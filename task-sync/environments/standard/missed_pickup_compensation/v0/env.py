"""
Environment for the missed-pickup compensation task.
Provides tools for querying service requests, resident info, GPS stops,
bin lifts, and prior claims. Evaluates the agent's refund list output.
"""

import csv
import io
import json
import math
import os
import sqlite3
import yaml
from typing import Tuple, Dict, List, Any


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) *
         (1 - math.cos((lon2 - lon1) * p)) / 2)
    return 2 * R * math.asin(math.sqrt(a))


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

    # ===================================================================
    # TOOL METHODS
    # ===================================================================

    @tool(
        description=(
            "Search service requests by type and/or status. Returns a paginated "
            "list with basic fields: request_id, resident_id, request_type, "
            "scheduled_pickup_date, status. Page numbering starts at 1."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_type": {
                    "type": "string",
                    "description": "Filter by request type, e.g. 'missed_pickup'.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status, e.g. 'pending_review'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (starting from 1). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def search_service_requests(
        self,
        request_type: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if request_type:
            clauses.append("request_type = ?")
            params.append(request_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM service_requests{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT request_id, resident_id, request_type, "
            f"scheduled_pickup_date, status "
            f"FROM service_requests{where} "
            f"ORDER BY request_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "results": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Get full details for a single service request by its request_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The service request ID, e.g. 'SR00001'.",
                },
            },
            "required": ["request_id"],
        },
    )
    def get_request_details(self, request_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM service_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Request {request_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Get resident information by resident_id. Returns name, address, "
            "latitude, longitude, zone_id, service_tier, and bin_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resident_id": {
                    "type": "string",
                    "description": "The resident ID, e.g. 'R00001'.",
                },
            },
            "required": ["resident_id"],
        },
    )
    def get_resident_info(self, resident_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM residents WHERE resident_id = ?",
            (resident_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Resident {resident_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Query GPS truck stops for a given truck on a specific date. "
            "Returns a list of stops with stop_id, latitude, longitude, "
            "stop_time, and stop_duration_sec."
        ),
        parameters={
            "type": "object",
            "properties": {
                "truck_id": {
                    "type": "string",
                    "description": "The truck ID, e.g. 'T001'.",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["truck_id", "date"],
        },
    )
    def query_gps_stops(self, truck_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT stop_id, latitude, longitude, stop_time, stop_duration_sec "
            "FROM gps_stops "
            "WHERE truck_id = ? AND stop_time LIKE ?",
            (truck_id, date + "%"),
        ).fetchall()
        conn.close()
        return {"truck_id": truck_id, "date": date, "stops": [dict(r) for r in rows]}

    @tool(
        description=(
            "Query bin lift sensor records for a specific bin on a given date. "
            "Returns lift_id, truck_id, lift_time, lift_successful, weight_kg."
        ),
        parameters={
            "type": "object",
            "properties": {
                "bin_id": {
                    "type": "string",
                    "description": "The bin ID, e.g. 'BIN00001'.",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["bin_id", "date"],
        },
    )
    def query_bin_lifts(self, bin_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT lift_id, truck_id, lift_time, lift_successful, weight_kg "
            "FROM bin_lifts "
            "WHERE bin_id = ? AND lift_time LIKE ?",
            (bin_id, date + "%"),
        ).fetchall()
        conn.close()
        return {"bin_id": bin_id, "date": date, "lifts": [dict(r) for r in rows]}

    @tool(
        description=(
            "Check how many resolved missed-pickup claims exist for a resident "
            "within a date window. Useful for determining repeat-miss status. "
            "Returns the count and the matching request IDs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "resident_id": {
                    "type": "string",
                    "description": "The resident ID.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start of window (inclusive) YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of window (exclusive) YYYY-MM-DD.",
                },
            },
            "required": ["resident_id", "start_date", "end_date"],
        },
    )
    def check_prior_claims(self, resident_id: str, start_date: str, end_date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT request_id, scheduled_pickup_date FROM service_requests "
            "WHERE resident_id = ? AND request_type = 'missed_pickup' "
            "AND status = 'resolved' "
            "AND scheduled_pickup_date >= ? AND scheduled_pickup_date < ?",
            (resident_id, start_date, end_date),
        ).fetchall()
        conn.close()
        return {
            "resident_id": resident_id,
            "window": f"{start_date} to {end_date}",
            "count": len(rows),
            "claims": [dict(r) for r in rows],
        }

    # ===================================================================
    # STEP  –  evaluation
    # ===================================================================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.
        """
        info: Dict[str, Any] = {"eval_criteria": {}}
        total_score = 0
        max_score = 0

        # ---- compute ground truth -----------------------------------
        gt_refunds = self._compute_ground_truth()

        # Criterion 1: refund_list.csv exists (10 pts)
        max_score += 10
        csv_path = os.path.join(self.workspace, "refund_list.csv")
        csv_exists = os.path.isfile(csv_path)
        info["eval_criteria"]["csv_exists"] = {
            "passed": csv_exists,
            "score": 10 if csv_exists else 0,
            "max_score": 10,
        }
        total_score += 10 if csv_exists else 0

        # Criterion 2: correct columns in CSV (10 pts)
        expected_cols = [
            "request_id", "resident_id", "resident_name", "zone_id",
            "service_tier", "scheduled_pickup_date", "miss_type",
            "base_credit", "final_credit",
        ]
        parsed_rows = []
        cols_ok = False
        if csv_exists:
            try:
                with open(csv_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    cols_ok = actual_cols == expected_cols
                    for row in reader:
                        parsed_rows.append({k.strip(): v.strip() for k, v in row.items()})
            except Exception:
                pass
        max_score += 10
        info["eval_criteria"]["csv_columns"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
        }
        total_score += 10 if cols_ok else 0

        # Criterion 3: correct set of request_ids (25 pts)
        gt_ids = set(r["request_id"] for r in gt_refunds)
        agent_ids = set(r.get("request_id", "") for r in parsed_rows)
        ids_match = gt_ids == agent_ids
        # Partial: Jaccard similarity
        if gt_ids or agent_ids:
            jaccard = len(gt_ids & agent_ids) / len(gt_ids | agent_ids)
        else:
            jaccard = 1.0 if not gt_ids else 0.0
        id_score = round(25 * jaccard)
        max_score += 25
        info["eval_criteria"]["correct_request_ids"] = {
            "passed": ids_match,
            "score": id_score,
            "max_score": 25,
            "reason": "" if ids_match else f"expected {len(gt_ids)} refunds, got {len(agent_ids)}; overlap={len(gt_ids & agent_ids)}",
        }
        total_score += id_score

        # Criterion 4: correct miss_type for each matching request (15 pts)
        gt_map = {r["request_id"]: r for r in gt_refunds}
        agent_map = {r.get("request_id", ""): r for r in parsed_rows}
        common_ids = gt_ids & agent_ids
        type_correct = 0
        for rid in common_ids:
            if agent_map[rid].get("miss_type", "") == gt_map[rid]["miss_type"]:
                type_correct += 1
        type_ratio = type_correct / len(common_ids) if common_ids else (1.0 if not gt_ids else 0.0)
        type_score = round(15 * type_ratio)
        max_score += 15
        info["eval_criteria"]["correct_miss_types"] = {
            "passed": type_ratio == 1.0,
            "score": type_score,
            "max_score": 15,
            "reason": "" if type_ratio == 1.0 else f"{type_correct}/{len(common_ids)} correct",
        }
        total_score += type_score

        # Criterion 5: correct final_credit values (20 pts)
        credit_correct = 0
        for rid in common_ids:
            try:
                agent_credit = float(agent_map[rid].get("final_credit", -1))
            except (ValueError, TypeError):
                agent_credit = -1
            gt_credit = float(gt_map[rid]["final_credit"])
            if abs(agent_credit - gt_credit) < 0.01:
                credit_correct += 1
        credit_ratio = credit_correct / len(common_ids) if common_ids else (1.0 if not gt_ids else 0.0)
        credit_score = round(20 * credit_ratio)
        max_score += 20
        info["eval_criteria"]["correct_credits"] = {
            "passed": credit_ratio == 1.0,
            "score": credit_score,
            "max_score": 20,
            "reason": "" if credit_ratio == 1.0 else f"{credit_correct}/{len(common_ids)} correct",
        }
        total_score += credit_score

        # Criterion 6: sort order (10 pts)
        sorted_ok = False
        if parsed_rows:
            agent_id_list = [r.get("request_id", "") for r in parsed_rows]
            sorted_ok = agent_id_list == sorted(agent_id_list)
        max_score += 10
        info["eval_criteria"]["sort_order"] = {
            "passed": sorted_ok,
            "score": 10 if sorted_ok else 0,
            "max_score": 10,
        }
        total_score += 10 if sorted_ok else 0

        # Criterion 7: action string contains total count and total credit (10 pts)
        gt_total_credit = sum(float(r["final_credit"]) for r in gt_refunds)
        gt_count = len(gt_refunds)
        count_in_action = str(gt_count) in action
        credit_str = f"{gt_total_credit:.2f}"
        credit_in_action = credit_str in action
        summary_ok = count_in_action and credit_in_action
        summary_score = 0
        if count_in_action:
            summary_score += 5
        if credit_in_action:
            summary_score += 5
        max_score += 10
        info["eval_criteria"]["action_summary"] = {
            "passed": summary_ok,
            "score": summary_score,
            "max_score": 10,
            "reason": "" if summary_ok else f"expected count={gt_count}, credit={credit_str}",
        }
        total_score += summary_score

        info["total_score"] = total_score
        info["max_score"] = max_score
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    # ===================================================================
    # Ground-truth computation (used by step and verify)
    # ===================================================================

    def _compute_ground_truth(self) -> List[Dict[str, Any]]:
        """Derive the correct refund list from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load workspace config files
        with open(os.path.join(self.workspace, "sla_terms.yaml"), "r") as f:
            sla = yaml.safe_load(f)

        comp_rates = {}
        with open(os.path.join(self.workspace, "compensation_rates.csv"), "r") as f:
            for row in csv.DictReader(f):
                comp_rates[row["service_tier"]] = {
                    "base_credit": float(row["base_credit"]),
                    "partial_miss_rate": float(row["partial_miss_rate"]),
                    "full_miss_rate": float(row["full_miss_rate"]),
                    "repeat_miss_multiplier": float(row["repeat_miss_multiplier"]),
                }

        with open(os.path.join(self.workspace, "zone_boundaries.json"), "r") as f:
            zones = json.load(f)

        # Load all route logs to find excused zone-dates
        excused = set()  # (zone_id, date_str)
        for fname in os.listdir(self.workspace):
            if fname.startswith("route_log_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), "r") as f:
                    for row in csv.DictReader(f):
                        exc_code = row.get("exception_code", "none")
                        adv = row.get("advance_notice", "false").lower() == "true"
                        if exc_code in sla["general"]["excused_exception_codes"] and adv:
                            excused.add((row["zone_id"], row["date"]))

        # Get all pending missed_pickup requests
        pending = conn.execute(
            "SELECT * FROM service_requests "
            "WHERE request_type = 'missed_pickup' AND status = 'pending_review' "
            "ORDER BY request_id"
        ).fetchall()

        refunds = []
        for req in pending:
            req = dict(req)
            rid = req["resident_id"]
            sched_date = req["scheduled_pickup_date"]

            # Get resident info
            res = dict(conn.execute(
                "SELECT * FROM residents WHERE resident_id = ?", (rid,)
            ).fetchone())

            zone_id = res["zone_id"]
            tier = res["service_tier"]

            # Check if scheduled day matches zone pickup days
            from datetime import datetime as _dt
            sched_dt = _dt.strptime(sched_date, "%Y-%m-%d")
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                         "Friday", "Saturday", "Sunday"]
            sched_day = day_names[sched_dt.weekday()]
            if sched_day not in zones[zone_id]["pickup_days"]:
                continue  # not a valid pickup day for this zone

            # Check excused
            if (zone_id, sched_date) in excused:
                continue

            # Get truck for this zone
            truck_id = zones[zone_id]["assigned_truck"]

            # Get SLA thresholds
            tier_sla = sla["service_tiers"][tier]
            prox_thresh = tier_sla["proximity_threshold_m"]
            min_dur = tier_sla["min_stop_duration_sec"]

            # Check GPS stops
            gps_rows = conn.execute(
                "SELECT latitude, longitude, stop_duration_sec "
                "FROM gps_stops WHERE truck_id = ? AND stop_time LIKE ?",
                (truck_id, sched_date + "%"),
            ).fetchall()

            has_valid_stop = False
            for g in gps_rows:
                dist = _haversine_m(res["latitude"], res["longitude"],
                                    g["latitude"], g["longitude"])
                if dist <= prox_thresh and g["stop_duration_sec"] >= min_dur:
                    has_valid_stop = True
                    break

            # Check bin lifts
            lifts = conn.execute(
                "SELECT lift_successful FROM bin_lifts "
                "WHERE bin_id = ? AND lift_time LIKE ?",
                (res["bin_id"], sched_date + "%"),
            ).fetchall()
            has_successful_lift = any(l["lift_successful"] for l in lifts)

            # Determine miss type
            if has_valid_stop and has_successful_lift:
                continue  # not a valid miss
            elif has_valid_stop and not has_successful_lift:
                miss_type = "partial_miss"
            else:
                # No valid GPS stop (or no stop at all)
                if has_successful_lift:
                    # Unusual: bin was lifted but no GPS stop recorded near address
                    # Treat as not a valid miss since service was provided
                    continue
                miss_type = "full_miss"

            # Credit calculation
            rates = comp_rates[tier]
            base_credit = rates["base_credit"]
            if miss_type == "full_miss":
                credit = base_credit * rates["full_miss_rate"]
            else:
                credit = base_credit * rates["partial_miss_rate"]

            # Check repeat miss
            from datetime import timedelta as _td
            window_start = (sched_dt - _td(days=30)).strftime("%Y-%m-%d")
            prior = conn.execute(
                "SELECT COUNT(*) FROM service_requests "
                "WHERE resident_id = ? AND request_type = 'missed_pickup' "
                "AND status = 'resolved' "
                "AND scheduled_pickup_date >= ? AND scheduled_pickup_date < ?",
                (rid, window_start, sched_date),
            ).fetchone()[0]
            if prior > 0:
                credit *= rates["repeat_miss_multiplier"]

            final_credit = round(credit, 2)

            refunds.append({
                "request_id": req["request_id"],
                "resident_id": rid,
                "resident_name": res["name"],
                "zone_id": zone_id,
                "service_tier": tier,
                "scheduled_pickup_date": sched_date,
                "miss_type": miss_type,
                "base_credit": f"{base_credit:.2f}",
                "final_credit": f"{final_credit:.2f}",
            })

        conn.close()
        refunds.sort(key=lambda r: r["request_id"])
        return refunds

    # ===================================================================
    # VERIFY
    # ===================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import os as _os
        from datetime import datetime as _dt, timedelta as _td

        # 1. Read workspace config files
        with open(_os.path.join(self.workspace, "sla_terms.yaml"), "r") as f:
            sla = yaml.safe_load(f)

        comp_rates = {}
        with open(_os.path.join(self.workspace, "compensation_rates.csv"), "r") as f:
            for row in csv.DictReader(f):
                comp_rates[row["service_tier"]] = {
                    "base_credit": float(row["base_credit"]),
                    "partial_miss_rate": float(row["partial_miss_rate"]),
                    "full_miss_rate": float(row["full_miss_rate"]),
                    "repeat_miss_multiplier": float(row["repeat_miss_multiplier"]),
                }

        with open(_os.path.join(self.workspace, "zone_boundaries.json"), "r") as f:
            zones = json.load(f)

        # Read all route logs for excused dates
        excused = set()
        for fname in _os.listdir(self.workspace):
            if fname.startswith("route_log_") and fname.endswith(".csv"):
                with open(_os.path.join(self.workspace, fname), "r") as f:
                    for row in csv.DictReader(f):
                        exc_code = row.get("exception_code", "none")
                        adv = row.get("advance_notice", "false").lower() == "true"
                        if exc_code in sla["general"]["excused_exception_codes"] and adv:
                            excused.add((row["zone_id"], row["date"]))

        # Read compensation policy (the agent would need to read this)
        with open(_os.path.join(self.workspace, "compensation_policy.md"), "r") as f:
            _ = f.read()

        # 2. Search for pending missed_pickup requests (paginated)
        all_pending = []
        page = 1
        while True:
            result = self.tools["search_service_requests"](
                request_type="missed_pickup", status="pending_review",
                page=page, page_size=20,
            )
            all_pending.extend(result["results"])
            if page * result["page_size"] >= result["total"]:
                break
            page += 1

        tool_call_count = page  # calls so far

        # 3. For each pending request, gather data and determine compensation
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"]

        refunds = []
        for req_summary in all_pending:
            req_id = req_summary["request_id"]
            resident_id = req_summary["resident_id"]
            sched_date = req_summary["scheduled_pickup_date"]

            # Get resident info
            res = self.tools["get_resident_info"](resident_id=resident_id)
            tool_call_count += 1

            zone_id = res["zone_id"]
            tier = res["service_tier"]

            # Check pickup day
            sched_dt = _dt.strptime(sched_date, "%Y-%m-%d")
            sched_day = day_names[sched_dt.weekday()]
            if sched_day not in zones[zone_id]["pickup_days"]:
                continue

            # Check excused
            if (zone_id, sched_date) in excused:
                continue

            # Get truck for this zone
            truck_id = zones[zone_id]["assigned_truck"]

            # SLA thresholds
            tier_sla = sla["service_tiers"][tier]
            prox_thresh = tier_sla["proximity_threshold_m"]
            min_dur = tier_sla["min_stop_duration_sec"]

            # Query GPS stops
            gps_result = self.tools["query_gps_stops"](
                truck_id=truck_id, date=sched_date,
            )
            tool_call_count += 1

            has_valid_stop = False
            for stop in gps_result["stops"]:
                dist = _haversine_m(
                    res["latitude"], res["longitude"],
                    stop["latitude"], stop["longitude"],
                )
                if dist <= prox_thresh and stop["stop_duration_sec"] >= min_dur:
                    has_valid_stop = True
                    break

            # Query bin lifts
            lift_result = self.tools["query_bin_lifts"](
                bin_id=res["bin_id"], date=sched_date,
            )
            tool_call_count += 1
            has_successful_lift = any(
                l["lift_successful"] for l in lift_result["lifts"]
            )

            # Determine miss type
            if has_valid_stop and has_successful_lift:
                continue  # not a miss
            elif has_valid_stop and not has_successful_lift:
                miss_type = "partial_miss"
            else:
                if has_successful_lift:
                    continue  # service was provided
                miss_type = "full_miss"

            # Credit calculation
            rates = comp_rates[tier]
            base_credit = rates["base_credit"]
            if miss_type == "full_miss":
                credit = base_credit * rates["full_miss_rate"]
            else:
                credit = base_credit * rates["partial_miss_rate"]

            # Check repeat miss
            window_start = (sched_dt - _td(days=30)).strftime("%Y-%m-%d")
            prior = self.tools["check_prior_claims"](
                resident_id=resident_id,
                start_date=window_start,
                end_date=sched_date,
            )
            tool_call_count += 1
            if prior["count"] > 0:
                credit *= rates["repeat_miss_multiplier"]

            final_credit = round(credit, 2)

            refunds.append({
                "request_id": req_id,
                "resident_id": resident_id,
                "resident_name": res["name"],
                "zone_id": zone_id,
                "service_tier": tier,
                "scheduled_pickup_date": sched_date,
                "miss_type": miss_type,
                "base_credit": f"{base_credit:.2f}",
                "final_credit": f"{final_credit:.2f}",
            })

        refunds.sort(key=lambda r: r["request_id"])

        # 4. Write refund_list.csv
        csv_path = _os.path.join(self.workspace, "refund_list.csv")
        fieldnames = [
            "request_id", "resident_id", "resident_name", "zone_id",
            "service_tier", "scheduled_pickup_date", "miss_type",
            "base_credit", "final_credit",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(refunds)

        # 5. Build action string
        total_credit = sum(float(r["final_credit"]) for r in refunds)
        action = (
            f"Validated {len(refunds)} missed pickup refund entries. "
            f"Total credit amount: {total_credit:.2f}. "
            f"Results saved to refund_list.csv."
        )

        assert tool_call_count >= 15, (
            f"Tool call count {tool_call_count} < 15 minimum"
        )

        return self.step(action)
