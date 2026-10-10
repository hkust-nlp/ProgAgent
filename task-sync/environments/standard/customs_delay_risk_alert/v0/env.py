import os
import json
import csv
import re
import yaml
import sqlite3
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func

    return decorator


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

    # ── Tools ──────────────────────────────────────────────────────

    @tool(
        description="Query shipments with optional status filter. Returns paginated results. Use status='active' to get all shipments not yet cleared (in_transit, at_port, pending_clearance).",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status. Use 'active' for all non-completed shipments, or specify one of: in_transit, at_port, pending_clearance, cleared, delivered. Omit for all shipments.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page, maximum 20. Default 20.",
                },
            },
            "required": ["page"],
        },
    )
    def query_shipments(
        self, page: int, status: str = None, page_size: int = 20
    ) -> dict:
        page_size = min(int(page_size), 20)
        page = int(page)
        offset = (page - 1) * page_size

        conn = sqlite3.connect(self.db_path)

        base = """
            SELECT s.shipment_id, s.carrier_id, s.supplier_id, s.hs_code,
                   s.origin_port_id, s.dest_port_id, s.status,
                   s.eta, s.departure_date, s.declared_value,
                   s.container_count, s.weight_kg,
                   p1.port_name AS origin_port_name,
                   p2.port_name AS dest_port_name
            FROM shipments s
            JOIN ports p1 ON s.origin_port_id = p1.port_id
            JOIN ports p2 ON s.dest_port_id = p2.port_id
        """
        params: list = []
        if status:
            if status == "active":
                base += " WHERE s.status IN ('in_transit','at_port','pending_clearance')"
            else:
                base += " WHERE s.status = ?"
                params.append(status)

        count_q = f"SELECT COUNT(*) FROM ({base})"
        total = conn.execute(count_q, params).fetchone()[0]

        base += " ORDER BY s.shipment_id LIMIT ? OFFSET ?"
        params.extend([page_size, offset])

        rows = conn.execute(base, params).fetchall()
        conn.close()

        keys = [
            "shipment_id", "carrier_id", "supplier_id", "hs_code",
            "origin_port_id", "dest_port_id", "status",
            "eta", "departure_date", "declared_value",
            "container_count", "weight_kg",
            "origin_port_name", "dest_port_name",
        ]
        shipments = [dict(zip(keys, r)) for r in rows]

        return json.dumps({
            "shipments": shipments,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": offset + page_size < total,
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get current congestion data for a specific port by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "port_id": {
                    "type": "integer",
                    "description": "The port ID to look up.",
                }
            },
            "required": ["port_id"],
        },
    )
    def get_port_congestion(self, port_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT port_id, port_name, country, region, congestion_index, "
            "avg_wait_hours, vessel_queue_size, last_updated "
            "FROM ports WHERE port_id = ?",
            (int(port_id),),
        ).fetchone()
        conn.close()
        if not row:
            return json.dumps({"error": f"Port with ID {port_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(
            zip(
                [
                    "port_id", "port_name", "country", "region",
                    "congestion_index", "avg_wait_hours",
                    "vessel_queue_size", "last_updated",
                ],
                row,
            )
        ), ensure_ascii=False, default=str)

    @tool(
        description="Get information about a specific shipping carrier.",
        parameters={
            "type": "object",
            "properties": {
                "carrier_id": {
                    "type": "integer",
                    "description": "The carrier ID to look up.",
                }
            },
            "required": ["carrier_id"],
        },
    )
    def get_carrier_info(self, carrier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT carrier_id, carrier_name, country, fleet_size, on_time_rate, "
            "avg_transit_days, license_number "
            "FROM carriers WHERE carrier_id = ?",
            (int(carrier_id),),
        ).fetchone()
        conn.close()
        if not row:
            return json.dumps({"error": f"Carrier with ID {carrier_id} not found"}, ensure_ascii=False, default=str)
        return json.dumps(dict(
            zip(
                [
                    "carrier_id", "carrier_name", "country", "fleet_size",
                    "on_time_rate", "avg_transit_days", "license_number",
                ],
                row,
            )
        ), ensure_ascii=False, default=str)

    @tool(
        description="Get inspection and classification details for an HS code.",
        parameters={
            "type": "object",
            "properties": {
                "hs_code": {
                    "type": "string",
                    "description": "The 6-digit HS code to look up.",
                }
            },
            "required": ["hs_code"],
        },
    )
    def get_hs_code_info(self, hs_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT hs_code, description, category, base_inspection_rate, "
            "avg_clearance_days, restricted_flag "
            "FROM hs_codes WHERE hs_code = ?",
            (str(hs_code),),
        ).fetchone()
        conn.close()
        if not row:
            return _envelope({"error": f"HS code {hs_code} not found"})
        d = dict(
            zip(
                [
                    "hs_code", "description", "category",
                    "base_inspection_rate", "avg_clearance_days", "restricted_flag",
                ],
                row,
            )
        )
        d["restricted_flag"] = bool(d["restricted_flag"])
        return _envelope(d)

    @tool(
        description="Get basic record for a supplier by ID.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The supplier ID to look up.",
                }
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_record(self, supplier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT supplier_id, supplier_name, country, city, registration_date, "
            "product_category, contact_email "
            "FROM suppliers WHERE supplier_id = ?",
            (int(supplier_id),),
        ).fetchone()
        conn.close()
        if not row:
            return _envelope({"error": f"Supplier with ID {supplier_id} not found"})
        return _envelope(dict(
            zip(
                [
                    "supplier_id", "supplier_name", "country", "city",
                    "registration_date", "product_category", "contact_email",
                ],
                row,
            )
        ))

    # ── Helpers ────────────────────────────────────────────────────

    def _load_workspace_data(self):
        """Load all workspace files needed for risk computation."""
        # Config
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            config = yaml.safe_load(f)

        # Inspection overrides
        with open(os.path.join(self.workspace, "inspection_override_rules.json")) as f:
            override_data = json.load(f)
        override_map = {o["hs_code"]: o["bonus"] for o in override_data["overrides"]}

        # Supplier compliance
        supplier_compliance: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("supplier_compliance_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        supplier_compliance[entry["supplier_id"]] = entry

        # Carrier manifests
        manifest_map: Dict[str, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("carrier_manifest_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        manifest_map[row["shipment_id"]] = row

        # Port advisories
        port_disruptions: Dict[str, int] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("port_advisory_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                current_port = None
                for line in content.split("\n"):
                    if line.startswith("## "):
                        current_port = line[3:].strip()
                    elif "Additional Delay Factor:" in line and current_port:
                        factor = int(line.split(":")[-1].strip())
                        port_disruptions[current_port] = factor

        # Trade lane risks
        trade_lane_bonuses: Dict[tuple, int] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("trade_lane_risk_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                if data and "trade_lanes" in data:
                    for entry in data["trade_lanes"]:
                        key = (entry["origin"], entry["destination"])
                        trade_lane_bonuses[key] = entry["risk_bonus"]

        return config, override_map, supplier_compliance, manifest_map, port_disruptions, trade_lane_bonuses

    def _compute_shipment_risk(self, ship, config, override_map,
                               supplier_compliance, manifest_map,
                               port_disruptions, trade_lane_bonuses):
        """Compute risk score for a single shipment dict.

        ship must contain keys: shipment_id, dest_port_name, origin_port_name,
        dest_congestion, hs_code, base_inspection_rate, supplier_id,
        on_time_rate, carrier_name, supplier_name.
        """
        weights = config["weights"]
        sid = ship["shipment_id"]

        # 1. Port congestion raw
        port_raw = ship["dest_congestion"]
        if ship["dest_port_name"] in port_disruptions:
            port_raw += port_disruptions[ship["dest_port_name"]]
        port_raw = min(port_raw, 100)

        # 2. HS inspection raw
        hs_raw = ship["base_inspection_rate"] * 100
        if ship["hs_code"] in override_map:
            hs_raw += override_map[ship["hs_code"]]
        hs_raw = min(hs_raw, 100)

        # 3. Supplier compliance raw
        comp = supplier_compliance.get(ship["supplier_id"], {})
        tier = comp.get("compliance_tier", "unrated")
        tier_score = config["supplier_tier_scoring"].get(
            tier, config["supplier_tier_scoring"]["unrated"]
        )
        supplier_raw = tier_score
        if comp.get("violation_count", 0) > config["violation_threshold"]:
            supplier_raw += config["violation_penalty"]
        audit = comp.get("audit_status", "pending")
        supplier_raw += config["audit_penalties"].get(audit, 0)
        supplier_raw = min(supplier_raw, 100)

        # 4. Carrier reliability raw
        on_time_rate = ship["on_time_rate"]
        on_time_score = 10
        for bracket in config["carrier_on_time_brackets"]:
            if on_time_rate <= bracket["upper_bound"]:
                on_time_score = bracket["score"]
                break
        carrier_raw = on_time_score

        manifest = manifest_map.get(sid, {})
        handling = manifest.get("special_handling_code", "none")
        carrier_raw += config["special_handling_risk"].get(handling, 0)
        if manifest.get("documentation_complete", "yes") == "no":
            carrier_raw += config["documentation_incomplete_penalty"]
        carrier_raw = min(carrier_raw, 100)

        # Weighted sum
        w_port = weights["port_congestion"] * port_raw
        w_hs = weights["hs_inspection"] * hs_raw
        w_sup = weights["supplier_compliance"] * supplier_raw
        w_car = weights["carrier_reliability"] * carrier_raw

        total = w_port + w_hs + w_sup + w_car

        # Trade lane bonus
        lane_key = (ship["origin_port_name"], ship["dest_port_name"])
        if lane_key in trade_lane_bonuses:
            total += trade_lane_bonuses[lane_key]

        total = min(total, 100)
        total = round(total, 2)

        return total, w_port, w_hs, w_sup, w_car

    def _build_alert(self, ship, total_risk, w_port, w_hs, w_sup, w_car, config):
        """Build an alert dict if total_risk >= threshold, else None."""
        if total_risk < config["alert_threshold"]:
            return None

        risk_level = (
            "CRITICAL"
            if total_risk >= config["risk_levels"]["CRITICAL"]
            else "HIGH"
        )
        broker_priority = (
            "URGENT"
            if total_risk >= config["priority_levels"]["URGENT"]
            else "HIGH"
        )

        dim_scores = {
            "port_congestion": w_port,
            "hs_inspection": w_hs,
            "supplier_compliance": w_sup,
            "carrier_reliability": w_car,
        }
        dim_order = [
            "port_congestion", "hs_inspection",
            "supplier_compliance", "carrier_reliability",
        ]
        max_val = max(dim_scores.values())
        primary = next(d for d in dim_order if dim_scores[d] == max_val)

        return {
            "shipment_id": ship["shipment_id"],
            "carrier_name": ship["carrier_name"],
            "supplier_name": ship["supplier_name"],
            "destination_port": ship["dest_port_name"],
            "hs_code": ship["hs_code"],
            "risk_score": total_risk,
            "risk_level": risk_level,
            "primary_risk_factor": primary,
            "recommended_action": config["recommended_actions"][primary],
            "broker_priority": broker_priority,
        }

    def _compute_ground_truth(self) -> list:
        """Compute full ground-truth alert list using direct DB access."""
        config, override_map, supplier_compliance, manifest_map, \
            port_disruptions, trade_lane_bonuses = self._load_workspace_data()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT s.shipment_id, s.carrier_id, s.supplier_id, s.hs_code,
                   s.origin_port_id, s.dest_port_id, s.status,
                   p1.port_name  AS origin_port_name,
                   p2.port_name  AS dest_port_name,
                   p2.congestion_index AS dest_congestion,
                   c.carrier_name, c.on_time_rate,
                   sup.supplier_name,
                   h.base_inspection_rate
            FROM shipments s
            JOIN ports p1    ON s.origin_port_id = p1.port_id
            JOIN ports p2    ON s.dest_port_id   = p2.port_id
            JOIN carriers c  ON s.carrier_id     = c.carrier_id
            JOIN suppliers sup ON s.supplier_id  = sup.supplier_id
            JOIN hs_codes h  ON s.hs_code        = h.hs_code
            WHERE s.status IN ('in_transit','at_port','pending_clearance')
            ORDER BY s.shipment_id
            """
        ).fetchall()
        conn.close()

        alerts = []
        for r in rows:
            ship = dict(r)
            total, wp, wh, ws, wc = self._compute_shipment_risk(
                ship, config, override_map,
                supplier_compliance, manifest_map,
                port_disruptions, trade_lane_bonuses,
            )
            alert = self._build_alert(ship, total, wp, wh, ws, wc, config)
            if alert:
                alerts.append(alert)

        alerts.sort(key=lambda a: (-a["risk_score"], a["shipment_id"]))
        return alerts

    # ── Interface ──────────────────────────────────────────────────

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
        ground_truth = self._compute_ground_truth()
        truth_map = {a["shipment_id"]: a for a in ground_truth}

        eval_criteria: Dict[str, dict] = {}

        # ── 1. Alert file exists (10 pts) ──────────────────────────
        alert_path = os.path.join(self.workspace, "high_risk_alerts.csv")
        file_exists = os.path.isfile(alert_path)
        eval_criteria["alert_file_exists"] = {
            "passed": file_exists,
            "score": 10 if file_exists else 0,
            "max_score": 10,
        }
        if not file_exists:
            eval_criteria["alert_file_exists"]["reason"] = "high_risk_alerts.csv not found in workspace"

        # Early exit helper
        def _fill_remaining(names_pts):
            for n, p in names_pts:
                eval_criteria[n] = {
                    "passed": False, "score": 0, "max_score": p,
                    "reason": "Prerequisite criterion failed",
                }
            t = sum(c["score"] for c in eval_criteria.values())
            m = sum(c["max_score"] for c in eval_criteria.values())
            return t / max(m, 1), {
                "eval_criteria": eval_criteria,
                "total_score": t,
                "max_score": m,
            }

        remaining = [
            ("correct_columns", 10), ("shipment_identification", 25),
            ("risk_score_accuracy", 20), ("correct_sorting", 10),
            ("primary_risk_factor", 15), ("response_summary", 10),
        ]

        if not file_exists:
            return _fill_remaining(remaining)

        # Read agent CSV
        try:
            with open(alert_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_columns = list(reader.fieldnames) if reader.fieldnames else []
                agent_rows = list(reader)
        except Exception as e:
            eval_criteria["alert_file_exists"]["reason"] = f"CSV parse error: {e}"
            return _fill_remaining(remaining)

        # ── 2. Correct columns (10 pts) ───────────────────────────
        expected_cols = [
            "shipment_id", "carrier_name", "supplier_name", "destination_port",
            "hs_code", "risk_score", "risk_level", "primary_risk_factor",
            "recommended_action", "broker_priority",
        ]
        cols_ok = agent_columns == expected_cols
        eval_criteria["correct_columns"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
        }
        if not cols_ok:
            eval_criteria["correct_columns"]["reason"] = (
                f"Expected {expected_cols}, got {agent_columns}"
            )

        # ── 3. Shipment identification (25 pts) ───────────────────
        truth_ids = set(truth_map.keys())
        agent_ids = {r.get("shipment_id", "") for r in agent_rows}

        if not truth_ids and not agent_ids:
            f1 = 1.0
        elif not truth_ids or not agent_ids:
            f1 = 0.0
        else:
            tp = len(truth_ids & agent_ids)
            prec = tp / len(agent_ids) if agent_ids else 0
            rec = tp / len(truth_ids) if truth_ids else 0
            f1 = 2 * prec * rec / max(prec + rec, 1e-10)

        id_score = round(f1 * 25)
        eval_criteria["shipment_identification"] = {
            "passed": f1 >= 0.99,
            "score": id_score,
            "max_score": 25,
        }
        if f1 < 0.99:
            eval_criteria["shipment_identification"]["reason"] = (
                f"F1={f1:.3f}; expected {len(truth_ids)} shipments, "
                f"got {len(agent_ids)}, overlap {len(truth_ids & agent_ids)}"
            )

        # Build agent map
        agent_map: Dict[str, dict] = {}
        for r in agent_rows:
            sid = r.get("shipment_id", "")
            try:
                agent_map[sid] = {
                    "risk_score": float(r.get("risk_score", 0)),
                    "primary_risk_factor": r.get("primary_risk_factor", ""),
                    "risk_level": r.get("risk_level", ""),
                    "broker_priority": r.get("broker_priority", ""),
                }
            except (ValueError, TypeError):
                pass

        common = truth_ids & agent_ids

        # ── 4. Risk score accuracy (20 pts) ───────────────────────
        if common:
            accurate = sum(
                1 for sid in common
                if sid in agent_map
                and abs(agent_map[sid]["risk_score"] - truth_map[sid]["risk_score"]) <= 2.0
            )
            acc_pct = accurate / len(common)
        else:
            acc_pct = 0.0

        acc_score = round(acc_pct * 20)
        eval_criteria["risk_score_accuracy"] = {
            "passed": acc_pct >= 0.95,
            "score": acc_score,
            "max_score": 20,
        }
        if acc_pct < 0.95:
            eval_criteria["risk_score_accuracy"]["reason"] = (
                f"Only {acc_pct:.1%} of scores within +/-2.0 tolerance"
            )

        # ── 5. Correct sorting (10 pts) ───────────────────────────
        agent_order = []
        for r in agent_rows:
            try:
                agent_order.append((float(r["risk_score"]), r["shipment_id"]))
            except (ValueError, KeyError):
                agent_order.append((0.0, r.get("shipment_id", "")))

        expected_order = sorted(agent_order, key=lambda x: (-x[0], x[1]))
        sort_ok = agent_order == expected_order
        eval_criteria["correct_sorting"] = {
            "passed": sort_ok,
            "score": 10 if sort_ok else 0,
            "max_score": 10,
        }
        if not sort_ok:
            eval_criteria["correct_sorting"]["reason"] = (
                "Rows not sorted by risk_score desc / shipment_id asc"
            )

        # ── 6. Primary risk factor (15 pts) ───────────────────────
        if common:
            correct_prf = sum(
                1 for sid in common
                if sid in agent_map
                and agent_map[sid]["primary_risk_factor"] == truth_map[sid]["primary_risk_factor"]
            )
            prf_pct = correct_prf / len(common)
        else:
            prf_pct = 0.0

        prf_score = round(prf_pct * 15)
        eval_criteria["primary_risk_factor"] = {
            "passed": prf_pct >= 0.95,
            "score": prf_score,
            "max_score": 15,
        }
        if prf_pct < 0.95:
            eval_criteria["primary_risk_factor"]["reason"] = (
                f"Only {prf_pct:.1%} of primary risk factors correct"
            )

        # ── 7. Response summary (10 pts) ──────────────────────────
        summary_pts = 0
        expected_count = len(ground_truth)
        # Check count in response
        if re.search(r"(?<!\d)" + re.escape(str(expected_count)) + r"(?!\d)", action):
            summary_pts += 5

        # Check highest-risk shipment ID
        if ground_truth:
            highest_id = ground_truth[0]["shipment_id"]
            if highest_id in action:
                summary_pts += 5
        else:
            summary_pts += 5

        eval_criteria["response_summary"] = {
            "passed": summary_pts == 10,
            "score": summary_pts,
            "max_score": 10,
        }
        if summary_pts < 10:
            eval_criteria["response_summary"]["reason"] = (
                "Response missing expected total count or highest-risk shipment ID"
            )

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max(max_score, 1), {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

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
        # ── 1. Read workspace config / data files ─────────────────
        with open(os.path.join(self.workspace, "risk_scoring_config.yaml")) as f:
            config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "inspection_override_rules.json")) as f:
            override_data = json.load(f)
        override_map = {o["hs_code"]: o["bonus"] for o in override_data["overrides"]}

        # Supplier compliance
        supplier_compliance: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("supplier_compliance_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for entry in json.load(f):
                        supplier_compliance[entry["supplier_id"]] = entry

        # Carrier manifests
        manifest_map: Dict[str, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("carrier_manifest_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        manifest_map[row["shipment_id"]] = row

        # Port advisories
        port_disruptions: Dict[str, int] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("port_advisory_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    content = f.read()
                current_port = None
                for line in content.split("\n"):
                    if line.startswith("## "):
                        current_port = line[3:].strip()
                    elif "Additional Delay Factor:" in line and current_port:
                        factor = int(line.split(":")[-1].strip())
                        port_disruptions[current_port] = factor

        # Trade lane risks
        trade_lane_bonuses: Dict[tuple, int] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("trade_lane_risk_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = yaml.safe_load(f)
                if data and "trade_lanes" in data:
                    for entry in data["trade_lanes"]:
                        key = (entry["origin"], entry["destination"])
                        trade_lane_bonuses[key] = entry["risk_bonus"]

        weights = config["weights"]

        # ── 2. Query all active shipments via tools ───────────────
        all_shipments = []
        page = 1
        while True:
            result = json.loads(self.tools["query_shipments"](status="active", page=page, page_size=20))
            all_shipments.extend(result["shipments"])
            if not result["has_more"]:
                break
            page += 1

        # ── 3. Collect unique entity IDs ──────────────────────────
        unique_dest_ports = set()
        unique_carriers = set()
        unique_hs_codes = set()
        unique_suppliers = set()

        for s in all_shipments:
            unique_dest_ports.add(s["dest_port_id"])
            unique_carriers.add(s["carrier_id"])
            unique_hs_codes.add(s["hs_code"])
            unique_suppliers.add(s["supplier_id"])

        # ── 4. Fetch entity data via tools ────────────────────────
        port_info = {}
        for pid in sorted(unique_dest_ports):
            port_info[pid] = json.loads(self.tools["get_port_congestion"](port_id=pid))

        carrier_info = {}
        for cid in sorted(unique_carriers):
            carrier_info[cid] = json.loads(self.tools["get_carrier_info"](carrier_id=cid))

        hs_info = {}
        for hc in sorted(unique_hs_codes):
            hs_info[hc] = json.loads(self.tools["get_hs_code_info"](hs_code=hc)["content"][0]["text"])

        supplier_info = {}
        for sid in sorted(unique_suppliers):
            supplier_info[sid] = json.loads(self.tools["get_supplier_record"](supplier_id=sid)["content"][0]["text"])

        # ── 5. Compute risk scores ────────────────────────────────
        alerts = []
        for s in all_shipments:
            sid = s["shipment_id"]
            dest_pid = s["dest_port_id"]
            dest_port_name = s["dest_port_name"]
            origin_port_name = s["origin_port_name"]

            # Build enriched ship dict for _compute_shipment_risk
            ship = {
                "shipment_id": sid,
                "dest_port_name": dest_port_name,
                "origin_port_name": origin_port_name,
                "dest_congestion": port_info[dest_pid]["congestion_index"],
                "hs_code": s["hs_code"],
                "base_inspection_rate": hs_info[s["hs_code"]]["base_inspection_rate"],
                "supplier_id": s["supplier_id"],
                "on_time_rate": carrier_info[s["carrier_id"]]["on_time_rate"],
                "carrier_name": carrier_info[s["carrier_id"]]["carrier_name"],
                "supplier_name": supplier_info[s["supplier_id"]]["supplier_name"],
            }

            total, wp, wh, ws, wc = self._compute_shipment_risk(
                ship, config, override_map,
                supplier_compliance, manifest_map,
                port_disruptions, trade_lane_bonuses,
            )
            alert = self._build_alert(ship, total, wp, wh, ws, wc, config)
            if alert:
                alerts.append(alert)

        alerts.sort(key=lambda a: (-a["risk_score"], a["shipment_id"]))

        # ── 6. Write output CSV ───────────────────────────────────
        fieldnames = [
            "shipment_id", "carrier_name", "supplier_name", "destination_port",
            "hs_code", "risk_score", "risk_level", "primary_risk_factor",
            "recommended_action", "broker_priority",
        ]
        with open(os.path.join(self.workspace, "high_risk_alerts.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in alerts:
                row = dict(a)
                row["risk_score"] = f"{a['risk_score']:.2f}"
                writer.writerow(row)

        # ── 7. Construct action string ────────────────────────────
        if alerts:
            highest = alerts[0]
            action = (
                f"Risk assessment complete. Identified {len(alerts)} high-risk "
                f"shipments requiring proactive broker intervention. "
                f"The shipment with the highest composite risk score is "
                f"{highest['shipment_id']} with a score of {highest['risk_score']:.2f}."
            )
        else:
            action = "Risk assessment complete. No high-risk shipments identified."

        return self.step(action)
