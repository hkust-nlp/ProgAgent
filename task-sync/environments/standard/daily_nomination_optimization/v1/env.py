import sqlite3
import os
import json
import csv
import math
import re
import glob as glob_mod
from typing import Tuple, Dict, List, Any

try:
    import yaml
except ImportError:
    yaml = None


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

    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions in OpenAI function calling format.
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

    # ── Tool methods ──────────────────────────────────────────────────────

    @tool(
        description="List shippers with pagination. Returns up to 20 shippers per page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                }
            },
            "required": ["page"],
        },
    )
    def list_shippers(self, page: int) -> dict:
        page = int(page)
        limit = 20
        offset = (page - 1) * limit
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM shippers")
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / limit))
        cur.execute(
            "SELECT shipper_id, shipper_name FROM shippers ORDER BY shipper_id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [{"shipper_id": r[0], "shipper_name": r[1]} for r in cur.fetchall()]
        conn.close()
        return _envelope({"shippers": rows, "page": page, "total_pages": total_pages})

    @tool(
        description="Get all nominations for a specific shipper.",
        parameters={
            "type": "object",
            "properties": {
                "shipper_id": {
                    "type": "string",
                    "description": "The shipper ID, e.g. 'SHIP-0001'.",
                }
            },
            "required": ["shipper_id"],
        },
    )
    def get_shipper_nominations(self, shipper_id: str) -> Any:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT shipper_id FROM shippers WHERE shipper_id = ?", (shipper_id,)
        )
        if cur.fetchone() is None:
            conn.close()
            return _envelope({"error": "Shipper not found"})
        cur.execute(
            "SELECT segment_id, daily_volume_mmbtu FROM nominations WHERE shipper_id = ? ORDER BY segment_id",
            (shipper_id,),
        )
        rows = [
            {"segment_id": r[0], "daily_volume_mmbtu": r[1]} for r in cur.fetchall()
        ]
        conn.close()
        return _envelope(rows)

    @tool(
        description="List pipeline segments with pagination. Returns up to 20 segments per page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                }
            },
            "required": ["page"],
        },
    )
    def list_pipeline_segments(self, page: int) -> dict:
        page = int(page)
        limit = 20
        offset = (page - 1) * limit
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pipeline_segments")
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / limit))
        cur.execute(
            "SELECT segment_id, segment_name, from_node, to_node FROM pipeline_segments ORDER BY segment_id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [
            {
                "segment_id": r[0],
                "segment_name": r[1],
                "from_node": r[2],
                "to_node": r[3],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return json.dumps({"segments": rows, "page": page, "total_pages": total_pages}, ensure_ascii=False, default=str)

    @tool(
        description="Get all 24 hourly sensor readings for a specific pipeline segment.",
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {
                    "type": "string",
                    "description": "The segment ID, e.g. 'SEG-0001'.",
                }
            },
            "required": ["segment_id"],
        },
    )
    def get_segment_sensor_data(self, segment_id: str) -> Any:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT segment_id FROM pipeline_segments WHERE segment_id = ?",
            (segment_id,),
        )
        if cur.fetchone() is None:
            conn.close()
            return json.dumps({"error": "Segment not found"}, ensure_ascii=False, default=str)
        cur.execute(
            "SELECT hour, pressure_psi, flow_rate_mmbtu_hr, temperature_f "
            "FROM sensor_readings WHERE segment_id = ? ORDER BY hour",
            (segment_id,),
        )
        rows = [
            {
                "hour": r[0],
                "pressure_psi": r[1],
                "flow_rate_mmbtu_hr": r[2],
                "temperature_f": r[3],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return json.dumps(rows, ensure_ascii=False, default=str)

    @tool(
        description="List customers with pagination. Returns up to 20 customers per page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                }
            },
            "required": ["page"],
        },
    )
    def list_customers(self, page: int) -> dict:
        page = int(page)
        limit = 20
        offset = (page - 1) * limit
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM customers")
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / limit))
        cur.execute(
            "SELECT customer_id, customer_name, connected_segment_id FROM customers ORDER BY customer_id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [
            {
                "customer_id": r[0],
                "customer_name": r[1],
                "connected_segment_id": r[2],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return _envelope({"customers": rows, "page": page, "total_pages": total_pages})

    @tool(
        description="Get 24 hourly demand forecasts for a specific customer.",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The customer ID, e.g. 'CUST-0001'.",
                }
            },
            "required": ["customer_id"],
        },
    )
    def get_customer_demand_forecast(self, customer_id: str) -> Any:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT customer_id FROM customers WHERE customer_id = ?", (customer_id,)
        )
        if cur.fetchone() is None:
            conn.close()
            return _envelope({"error": "Customer not found"})
        cur.execute(
            "SELECT hour, forecasted_demand_mmbtu FROM demand_forecasts WHERE customer_id = ? ORDER BY hour",
            (customer_id,),
        )
        rows = [
            {"hour": r[0], "forecasted_demand_mmbtu": r[1]} for r in cur.fetchall()
        ]
        conn.close()
        return _envelope(rows)

    @tool(
        description="List compressor stations with pagination. Returns up to 20 stations per page.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                }
            },
            "required": ["page"],
        },
    )
    def list_compressor_stations(self, page: int) -> dict:
        page = int(page)
        limit = 20
        offset = (page - 1) * limit
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM compressor_stations")
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / limit))
        cur.execute(
            "SELECT station_id, station_name, segment_id FROM compressor_stations ORDER BY station_id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [
            {
                "station_id": r[0],
                "station_name": r[1],
                "segment_id": r[2],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return json.dumps({"stations": rows, "page": page, "total_pages": total_pages}, ensure_ascii=False, default=str)

    @tool(
        description="Get 24 hourly compressor log entries for a specific station.",
        parameters={
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "string",
                    "description": "The compressor station ID, e.g. 'COMP-0001'.",
                }
            },
            "required": ["station_id"],
        },
    )
    def get_compressor_log(self, station_id: str) -> Any:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT station_id FROM compressor_stations WHERE station_id = ?",
            (station_id,),
        )
        if cur.fetchone() is None:
            conn.close()
            return json.dumps({"error": "Compressor station not found"}, ensure_ascii=False, default=str)
        cur.execute(
            "SELECT hour, fuel_consumed_mmbtu, throughput_mmbtu_hr "
            "FROM compressor_logs WHERE station_id = ? ORDER BY hour",
            (station_id,),
        )
        rows = [
            {
                "hour": r[0],
                "fuel_consumed_mmbtu": r[1],
                "throughput_mmbtu_hr": r[2],
            }
            for r in cur.fetchall()
        ]
        conn.close()
        return json.dumps(rows, ensure_ascii=False, default=str)

    # ── Helpers for ground truth computation ──────────────────────────────

    def _load_segment_specs(self) -> Dict[str, dict]:
        """Load all segment specs from workspace YAML files."""
        specs = {}
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "segment_specs_*.yaml"))):
            if yaml is not None:
                with open(fpath) as f:
                    data = yaml.safe_load(f)
            else:
                with open(fpath) as f:
                    text = f.read()
                data = {"segments": []}
                current = {}
                for line in text.split("\n"):
                    line_s = line.strip()
                    if line_s.startswith("- segment_id:"):
                        if current:
                            data["segments"].append(current)
                        current = {"segment_id": line_s.split(":", 1)[1].strip()}
                    elif ":" in line_s and current and not line_s.startswith("segments"):
                        k, v = line_s.split(":", 1)
                        k = k.strip()
                        v = v.strip()
                        try:
                            v = float(v)
                        except ValueError:
                            pass
                        current[k] = v
                if current:
                    data["segments"].append(current)
            for seg in data.get("segments", []):
                specs[seg["segment_id"]] = seg
        return specs

    def _load_shipper_contracts(self) -> Dict[str, dict]:
        """Load all shipper contracts from workspace JSON files."""
        contracts = {}
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "shipper_contracts_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
            for c in data:
                contracts[c["shipper_id"]] = c
        return contracts

    def _load_customer_profiles(self) -> Dict[str, dict]:
        """Load all customer profiles from workspace CSV files."""
        profiles = {}
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "customer_profiles_*.csv"))):
            with open(fpath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    profiles[row["customer_id"]] = {
                        "customer_id": row["customer_id"],
                        "customer_type": row["customer_type"],
                        "min_delivery_obligation_mmbtu_hr": float(row["min_delivery_obligation_mmbtu_hr"]),
                        "criticality": row["criticality"],
                    }
        return profiles

    def _load_fuel_prices(self) -> Dict[int, float]:
        """Load fuel prices from workspace JSON."""
        with open(os.path.join(self.workspace, "fuel_prices.json")) as f:
            data = json.load(f)
        return {int(k): v for k, v in data.items()}

    def _compute_ground_truth(self):
        """Compute the full ground truth from DB + workspace files."""
        seg_specs = self._load_segment_specs()
        shipper_contracts = self._load_shipper_contracts()
        customer_profiles = self._load_customer_profiles()
        fuel_prices = self._load_fuel_prices()

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Load all nominations
        cur.execute("SELECT shipper_id, segment_id, daily_volume_mmbtu FROM nominations")
        nominations = cur.fetchall()

        # Build seg -> [(shipper_id, daily_vol)]
        seg_noms = {}
        for sid, seg, vol in nominations:
            seg_noms.setdefault(seg, []).append((sid, vol))

        # Load all sensor readings
        cur.execute("SELECT segment_id, hour, pressure_psi FROM sensor_readings")
        sensor = {}
        for seg, h, p in cur.fetchall():
            sensor[(seg, h)] = p

        # Load customer -> connected_segment
        cur.execute("SELECT customer_id, connected_segment_id FROM customers")
        cust_seg = {}
        for cid, seg in cur.fetchall():
            cust_seg[cid] = seg

        # Build segment -> sum of min_delivery_obligation
        seg_min_delivery = {}
        for cid, prof in customer_profiles.items():
            seg = cust_seg.get(cid)
            if seg:
                seg_min_delivery[seg] = seg_min_delivery.get(seg, 0.0) + prof["min_delivery_obligation_mmbtu_hr"]

        # Load compressor data
        cur.execute("SELECT station_id, segment_id FROM compressor_stations")
        station_seg = {}
        for station_id, seg in cur.fetchall():
            station_seg[station_id] = seg

        cur.execute("SELECT station_id, hour, fuel_consumed_mmbtu FROM compressor_logs")
        comp_logs = {}
        for station_id, h, fuel in cur.fetchall():
            comp_logs[(station_id, h)] = fuel

        conn.close()

        all_segs = sorted(seg_specs.keys())

        dispatch_rows = []
        curtailment_rows = []

        for seg in all_segs:
            spec = seg_specs[seg]
            max_cap = spec["max_capacity_mmbtu_hr"]
            min_p = spec["min_pressure_psi"]
            max_p = spec["max_pressure_psi"]
            shippers_on_seg = seg_noms.get(seg, [])
            min_del = seg_min_delivery.get(seg, 0.0)

            for h in range(24):
                shipper_hourly = []
                total_nom = 0.0
                for sid, daily_vol in shippers_on_seg:
                    contract = shipper_contracts.get(sid)
                    if contract is None:
                        continue
                    hourly_profile = contract["hourly_profile"]
                    hourly_nom = daily_vol * hourly_profile[h]
                    priority = contract["priority_tier"]
                    shipper_hourly.append((sid, hourly_nom, priority))
                    total_nom += hourly_nom

                pressure = sensor.get((seg, h))
                if pressure is not None and pressure > max_p:
                    eff_cap = max_cap * 0.85
                elif pressure is not None and pressure < min_p:
                    eff_cap = max_cap * 0.90
                else:
                    eff_cap = max_cap

                is_constrained = total_nom > eff_cap
                if is_constrained:
                    curtailment_needed = total_nom - eff_cap
                    max_curtailable = max(0.0, total_nom - min_del)
                    actual_curtailment = min(curtailment_needed, max_curtailable)
                    adjusted_flow = total_nom - actual_curtailment

                    shipper_hourly.sort(key=lambda x: (-x[2], x[0]))
                    remaining = actual_curtailment
                    for sid, hourly_nom, priority in shipper_hourly:
                        curtailed = min(remaining, hourly_nom)
                        curtailment_rows.append((
                            seg, h, sid, priority,
                            hourly_nom, curtailed, hourly_nom - curtailed,
                        ))
                        remaining -= curtailed

                    dispatch_rows.append((
                        seg, h, total_nom, eff_cap, adjusted_flow, True, actual_curtailment,
                    ))

        # Fuel cost computation
        fuel_cost_rows = []
        total_fuel_cost = 0.0
        for (station_id, h), fuel in sorted(comp_logs.items()):
            seg = station_seg[station_id]
            price = fuel_prices.get(h, 0.0)
            cost = fuel * price
            total_fuel_cost += cost
            fuel_cost_rows.append((station_id, seg, h, fuel, price, cost))

        total_curtailment = sum(r[6] for r in dispatch_rows)
        total_constrained = len(dispatch_rows)

        return {
            "dispatch_rows": dispatch_rows,
            "curtailment_rows": curtailment_rows,
            "fuel_cost_rows": fuel_cost_rows,
            "total_fuel_cost": total_fuel_cost,
            "total_curtailment": total_curtailment,
            "total_constrained": total_constrained,
        }

    # ── step ─────────────────────────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        gt = self._compute_ground_truth()
        eval_criteria = {}
        total_score = 0.0
        max_score = 100.0

        # 1. dispatch_instructions.csv format (10 pts)
        dispatch_path = os.path.join(self.workspace, "dispatch_instructions.csv")
        dispatch_score = 0.0
        dispatch_reason = ""
        agent_dispatch = {}
        expected_cols = [
            "segment_id", "hour", "total_nominated", "effective_capacity",
            "adjusted_flow", "is_constrained", "curtailment_volume",
        ]
        if os.path.isfile(dispatch_path):
            try:
                with open(dispatch_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_cols):
                        rows = list(reader)
                        for row in rows:
                            key = (row["segment_id"].strip(), int(row["hour"]))
                            agent_dispatch[key] = row
                        dispatch_score = 10.0
                    else:
                        missing = [c for c in expected_cols if c not in cols]
                        dispatch_score = 2.0
                        dispatch_reason = f"Missing columns: {missing}"
            except Exception as e:
                dispatch_reason = f"Error reading file: {e}"
        else:
            dispatch_reason = "File not found"
        eval_criteria["dispatch_instructions_format"] = {
            "passed": dispatch_score == 10.0,
            "score": dispatch_score,
            "max_score": 10.0,
            **({"reason": dispatch_reason} if dispatch_score < 10.0 else {}),
        }
        total_score += dispatch_score

        # Build ground truth sets
        gt_constrained = set()
        gt_eff_cap = {}
        gt_curtailment = {}
        for row in gt["dispatch_rows"]:
            seg, h, total_nom, eff_cap, adj_flow, is_const, curt = row
            key = (seg, h)
            gt_constrained.add(key)
            gt_eff_cap[key] = eff_cap
            gt_curtailment[key] = curt

        # 2. Constrained segment-hours identification (20 pts)
        agent_constrained = set(agent_dispatch.keys())
        f1 = 0.0
        if len(gt_constrained) > 0:
            correct = len(gt_constrained & agent_constrained)
            total_gt = len(gt_constrained)
            precision = correct / max(1, len(agent_constrained)) if agent_constrained else 0
            recall = correct / total_gt
            if precision + recall > 0:
                f1 = 2 * precision * recall / (precision + recall)
            constrained_score = round(f1 * 20.0, 2)
        else:
            constrained_score = 20.0 if len(agent_constrained) == 0 else 0.0
        eval_criteria["constrained_identification"] = {
            "passed": constrained_score == 20.0,
            "score": constrained_score,
            "max_score": 20.0,
            **({"reason": f"F1={f1:.3f}, found {len(agent_constrained)}, expected {len(gt_constrained)}"} if constrained_score < 20.0 else {}),
        }
        total_score += constrained_score

        # 3. Effective capacity values (15 pts)
        eff_matched = 0
        if gt_constrained:
            for key in gt_constrained:
                if key in agent_dispatch:
                    try:
                        agent_val = float(agent_dispatch[key]["effective_capacity"])
                        if abs(agent_val - gt_eff_cap[key]) <= 0.5:
                            eff_matched += 1
                    except (ValueError, KeyError):
                        pass
            eff_cap_score = round((eff_matched / len(gt_constrained)) * 15.0, 2)
        else:
            eff_cap_score = 15.0
        eval_criteria["effective_capacity_values"] = {
            "passed": eff_cap_score == 15.0,
            "score": eff_cap_score,
            "max_score": 15.0,
            **({"reason": f"Matched {eff_matched}/{len(gt_constrained)}"} if eff_cap_score < 15.0 else {}),
        }
        total_score += eff_cap_score

        # 4. Curtailment volumes (15 pts)
        curt_matched = 0
        if gt_constrained:
            for key in gt_constrained:
                if key in agent_dispatch:
                    try:
                        agent_val = float(agent_dispatch[key]["curtailment_volume"])
                        if abs(agent_val - gt_curtailment[key]) <= 0.5:
                            curt_matched += 1
                    except (ValueError, KeyError):
                        pass
            curt_score = round((curt_matched / len(gt_constrained)) * 15.0, 2)
        else:
            curt_score = 15.0
        eval_criteria["curtailment_volumes"] = {
            "passed": curt_score == 15.0,
            "score": curt_score,
            "max_score": 15.0,
            **({"reason": f"Matched {curt_matched}/{len(gt_constrained)}"} if curt_score < 15.0 else {}),
        }
        total_score += curt_score

        # 5. curtailment_allocations.csv (15 pts)
        alloc_path = os.path.join(self.workspace, "curtailment_allocations.csv")
        alloc_score = 0.0
        alloc_reason = ""
        expected_alloc_cols = [
            "segment_id", "hour", "shipper_id", "priority_tier",
            "original_nomination", "curtailed_amount", "adjusted_nomination",
        ]
        if os.path.isfile(alloc_path):
            try:
                with open(alloc_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_alloc_cols):
                        agent_allocs = list(reader)
                        gt_alloc = {}
                        for row in gt["curtailment_rows"]:
                            seg, h, sid, pri, orig, curtailed, adj = row
                            gt_alloc[(seg, h, sid)] = curtailed

                        alloc_matched = 0
                        total_gt_allocs = len(gt_alloc)
                        for arow in agent_allocs:
                            key = (arow["segment_id"].strip(), int(arow["hour"]), arow["shipper_id"].strip())
                            if key in gt_alloc:
                                try:
                                    agent_curt = float(arow["curtailed_amount"])
                                    if abs(agent_curt - gt_alloc[key]) <= 0.5:
                                        alloc_matched += 1
                                except (ValueError, KeyError):
                                    pass
                        if total_gt_allocs > 0:
                            alloc_score = round((alloc_matched / total_gt_allocs) * 15.0, 2)
                            if alloc_score < 15.0:
                                alloc_reason = f"Matched {alloc_matched}/{total_gt_allocs} allocations"
                        else:
                            alloc_score = 15.0
                    else:
                        missing = [c for c in expected_alloc_cols if c not in cols]
                        alloc_score = 2.0
                        alloc_reason = f"Missing columns: {missing}"
            except Exception as e:
                alloc_reason = f"Error reading file: {e}"
        else:
            alloc_reason = "File not found"
        eval_criteria["curtailment_allocations"] = {
            "passed": alloc_score == 15.0,
            "score": alloc_score,
            "max_score": 15.0,
            **({"reason": alloc_reason} if alloc_score < 15.0 else {}),
        }
        total_score += alloc_score

        # 6. fuel_cost_summary.csv (10 pts)
        fuel_path = os.path.join(self.workspace, "fuel_cost_summary.csv")
        fuel_score = 0.0
        fuel_reason = ""
        expected_fuel_cols = [
            "station_id", "segment_id", "hour", "fuel_consumed_mmbtu",
            "fuel_price_usd", "fuel_cost_usd",
        ]
        if os.path.isfile(fuel_path):
            try:
                with open(fuel_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in expected_fuel_cols):
                        agent_fuel_rows = list(reader)
                        agent_total_fuel = 0.0
                        for row in agent_fuel_rows:
                            try:
                                agent_total_fuel += float(row["fuel_cost_usd"])
                            except (ValueError, KeyError):
                                pass
                        if abs(agent_total_fuel - gt["total_fuel_cost"]) <= 1.0:
                            fuel_score = 10.0
                        else:
                            fuel_score = 3.0
                            fuel_reason = f"Total mismatch: agent={agent_total_fuel:.2f}, expected={gt['total_fuel_cost']:.2f}"
                    else:
                        missing = [c for c in expected_fuel_cols if c not in cols]
                        fuel_score = 2.0
                        fuel_reason = f"Missing columns: {missing}"
            except Exception as e:
                fuel_reason = f"Error reading file: {e}"
        else:
            fuel_reason = "File not found"
        eval_criteria["fuel_cost_summary"] = {
            "passed": fuel_score == 10.0,
            "score": fuel_score,
            "max_score": 10.0,
            **({"reason": fuel_reason} if fuel_score < 10.0 else {}),
        }
        total_score += fuel_score

        # 7. Response summary (15 pts)
        summary_score = 0.0
        summary_reasons = []
        if action and isinstance(action, str):
            m = re.search(r"Total constrained segment-hours:\s*(\d+)", action)
            if m and int(m.group(1)) == gt["total_constrained"]:
                summary_score += 5.0
            else:
                summary_reasons.append(f"constrained count: expected {gt['total_constrained']}")

            m = re.search(r"Total curtailment volume:\s*([\d.]+)", action)
            if m:
                agent_curt = float(m.group(1))
                if abs(agent_curt - gt["total_curtailment"]) <= 1.0:
                    summary_score += 5.0
                else:
                    summary_reasons.append(f"curtailment: expected ~{gt['total_curtailment']:.2f}")
            else:
                summary_reasons.append("curtailment volume not found")

            m = re.search(r"Total fuel cost:\s*\$?([\d.]+)", action)
            if m:
                agent_fuel = float(m.group(1))
                if abs(agent_fuel - gt["total_fuel_cost"]) <= 1.0:
                    summary_score += 5.0
                else:
                    summary_reasons.append(f"fuel cost: expected ~{gt['total_fuel_cost']:.2f}")
            else:
                summary_reasons.append("fuel cost not found")
        else:
            summary_reasons.append("No action string provided")

        eval_criteria["response_summary"] = {
            "passed": summary_score == 15.0,
            "score": round(summary_score, 2),
            "max_score": 15.0,
            **({"reason": "; ".join(summary_reasons)} if summary_score < 15.0 else {}),
        }
        total_score += summary_score

        reward = total_score / max_score
        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": round(total_score, 2),
            "max_score": max_score,
        }

    # ── verify ───────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """Solve the task using only self.tools and workspace files, then call step()."""

        # ── 1. Gather all shippers ──
        all_shippers = []
        page = 1
        while True:
            result = json.loads(self.tools["list_shippers"](page=page)["content"][0]["text"])
            all_shippers.extend(result["shippers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── 2. Gather all nominations per shipper ──
        shipper_noms = {}
        for s in all_shippers:
            noms = json.loads(self.tools["get_shipper_nominations"](shipper_id=s["shipper_id"])["content"][0]["text"])
            if isinstance(noms, list):
                shipper_noms[s["shipper_id"]] = [
                    (n["segment_id"], n["daily_volume_mmbtu"]) for n in noms
                ]

        # ── 3. Gather all segments ──
        all_segments = []
        page = 1
        while True:
            result = json.loads(self.tools["list_pipeline_segments"](page=page))
            all_segments.extend(result["segments"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── 4. Gather sensor data per segment ──
        seg_sensor = {}
        for seg in all_segments:
            data = json.loads(self.tools["get_segment_sensor_data"](segment_id=seg["segment_id"]))
            if isinstance(data, list):
                seg_sensor[seg["segment_id"]] = {r["hour"]: r["pressure_psi"] for r in data}

        # ── 5. Gather all customers ──
        all_customers = []
        page = 1
        while True:
            result = json.loads(self.tools["list_customers"](page=page)["content"][0]["text"])
            all_customers.extend(result["customers"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── 6. Gather demand forecasts ──
        for c in all_customers:
            json.loads(self.tools["get_customer_demand_forecast"](customer_id=c["customer_id"])["content"][0]["text"])

        # ── 7. Gather compressor stations ──
        all_stations = []
        page = 1
        while True:
            result = json.loads(self.tools["list_compressor_stations"](page=page))
            all_stations.extend(result["stations"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ── 8. Gather compressor logs ──
        station_logs = {}
        station_seg_map = {}
        for st in all_stations:
            station_seg_map[st["station_id"]] = st["segment_id"]
            data = json.loads(self.tools["get_compressor_log"](station_id=st["station_id"]))
            if isinstance(data, list):
                station_logs[st["station_id"]] = {
                    r["hour"]: r["fuel_consumed_mmbtu"] for r in data
                }

        # ── 9. Load workspace files ──
        seg_specs = self._load_segment_specs()
        shipper_contracts = self._load_shipper_contracts()
        customer_profiles = self._load_customer_profiles()
        fuel_prices = self._load_fuel_prices()

        # Build seg -> [(shipper_id, daily_vol)] from tool data
        seg_noms = {}
        for sid, noms in shipper_noms.items():
            for seg_id, daily_vol in noms:
                seg_noms.setdefault(seg_id, []).append((sid, daily_vol))

        # Build segment -> sum of min_delivery_obligation
        cust_seg = {c["customer_id"]: c["connected_segment_id"] for c in all_customers}
        seg_min_delivery = {}
        for cid, prof in customer_profiles.items():
            seg = cust_seg.get(cid)
            if seg:
                seg_min_delivery[seg] = seg_min_delivery.get(seg, 0.0) + prof["min_delivery_obligation_mmbtu_hr"]

        all_seg_ids = sorted(seg_specs.keys())

        # ── 10. Compute constrained hours and curtailments ──
        dispatch_rows = []
        curtailment_rows = []

        for seg in all_seg_ids:
            spec = seg_specs[seg]
            max_cap = spec["max_capacity_mmbtu_hr"]
            min_p = spec["min_pressure_psi"]
            max_p = spec["max_pressure_psi"]
            shippers_on_seg = seg_noms.get(seg, [])
            min_del = seg_min_delivery.get(seg, 0.0)
            sensor_data = seg_sensor.get(seg, {})

            for h in range(24):
                shipper_hourly = []
                total_nom = 0.0
                for sid, daily_vol in shippers_on_seg:
                    contract = shipper_contracts.get(sid)
                    if contract is None:
                        continue
                    hourly_profile = contract["hourly_profile"]
                    hourly_nom = daily_vol * hourly_profile[h]
                    priority = contract["priority_tier"]
                    shipper_hourly.append((sid, hourly_nom, priority))
                    total_nom += hourly_nom

                pressure = sensor_data.get(h)
                if pressure is not None and pressure > max_p:
                    eff_cap = max_cap * 0.85
                elif pressure is not None and pressure < min_p:
                    eff_cap = max_cap * 0.90
                else:
                    eff_cap = max_cap

                is_constrained = total_nom > eff_cap
                if is_constrained:
                    curtailment_needed = total_nom - eff_cap
                    max_curtailable = max(0.0, total_nom - min_del)
                    actual_curtailment = min(curtailment_needed, max_curtailable)
                    adjusted_flow = total_nom - actual_curtailment

                    shipper_hourly.sort(key=lambda x: (-x[2], x[0]))
                    remaining = actual_curtailment
                    for sid, hourly_nom, priority in shipper_hourly:
                        curtailed = min(remaining, hourly_nom)
                        curtailment_rows.append({
                            "segment_id": seg,
                            "hour": h,
                            "shipper_id": sid,
                            "priority_tier": priority,
                            "original_nomination": round(hourly_nom, 4),
                            "curtailed_amount": round(curtailed, 4),
                            "adjusted_nomination": round(hourly_nom - curtailed, 4),
                        })
                        remaining -= curtailed

                    dispatch_rows.append({
                        "segment_id": seg,
                        "hour": h,
                        "total_nominated": round(total_nom, 4),
                        "effective_capacity": round(eff_cap, 4),
                        "adjusted_flow": round(adjusted_flow, 4),
                        "is_constrained": True,
                        "curtailment_volume": round(actual_curtailment, 4),
                    })

        # ── 11. Fuel cost computation ──
        fuel_cost_rows = []
        total_fuel_cost = 0.0
        for station_id in sorted(station_logs.keys()):
            seg = station_seg_map[station_id]
            for h in range(24):
                fuel = station_logs[station_id].get(h, 0.0)
                price = fuel_prices.get(h, 0.0)
                cost = fuel * price
                total_fuel_cost += cost
                fuel_cost_rows.append({
                    "station_id": station_id,
                    "segment_id": seg,
                    "hour": h,
                    "fuel_consumed_mmbtu": round(fuel, 4),
                    "fuel_price_usd": round(price, 4),
                    "fuel_cost_usd": round(cost, 4),
                })

        # ── 12. Write output files ──
        dispatch_path = os.path.join(self.workspace, "dispatch_instructions.csv")
        with open(dispatch_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "segment_id", "hour", "total_nominated", "effective_capacity",
                "adjusted_flow", "is_constrained", "curtailment_volume",
            ])
            writer.writeheader()
            for row in dispatch_rows:
                writer.writerow(row)

        alloc_path = os.path.join(self.workspace, "curtailment_allocations.csv")
        with open(alloc_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "segment_id", "hour", "shipper_id", "priority_tier",
                "original_nomination", "curtailed_amount", "adjusted_nomination",
            ])
            writer.writeheader()
            for row in curtailment_rows:
                writer.writerow(row)

        fuel_path = os.path.join(self.workspace, "fuel_cost_summary.csv")
        with open(fuel_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "station_id", "segment_id", "hour", "fuel_consumed_mmbtu",
                "fuel_price_usd", "fuel_cost_usd",
            ])
            writer.writeheader()
            for row in fuel_cost_rows:
                writer.writerow(row)

        total_curtailment = sum(r["curtailment_volume"] for r in dispatch_rows)
        total_constrained = len(dispatch_rows)

        action = (
            f"Total constrained segment-hours: {total_constrained}\n"
            f"Total curtailment volume: {total_curtailment:.2f} MMBtu\n"
            f"Total fuel cost: ${total_fuel_cost:.2f}"
        )

        return self.step(action)
