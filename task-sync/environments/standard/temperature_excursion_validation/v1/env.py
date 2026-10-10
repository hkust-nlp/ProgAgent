from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import yaml
import math


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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List shipments filtered by status. Returns a paginated list of "
            "shipment IDs and their current status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": (
                        "Filter by shipment status "
                        "(e.g. 'pending_review', 'released', 'quarantined')"
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 50, max 50)",
                },
            },
            "required": ["status"],
        },
    )
    def list_shipments(self, status: str, page: int = 1, page_size: int = 50) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM shipments WHERE status = ?", (status,)
        )
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT shipment_id, status FROM shipments "
            "WHERE status = ? ORDER BY shipment_id LIMIT ? OFFSET ?",
            (status, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "shipments": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @tool(
        description=(
            "Get detailed information for a specific shipment, including "
            "product ID, carrier ID, warehouse IDs, dates, and quantities."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "The shipment ID (e.g. 'SHP-0001')",
                },
            },
            "required": ["shipment_id"],
        },
    )
    def get_shipment_details(self, shipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM shipments WHERE shipment_id = ?", (shipment_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Shipment {shipment_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Get temperature log readings for a specific shipment. Returns "
            "all recorded temperature readings with timestamps and sensor IDs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "The shipment ID (e.g. 'SHP-0001')",
                },
            },
            "required": ["shipment_id"],
        },
    )
    def get_temperature_log(self, shipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT timestamp, temperature, sensor_id "
            "FROM temperature_logs WHERE shipment_id = ? ORDER BY timestamp",
            (shipment_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"shipment_id": shipment_id, "readings": rows}

    @tool(
        description=(
            "Get product information including name, category, storage class, "
            "and acceptable temperature range."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID (e.g. 'PROD-0001')",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_product_info(self, product_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Product {product_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Get incident reports associated with a specific shipment. "
            "Returns all incidents linked to the given shipment ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "The shipment ID (e.g. 'SHP-0001')",
                },
            },
            "required": ["shipment_id"],
        },
    )
    def get_incident_reports(self, shipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT incident_id, incident_type, severity, incident_date, description "
            "FROM incidents WHERE shipment_id = ? ORDER BY incident_id",
            (shipment_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"shipment_id": shipment_id, "incidents": rows}

    # ------------------------------------------------------------------
    # Helper: compute ground-truth disposition for all pending shipments
    # ------------------------------------------------------------------

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the expected disposition roster from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. All pending_review shipments
        cur.execute(
            "SELECT * FROM shipments WHERE status = 'pending_review' "
            "ORDER BY shipment_id"
        )
        pending = [dict(r) for r in cur.fetchall()]

        # 2. Product info cache
        cur.execute("SELECT * FROM products")
        products = {r["product_id"]: dict(r) for r in cur.fetchall()}

        # 3. Temperature logs per shipment
        temp_logs = {}
        for s in pending:
            sid = s["shipment_id"]
            cur.execute(
                "SELECT timestamp, temperature FROM temperature_logs "
                "WHERE shipment_id = ? ORDER BY timestamp",
                (sid,),
            )
            temp_logs[sid] = [dict(r) for r in cur.fetchall()]

        # 4. Incidents per shipment
        incidents_map = {}
        for s in pending:
            sid = s["shipment_id"]
            cur.execute(
                "SELECT severity FROM incidents WHERE shipment_id = ?",
                (sid,),
            )
            incidents_map[sid] = [dict(r) for r in cur.fetchall()]

        conn.close()

        # 5. Workspace: stability profiles
        stability = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("stability_profiles_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    stability.update(json.load(f))

        # 6. Workspace: carrier certifications
        carrier_certs = {}
        cert_path = os.path.join(self.workspace, "carrier_certifications.csv")
        with open(cert_path) as f:
            for row in csv.DictReader(f):
                carrier_certs[row["carrier_id"]] = row["cold_chain_certified"] == "yes"

        # 7. Workspace: warehouse thermal compliance
        warehouse_compliant = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("thermal_mapping_report_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        wid = row["warehouse_id"]
                        if wid not in warehouse_compliant:
                            warehouse_compliant[wid] = True
                        if row["compliance_status"] == "FAIL":
                            warehouse_compliant[wid] = False

        # 8. Build roster
        severity_rank = {"none": 0, "minor": 1, "moderate": 2, "major": 3, "critical": 4}
        roster = []
        for s in pending:
            sid = s["shipment_id"]
            pid = s["product_id"]
            product = products[pid]
            min_t = product["min_temp"]
            max_t = product["max_temp"]
            readings = temp_logs[sid]

            # Excursion analysis
            excursion_readings = []
            max_deviation = 0.0
            for r in readings:
                temp = r["temperature"]
                if temp < min_t:
                    dev = min_t - temp
                elif temp > max_t:
                    dev = temp - max_t
                else:
                    dev = 0.0
                if dev > 0:
                    excursion_readings.append(r)
                    max_deviation = max(max_deviation, dev)

            excursion_detected = len(excursion_readings) > 0
            max_deviation = round(max_deviation, 2)

            # Duration calculation (proportional method)
            if excursion_detected and len(readings) >= 2:
                from datetime import datetime as dt
                first_ts = dt.strptime(readings[0]["timestamp"], "%Y-%m-%dT%H:%M:%S")
                last_ts = dt.strptime(readings[-1]["timestamp"], "%Y-%m-%dT%H:%M:%S")
                span_min = (last_ts - first_ts).total_seconds() / 60.0
                excursion_duration = round(
                    (len(excursion_readings) / len(readings)) * span_min
                )
            elif excursion_detected:
                excursion_duration = 60  # fallback
            else:
                excursion_duration = 0

            # Highest incident severity
            incs = incidents_map[sid]
            if incs:
                highest_sev = max(incs, key=lambda x: severity_rank.get(x["severity"], 0))["severity"]
            else:
                highest_sev = "none"

            # Carrier certification
            carrier_cert = carrier_certs.get(s["carrier_id"], True)

            # Stability tolerance
            stab = stability.get(pid, {}).get("stability_tolerance", {})
            stab_max_dev = stab.get("max_allowed_deviation_celsius", 999)
            stab_max_dur = stab.get("max_allowed_duration_minutes", 99999)

            # Warehouse compliance
            origin_ok = warehouse_compliant.get(s["origin_warehouse_id"], True)
            dest_ok = warehouse_compliant.get(s["destination_warehouse_id"], True)
            wh_compliant = origin_ok and dest_ok

            # Disposition logic (priority order from policy)
            if not excursion_detected:
                disposition = "RELEASE"
                reason = "No temperature excursion detected"
            elif not carrier_cert:
                disposition = "QUARANTINE"
                reason = "Carrier not cold chain certified"
            elif highest_sev == "critical":
                disposition = "QUARANTINE"
                reason = "Critical incident reported"
            elif max_deviation > stab_max_dev or excursion_duration > stab_max_dur:
                disposition = "QUARANTINE"
                reason = "Excursion exceeds stability tolerance"
            elif not wh_compliant:
                disposition = "QUARANTINE"
                reason = "Warehouse thermal noncompliance"
            elif severity_rank.get(highest_sev, 0) >= severity_rank["moderate"]:
                disposition = "QUARANTINE"
                reason = "Incident severity moderate or higher"
            else:
                disposition = "RELEASE"
                reason = "Excursion within stability tolerance"

            roster.append({
                "shipment_id": sid,
                "product_id": pid,
                "product_name": product["product_name"],
                "excursion_detected": "yes" if excursion_detected else "no",
                "max_deviation_celsius": f"{max_deviation:.2f}",
                "excursion_duration_minutes": str(excursion_duration),
                "highest_incident_severity": highest_sev,
                "carrier_certified": "yes" if carrier_cert else "no",
                "disposition": disposition,
                "reason": reason,
            })

        roster.sort(key=lambda x: x["shipment_id"])
        return roster

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        gt_map = {r["shipment_id"]: r for r in ground_truth}
        total_pending = len(ground_truth)

        eval_criteria = {}

        # --- Criterion 1: Roster file exists (10 pts) ---
        roster_path = os.path.join(self.workspace, "disposition_roster.csv")
        file_exists = os.path.isfile(roster_path)
        eval_criteria["roster_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            eval_criteria["roster_file_exists"]["reason"] = "disposition_roster.csv not found"

        # Try to parse the roster
        agent_rows = []
        parse_ok = False
        if file_exists:
            try:
                with open(roster_path, newline="") as f:
                    reader = csv.DictReader(f)
                    agent_rows = list(reader)
                parse_ok = True
            except Exception as e:
                parse_ok = False

        # --- Criterion 2: Correct columns (10 pts) ---
        expected_cols = [
            "shipment_id", "product_id", "product_name",
            "excursion_detected", "max_deviation_celsius",
            "excursion_duration_minutes", "highest_incident_severity",
            "carrier_certified", "disposition", "reason",
        ]
        if parse_ok and agent_rows:
            actual_cols = list(agent_rows[0].keys())
            cols_match = actual_cols == expected_cols
        else:
            actual_cols = []
            cols_match = False
        eval_criteria["correct_columns"] = {
            "passed": cols_match,
            "score": 10 if cols_match else 0,
            "max_score": 10,
        }
        if not cols_match:
            eval_criteria["correct_columns"]["reason"] = (
                f"Expected columns {expected_cols}, got {actual_cols}"
            )

        # --- Criterion 3: Correct row count (15 pts) ---
        row_count_ok = len(agent_rows) == total_pending
        eval_criteria["correct_row_count"] = {
            "passed": row_count_ok,
            "score": 15 if row_count_ok else 0,
            "max_score": 15,
        }
        if not row_count_ok:
            eval_criteria["correct_row_count"]["reason"] = (
                f"Expected {total_pending} rows, got {len(agent_rows)}"
            )

        # --- Criterion 4: Excursion detection accuracy (20 pts) ---
        if agent_rows and total_pending > 0:
            excursion_correct = 0
            for ar in agent_rows:
                sid = ar.get("shipment_id", "")
                if sid in gt_map:
                    if ar.get("excursion_detected", "").strip().lower() == gt_map[sid]["excursion_detected"]:
                        excursion_correct += 1
            excursion_score = round(20 * excursion_correct / total_pending, 2)
            excursion_pass = excursion_correct == total_pending
        else:
            excursion_score = 0
            excursion_pass = False
            excursion_correct = 0
        eval_criteria["excursion_detection"] = {
            "passed": excursion_pass,
            "score": excursion_score,
            "max_score": 20,
        }
        if not excursion_pass:
            eval_criteria["excursion_detection"]["reason"] = (
                f"{excursion_correct}/{total_pending} excursions correctly identified"
            )

        # --- Criterion 5: Disposition accuracy (30 pts) ---
        if agent_rows and total_pending > 0:
            disp_correct = 0
            for ar in agent_rows:
                sid = ar.get("shipment_id", "")
                if sid in gt_map:
                    if ar.get("disposition", "").strip().upper() == gt_map[sid]["disposition"]:
                        disp_correct += 1
            disp_score = round(30 * disp_correct / total_pending, 2)
            disp_pass = disp_correct == total_pending
        else:
            disp_score = 0
            disp_pass = False
            disp_correct = 0
        eval_criteria["disposition_accuracy"] = {
            "passed": disp_pass,
            "score": disp_score,
            "max_score": 30,
        }
        if not disp_pass:
            eval_criteria["disposition_accuracy"]["reason"] = (
                f"{disp_correct}/{total_pending} dispositions correct"
            )

        # --- Criterion 6: Sort order (5 pts) ---
        if agent_rows:
            sids = [r.get("shipment_id", "") for r in agent_rows]
            sorted_ok = sids == sorted(sids)
        else:
            sorted_ok = False
        eval_criteria["sort_order"] = {
            "passed": sorted_ok,
            "score": 5 if sorted_ok else 0,
            "max_score": 5,
        }
        if not sorted_ok:
            eval_criteria["sort_order"]["reason"] = "Rows not sorted by shipment_id ascending"

        # --- Criterion 7: Summary in response (10 pts) ---
        gt_release = sum(1 for r in ground_truth if r["disposition"] == "RELEASE")
        gt_quarantine = sum(1 for r in ground_truth if r["disposition"] == "QUARANTINE")
        action_lower = action.lower() if action else ""
        has_total = str(total_pending) in action
        has_release = str(gt_release) in action
        has_quarantine = str(gt_quarantine) in action
        summary_ok = has_total and has_release and has_quarantine
        summary_score = 0
        if has_total:
            summary_score += 4
        if has_release:
            summary_score += 3
        if has_quarantine:
            summary_score += 3
        eval_criteria["response_summary"] = {
            "passed": summary_ok,
            "score": summary_score,
            "max_score": 10,
        }
        if not summary_ok:
            eval_criteria["response_summary"]["reason"] = (
                f"Expected counts: total={total_pending}, "
                f"release={gt_release}, quarantine={gt_quarantine}"
            )

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

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
        from datetime import datetime as dt

        # ---- Read workspace files ----

        # Stability profiles
        stability = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("stability_profiles_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    stability.update(json.load(f))

        # Carrier certifications
        carrier_certs = {}
        for fname in os.listdir(self.workspace):
            if fname == "carrier_certifications.csv":
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        carrier_certs[row["carrier_id"]] = (
                            row["cold_chain_certified"] == "yes"
                        )

        # Warehouse thermal compliance
        warehouse_compliant = {}
        for fname in os.listdir(self.workspace):
            if fname.startswith("thermal_mapping_report_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        wid = row["warehouse_id"]
                        if wid not in warehouse_compliant:
                            warehouse_compliant[wid] = True
                        if row["compliance_status"] == "FAIL":
                            warehouse_compliant[wid] = False

        # ---- Use tools to gather DB data ----
        severity_rank = {"none": 0, "minor": 1, "moderate": 2, "major": 3, "critical": 4}

        # Collect all pending shipments (paginate)
        all_pending_ids = []
        page = 1
        while True:
            result = self.tools["list_shipments"](status="pending_review", page=page, page_size=50)
            all_pending_ids.extend([s["shipment_id"] for s in result["shipments"]])
            if page * 50 >= result["total"]:
                break
            page += 1

        # Cache product info
        product_cache = {}

        roster = []
        for sid in all_pending_ids:
            # Get shipment details
            details = self.tools["get_shipment_details"](shipment_id=sid)

            pid = details["product_id"]

            # Get product info (with caching)
            if pid not in product_cache:
                product_cache[pid] = self.tools["get_product_info"](product_id=pid)
            product = product_cache[pid]

            min_t = product["min_temp"]
            max_t = product["max_temp"]

            # Get temperature log
            temp_result = self.tools["get_temperature_log"](shipment_id=sid)
            readings = temp_result["readings"]

            # Excursion analysis
            excursion_count = 0
            max_deviation = 0.0
            for r in readings:
                temp = r["temperature"]
                if temp < min_t:
                    dev = min_t - temp
                elif temp > max_t:
                    dev = temp - max_t
                else:
                    dev = 0.0
                if dev > 0:
                    excursion_count += 1
                    max_deviation = max(max_deviation, dev)

            excursion_detected = excursion_count > 0
            max_deviation = round(max_deviation, 2)

            # Duration (proportional)
            if excursion_detected and len(readings) >= 2:
                first_ts = dt.strptime(readings[0]["timestamp"], "%Y-%m-%dT%H:%M:%S")
                last_ts = dt.strptime(readings[-1]["timestamp"], "%Y-%m-%dT%H:%M:%S")
                span_min = (last_ts - first_ts).total_seconds() / 60.0
                excursion_duration = round(
                    (excursion_count / len(readings)) * span_min
                )
            elif excursion_detected:
                excursion_duration = 60
            else:
                excursion_duration = 0

            # Incidents
            inc_result = self.tools["get_incident_reports"](shipment_id=sid)
            incs = inc_result["incidents"]
            if incs:
                highest_sev = max(
                    incs, key=lambda x: severity_rank.get(x["severity"], 0)
                )["severity"]
            else:
                highest_sev = "none"

            # Carrier certification
            carrier_cert = carrier_certs.get(details["carrier_id"], True)

            # Stability tolerance
            stab = stability.get(pid, {}).get("stability_tolerance", {})
            stab_max_dev = stab.get("max_allowed_deviation_celsius", 999)
            stab_max_dur = stab.get("max_allowed_duration_minutes", 99999)

            # Warehouse compliance
            origin_ok = warehouse_compliant.get(details["origin_warehouse_id"], True)
            dest_ok = warehouse_compliant.get(details["destination_warehouse_id"], True)
            wh_compliant = origin_ok and dest_ok

            # Disposition decision
            if not excursion_detected:
                disposition = "RELEASE"
                reason = "No temperature excursion detected"
            elif not carrier_cert:
                disposition = "QUARANTINE"
                reason = "Carrier not cold chain certified"
            elif highest_sev == "critical":
                disposition = "QUARANTINE"
                reason = "Critical incident reported"
            elif max_deviation > stab_max_dev or excursion_duration > stab_max_dur:
                disposition = "QUARANTINE"
                reason = "Excursion exceeds stability tolerance"
            elif not wh_compliant:
                disposition = "QUARANTINE"
                reason = "Warehouse thermal noncompliance"
            elif severity_rank.get(highest_sev, 0) >= severity_rank["moderate"]:
                disposition = "QUARANTINE"
                reason = "Incident severity moderate or higher"
            else:
                disposition = "RELEASE"
                reason = "Excursion within stability tolerance"

            roster.append({
                "shipment_id": sid,
                "product_id": pid,
                "product_name": product["product_name"],
                "excursion_detected": "yes" if excursion_detected else "no",
                "max_deviation_celsius": f"{max_deviation:.2f}",
                "excursion_duration_minutes": str(excursion_duration),
                "highest_incident_severity": highest_sev,
                "carrier_certified": "yes" if carrier_cert else "no",
                "disposition": disposition,
                "reason": reason,
            })

        roster.sort(key=lambda x: x["shipment_id"])

        # ---- Write deliverable ----
        roster_path = os.path.join(self.workspace, "disposition_roster.csv")
        fieldnames = [
            "shipment_id", "product_id", "product_name",
            "excursion_detected", "max_deviation_celsius",
            "excursion_duration_minutes", "highest_incident_severity",
            "carrier_certified", "disposition", "reason",
        ]
        with open(roster_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(roster)

        # Summary counts
        n_release = sum(1 for r in roster if r["disposition"] == "RELEASE")
        n_quarantine = sum(1 for r in roster if r["disposition"] == "QUARANTINE")

        action = (
            f"Temperature excursion review complete. "
            f"Total shipments reviewed: {len(roster)}. "
            f"Recommended for release: {n_release}. "
            f"Recommended for quarantine: {n_quarantine}. "
            f"Disposition roster saved to disposition_roster.csv."
        )

        return self.step(action)
