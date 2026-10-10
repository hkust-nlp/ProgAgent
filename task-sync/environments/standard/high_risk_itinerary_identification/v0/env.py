from typing import Tuple, Dict, List, Any
import sqlite3
import json
import csv
import os
import math

try:
    import yaml
except ImportError:
    import json as yaml


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

    # ------------------------------------------------------------------ tools

    @tool(
        description="List all confirmed bookings with pagination. Returns PNR, traveler_id, booking_date, and status for each booking.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20, default 10).",
                },
            },
            "required": ["page"],
        },
    )
    def list_bookings(self, page: int, page_size: int = 10) -> dict:
        page_size = min(int(page_size), 20)
        page = int(page)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bookings WHERE status='confirmed'")
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT pnr, traveler_id, booking_date, status FROM bookings "
            "WHERE status='confirmed' ORDER BY booking_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "bookings": rows,
            "page": page,
            "page_size": page_size,
            "total_bookings": total,
            "total_pages": total_pages,
        }

    @tool(
        description="Get flight segments for a given booking PNR. Returns leg order, flight number, carrier, origin, destination, and scheduled times.",
        parameters={
            "type": "object",
            "properties": {
                "pnr": {
                    "type": "string",
                    "description": "The 6-character Passenger Name Record code.",
                },
            },
            "required": ["pnr"],
        },
    )
    def get_segments(self, pnr: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT leg_order, flight_number, carrier_code, origin, destination, "
            "scheduled_departure, scheduled_arrival FROM segments "
            "WHERE pnr=? ORDER BY leg_order",
            (pnr,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"pnr": pnr, "segments": rows}

    @tool(
        description="Get the real-time status of a specific flight on a given date, including delay minutes and reason.",
        parameters={
            "type": "object",
            "properties": {
                "flight_number": {
                    "type": "string",
                    "description": "Flight number, e.g. 'AA1234'.",
                },
                "flight_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["flight_number", "flight_date"],
        },
    )
    def get_flight_status(self, flight_number: str, flight_date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT flight_number, flight_date, status, delay_minutes, reason "
            "FROM flight_status WHERE flight_number=? AND flight_date=?",
            (flight_number, flight_date),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {
            "flight_number": flight_number,
            "flight_date": flight_date,
            "status": "unknown",
            "delay_minutes": 0,
            "reason": "",
        }

    @tool(
        description="Get traveler details by traveler ID, including name, contact info, and loyalty tier.",
        parameters={
            "type": "object",
            "properties": {
                "traveler_id": {
                    "type": "string",
                    "description": "Traveler identifier, e.g. 'T0001'.",
                },
            },
            "required": ["traveler_id"],
        },
    )
    def get_traveler(self, traveler_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT traveler_id, name, email, phone, loyalty_tier "
            "FROM travelers WHERE traveler_id=?",
            (traveler_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Traveler {traveler_id} not found"}

    @tool(
        description="Search for alternative flights on a given route and date. Results are sorted by departure time. Returns at most 10 results.",
        parameters={
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport code.",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport code.",
                },
                "flight_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
                "min_departure_time": {
                    "type": "string",
                    "description": "Only return flights departing at or after this time (HH:MM). Optional.",
                },
            },
            "required": ["origin", "destination", "flight_date"],
        },
    )
    def search_alternatives(self, origin: str, destination: str,
                            flight_date: str, min_departure_time: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if min_departure_time:
            cur.execute(
                "SELECT flight_number, carrier_code, origin, destination, "
                "departure_time, arrival_time, available_seats "
                "FROM alternative_flights "
                "WHERE origin=? AND destination=? AND flight_date=? AND departure_time>=? "
                "ORDER BY departure_time LIMIT 10",
                (origin, destination, flight_date, min_departure_time),
            )
        else:
            cur.execute(
                "SELECT flight_number, carrier_code, origin, destination, "
                "departure_time, arrival_time, available_seats "
                "FROM alternative_flights "
                "WHERE origin=? AND destination=? AND flight_date=? "
                "ORDER BY departure_time LIMIT 10",
                (origin, destination, flight_date),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"alternatives": rows, "count": len(rows)}

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _time_to_minutes(t: str) -> int:
        parts = t.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def _load_workspace_config(self):
        """Load all workspace configuration and supplement files."""
        ws = self.workspace

        with open(os.path.join(ws, "connection_rules.yaml")) as f:
            conn_rules = yaml.safe_load(f)
        min_conn_times = conn_rules["minimum_connection_times"]
        # Ensure keys are strings
        min_conn_times = {str(k): int(v) for k, v in min_conn_times.items()}

        with open(os.path.join(ws, "risk_config.json")) as f:
            risk_config = json.load(f)

        # Read passenger supplements from all passenger_data_* files
        supplements = {}
        for fname in sorted(os.listdir(ws)):
            if not fname.startswith("passenger_data_"):
                continue
            fpath = os.path.join(ws, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    data = json.load(f)
                for item in data:
                    supplements[item["pnr"]] = {
                        "special_assistance": bool(item.get("special_assistance", False)),
                        "unaccompanied_minor": bool(item.get("unaccompanied_minor", False)),
                    }
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        supplements[row["pnr"]] = {
                            "special_assistance": row["special_assistance"] == "True",
                            "unaccompanied_minor": row["unaccompanied_minor"] == "True",
                        }
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    content = f.read()
                for block in content.strip().split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    d = {}
                    for line in block.split("\n"):
                        if ": " in line:
                            key, val = line.split(": ", 1)
                            d[key.strip()] = val.strip()
                    if "PNR" in d:
                        supplements[d["PNR"]] = {
                            "special_assistance": d.get("Special Assistance", "No") == "Yes",
                            "unaccompanied_minor": d.get("Unaccompanied Minor", "No") == "Yes",
                        }
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    data = yaml.safe_load(f)
                if data:
                    for item in data:
                        supplements[item["pnr"]] = {
                            "special_assistance": bool(item.get("special_assistance", False)),
                            "unaccompanied_minor": bool(item.get("unaccompanied_minor", False)),
                        }

        return min_conn_times, risk_config, supplements

    def _compute_booking_risk(self, segments_list, flight_statuses_map,
                              min_conn_times, risk_config, supplement):
        """Compute risk score and details for a single booking.

        Args:
            segments_list: list of segment dicts (sorted by leg_order)
            flight_statuses_map: dict mapping flight_number -> status dict
            min_conn_times: airport -> min connection minutes
            risk_config: full risk config dict
            supplement: dict with special_assistance, unaccompanied_minor bools

        Returns:
            dict with risk_score, risk_factors, at_risk_segment or None if not high-risk
        """
        weights = risk_config["weights"]
        thresholds = risk_config["thresholds"]
        carrier_otp = risk_config["carrier_otp"]

        # --- Connection tightness (max across connections) ---
        best_conn_score = 0.0
        best_conn_seg_idx = -1  # index of departing segment at tightest connection

        for i in range(len(segments_list) - 1):
            seg_in = segments_list[i]
            seg_out = segments_list[i + 1]
            fs_in = flight_statuses_map.get(seg_in["flight_number"],
                                            {"status": "on_time", "delay_minutes": 0})
            fs_out = flight_statuses_map.get(seg_out["flight_number"],
                                             {"status": "on_time", "delay_minutes": 0})

            if fs_in["status"] == "cancelled" or fs_out["status"] == "cancelled":
                cs = float(weights["connection_tightness"])
            else:
                sched_layover = (self._time_to_minutes(seg_out["scheduled_departure"])
                                 - self._time_to_minutes(seg_in["scheduled_arrival"]))
                if sched_layover < 0:
                    sched_layover += 1440
                delay_in = fs_in.get("delay_minutes", 0) or 0
                delay_out = fs_out.get("delay_minutes", 0) or 0
                effective_layover = sched_layover - delay_in + delay_out

                conn_airport = seg_in["destination"]
                min_conn = min_conn_times.get(conn_airport, 60)
                buffer = thresholds["tight_connection_buffer_minutes"]

                if effective_layover <= 0:
                    cs = float(weights["connection_tightness"])
                elif effective_layover < min_conn:
                    cs = float(weights["connection_tightness"])
                elif effective_layover < min_conn + buffer:
                    cs = weights["connection_tightness"] * (1.0 - (effective_layover - min_conn) / buffer)
                else:
                    cs = 0.0

            if cs > best_conn_score:
                best_conn_score = cs
                best_conn_seg_idx = i + 1  # departing segment index

        # --- Carrier reliability (max across segments) ---
        best_carrier_score = 0.0
        best_carrier_seg_idx = -1
        for i, seg in enumerate(segments_list):
            otp = carrier_otp.get(seg["carrier_code"], 0.85)
            if otp < thresholds["poor_otp_threshold"]:
                cs = weights["carrier_reliability"] * (1.0 - otp)
                if cs > best_carrier_score:
                    best_carrier_score = cs
                    best_carrier_seg_idx = i

        # --- Current delay (max across segments) ---
        best_delay_score = 0.0
        best_delay_seg_idx = -1
        has_delayed = False
        has_cancelled = False
        for i, seg in enumerate(segments_list):
            fs = flight_statuses_map.get(seg["flight_number"],
                                         {"status": "on_time", "delay_minutes": 0})
            if fs["status"] == "cancelled":
                has_cancelled = True
                ds = float(weights["current_delay"])
            elif fs["status"] == "delayed":
                has_delayed = True
                dm = fs.get("delay_minutes", 0) or 0
                ds = weights["current_delay"] * min(1.0, dm / thresholds["severe_delay_minutes"])
            else:
                ds = 0.0
            if ds > best_delay_score:
                best_delay_score = ds
                best_delay_seg_idx = i

        raw_score = best_conn_score + best_carrier_score + best_delay_score

        # Vulnerability multiplier
        sa = supplement.get("special_assistance", False)
        um = supplement.get("unaccompanied_minor", False)
        if um:
            mult = risk_config["vulnerability_factors"]["unaccompanied_minor"]
        elif sa:
            mult = risk_config["vulnerability_factors"]["special_assistance"]
        else:
            mult = risk_config["vulnerability_factors"]["default"]

        final_risk = round(raw_score * mult, 1)

        if final_risk < thresholds["high_risk_score"]:
            return None

        # Risk factors
        factors = []
        if best_conn_score > 0:
            factors.append("tight_connection")
        if best_carrier_score > 0:
            factors.append("carrier_unreliable")
        if has_delayed:
            factors.append("flight_delayed")
        if has_cancelled:
            factors.append("flight_cancelled")

        # At-risk segment (priority: cancelled > connection > delay > carrier)
        cancelled_indices = [
            i for i, seg in enumerate(segments_list)
            if flight_statuses_map.get(seg["flight_number"], {}).get("status") == "cancelled"
        ]
        if cancelled_indices:
            at_risk_idx = cancelled_indices[0]
        elif best_conn_score > 0 and best_conn_seg_idx >= 0:
            at_risk_idx = best_conn_seg_idx
        elif best_delay_score > 0 and best_delay_seg_idx >= 0:
            at_risk_idx = best_delay_seg_idx
        elif best_carrier_score > 0 and best_carrier_seg_idx >= 0:
            at_risk_idx = best_carrier_seg_idx
        else:
            at_risk_idx = 0

        at_risk_seg = segments_list[at_risk_idx]

        return {
            "risk_score": final_risk,
            "risk_factors": ";".join(factors),
            "at_risk_segment": at_risk_seg["flight_number"],
            "at_risk_origin": at_risk_seg["origin"],
            "at_risk_destination": at_risk_seg["destination"],
            "at_risk_departure": at_risk_seg["scheduled_departure"],
        }

    def _compute_ground_truth(self):
        """Compute the full ground-truth rebooking list from DB + workspace."""
        min_conn_times, risk_config, supplements = self._load_workspace_config()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # All bookings
        cur = conn.cursor()
        cur.execute("SELECT pnr, traveler_id FROM bookings WHERE status='confirmed' ORDER BY booking_id")
        all_bookings = [dict(r) for r in cur.fetchall()]

        # All flight statuses
        cur.execute("SELECT flight_number, flight_date, status, delay_minutes, reason FROM flight_status")
        fs_map = {}
        for r in cur.fetchall():
            fs_map[r["flight_number"]] = dict(r)

        # All segments by pnr
        cur.execute("SELECT pnr, leg_order, flight_number, carrier_code, origin, destination, "
                    "scheduled_departure, scheduled_arrival FROM segments ORDER BY pnr, leg_order")
        seg_by_pnr = {}
        for r in cur.fetchall():
            d = dict(r)
            seg_by_pnr.setdefault(d["pnr"], []).append(d)

        # All travelers
        cur.execute("SELECT traveler_id, name, loyalty_tier FROM travelers")
        traveler_map = {}
        for r in cur.fetchall():
            traveler_map[r["traveler_id"]] = dict(r)

        flagged = []
        for bk in all_bookings:
            pnr = bk["pnr"]
            segs = seg_by_pnr.get(pnr, [])
            supp = supplements.get(pnr, {"special_assistance": False, "unaccompanied_minor": False})
            result = self._compute_booking_risk(segs, fs_map, min_conn_times, risk_config, supp)
            if result is None:
                continue

            trav = traveler_map.get(bk["traveler_id"], {})
            risk_score = result["risk_score"]
            loyalty = trav.get("loyalty_tier", "Basic")

            # Find alternative
            cur.execute(
                "SELECT flight_number, departure_time, available_seats "
                "FROM alternative_flights "
                "WHERE origin=? AND destination=? AND flight_date='2026-04-22' "
                "AND departure_time > ? AND available_seats > 0 "
                "ORDER BY departure_time LIMIT 1",
                (result["at_risk_origin"], result["at_risk_destination"],
                 result["at_risk_departure"]),
            )
            alt_row = cur.fetchone()
            recommended = alt_row["flight_number"] if alt_row else "NONE"

            # Priority
            if risk_score >= 80 and loyalty in ("Platinum", "Gold"):
                priority = 1
            elif risk_score >= 80:
                priority = 2
            elif loyalty in ("Platinum", "Gold"):
                priority = 3
            else:
                priority = 4

            flagged.append({
                "pnr": pnr,
                "traveler_name": trav.get("name", ""),
                "loyalty_tier": loyalty,
                "risk_score": risk_score,
                "risk_factors": result["risk_factors"],
                "at_risk_segment": result["at_risk_segment"],
                "recommended_alternative": recommended,
                "rebooking_priority": priority,
            })

        conn.close()

        flagged.sort(key=lambda x: (x["rebooking_priority"], -x["risk_score"], x["traveler_name"]))
        return flagged, len(all_bookings)

    # ----------------------------------------------------------------- eval

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
        ground_truth, total_bookings = self._compute_ground_truth()
        gt_pnrs = {r["pnr"] for r in ground_truth}
        gt_by_pnr = {r["pnr"]: r for r in ground_truth}

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: file exists and valid CSV (10 pts) ---
        csv_path = os.path.join(self.workspace, "rebooking_list.csv")
        c1_max = 10
        max_score += c1_max
        agent_rows = []
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_rows = list(reader)
            c1_pass = True
            c1_score = c1_max
        except Exception as e:
            c1_pass = False
            c1_score = 0
            eval_criteria["file_valid_csv"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": f"Could not read rebooking_list.csv: {e}",
            }
        if c1_pass:
            eval_criteria["file_valid_csv"] = {"passed": True, "score": c1_score, "max_score": c1_max}
        total_score += c1_score

        # --- Criterion 2: correct columns (10 pts) ---
        c2_max = 10
        max_score += c2_max
        expected_cols = ["pnr", "traveler_name", "loyalty_tier", "risk_score",
                         "risk_factors", "at_risk_segment", "recommended_alternative",
                         "rebooking_priority"]
        if agent_rows:
            actual_cols = list(agent_rows[0].keys())
            if actual_cols == expected_cols:
                c2_score = c2_max
                c2_pass = True
            else:
                # partial credit if all expected columns present
                if all(c in actual_cols for c in expected_cols):
                    c2_score = c2_max // 2
                    c2_pass = False
                else:
                    c2_score = 0
                    c2_pass = False
        else:
            c2_score = 0
            c2_pass = False
        eval_criteria["correct_columns"] = {
            "passed": c2_pass if c2_score == c2_max else False,
            "score": c2_score, "max_score": c2_max,
            "reason": "" if c2_score == c2_max else "Column mismatch",
        }
        total_score += c2_score

        # --- Criterion 3: recall – all true high-risk PNRs found (20 pts) ---
        c3_max = 20
        max_score += c3_max
        agent_pnrs = {r.get("pnr", "") for r in agent_rows}
        if gt_pnrs:
            recall = len(agent_pnrs & gt_pnrs) / len(gt_pnrs)
        else:
            recall = 1.0 if not agent_pnrs else 0.0
        c3_score = round(c3_max * recall)
        eval_criteria["recall_high_risk"] = {
            "passed": recall == 1.0,
            "score": c3_score, "max_score": c3_max,
            "reason": "" if recall == 1.0 else f"Recall={recall:.2f}, missing {gt_pnrs - agent_pnrs}",
        }
        total_score += c3_score

        # --- Criterion 4: precision – no false positives (15 pts) ---
        c4_max = 15
        max_score += c4_max
        if agent_pnrs:
            precision = len(agent_pnrs & gt_pnrs) / len(agent_pnrs)
        else:
            precision = 1.0 if not gt_pnrs else 0.0
        c4_score = round(c4_max * precision)
        eval_criteria["precision_no_false_positives"] = {
            "passed": precision == 1.0,
            "score": c4_score, "max_score": c4_max,
            "reason": "" if precision == 1.0 else f"Precision={precision:.2f}, extra {agent_pnrs - gt_pnrs}",
        }
        total_score += c4_score

        # --- Criterion 5: risk score accuracy (15 pts) ---
        c5_max = 15
        max_score += c5_max
        matched_pnrs = agent_pnrs & gt_pnrs
        if matched_pnrs:
            correct_scores = 0
            for pnr in matched_pnrs:
                agent_row = next((r for r in agent_rows if r.get("pnr") == pnr), None)
                if agent_row:
                    try:
                        agent_score = float(agent_row.get("risk_score", 0))
                        gt_score = gt_by_pnr[pnr]["risk_score"]
                        if abs(agent_score - gt_score) <= 2.0:
                            correct_scores += 1
                    except (ValueError, TypeError):
                        pass
            score_accuracy = correct_scores / len(matched_pnrs)
        else:
            score_accuracy = 0.0
        c5_score = round(c5_max * score_accuracy)
        eval_criteria["risk_score_accuracy"] = {
            "passed": score_accuracy == 1.0,
            "score": c5_score, "max_score": c5_max,
            "reason": "" if score_accuracy == 1.0 else f"Accuracy={score_accuracy:.2f}",
        }
        total_score += c5_score

        # --- Criterion 6: correct rebooking priorities (15 pts) ---
        c6_max = 15
        max_score += c6_max
        if matched_pnrs:
            correct_priorities = 0
            for pnr in matched_pnrs:
                agent_row = next((r for r in agent_rows if r.get("pnr") == pnr), None)
                if agent_row:
                    try:
                        if int(agent_row.get("rebooking_priority", 0)) == gt_by_pnr[pnr]["rebooking_priority"]:
                            correct_priorities += 1
                    except (ValueError, TypeError):
                        pass
            priority_accuracy = correct_priorities / len(matched_pnrs)
        else:
            priority_accuracy = 0.0
        c6_score = round(c6_max * priority_accuracy)
        eval_criteria["priority_accuracy"] = {
            "passed": priority_accuracy == 1.0,
            "score": c6_score, "max_score": c6_max,
            "reason": "" if priority_accuracy == 1.0 else f"Accuracy={priority_accuracy:.2f}",
        }
        total_score += c6_score

        # --- Criterion 7: correct sort order (15 pts) ---
        c7_max = 15
        max_score += c7_max
        if len(agent_rows) == len(ground_truth):
            agent_pnr_order = [r.get("pnr", "") for r in agent_rows]
            gt_pnr_order = [r["pnr"] for r in ground_truth]
            if agent_pnr_order == gt_pnr_order:
                c7_score = c7_max
            else:
                c7_score = 0
        else:
            c7_score = 0
        eval_criteria["sort_order"] = {
            "passed": c7_score == c7_max,
            "score": c7_score, "max_score": c7_max,
            "reason": "" if c7_score == c7_max else "Row order does not match expected sort",
        }
        total_score += c7_score

        # --- Response checks ---
        # Check that action mentions total bookings and flagged count
        c8_max = 10
        max_score += c8_max
        c8_score = 0
        if str(total_bookings) in action:
            c8_score += 4
        if str(len(ground_truth)) in action:
            c8_score += 3
        # Check highest risk PNR mentioned
        if ground_truth:
            highest = ground_truth[0]
            for r in ground_truth:
                if r["risk_score"] > highest["risk_score"]:
                    highest = r
            if highest["pnr"] in action:
                c8_score += 3
        else:
            c8_score += 3
        eval_criteria["response_summary"] = {
            "passed": c8_score == c8_max,
            "score": c8_score, "max_score": c8_max,
            "reason": "" if c8_score == c8_max else "Missing some summary items in response",
        }
        total_score += c8_score

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ---------------------------------------------------------------- verify

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as glob_mod

        # --- 1. Read workspace config files ---
        ws = self.workspace

        with open(os.path.join(ws, "connection_rules.yaml")) as f:
            conn_rules = yaml.safe_load(f)
        min_conn_times = {str(k): int(v) for k, v in conn_rules["minimum_connection_times"].items()}

        with open(os.path.join(ws, "risk_config.json")) as f:
            risk_config = json.load(f)

        with open(os.path.join(ws, "rebooking_policy.md")) as _:
            pass  # policy read for completeness; rules are known

        # --- 2. Read passenger supplement files ---
        supplements = {}
        for fname in sorted(os.listdir(ws)):
            if not fname.startswith("passenger_data_"):
                continue
            fpath = os.path.join(ws, fname)
            if fname.endswith(".json"):
                with open(fpath) as f:
                    data = json.load(f)
                for item in data:
                    supplements[item["pnr"]] = {
                        "special_assistance": bool(item.get("special_assistance", False)),
                        "unaccompanied_minor": bool(item.get("unaccompanied_minor", False)),
                    }
            elif fname.endswith(".csv"):
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        supplements[row["pnr"]] = {
                            "special_assistance": row["special_assistance"] == "True",
                            "unaccompanied_minor": row["unaccompanied_minor"] == "True",
                        }
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    content = f.read()
                for block in content.strip().split("---"):
                    block = block.strip()
                    if not block:
                        continue
                    d = {}
                    for line in block.split("\n"):
                        if ": " in line:
                            key, val = line.split(": ", 1)
                            d[key.strip()] = val.strip()
                    if "PNR" in d:
                        supplements[d["PNR"]] = {
                            "special_assistance": d.get("Special Assistance", "No") == "Yes",
                            "unaccompanied_minor": d.get("Unaccompanied Minor", "No") == "Yes",
                        }
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    data = yaml.safe_load(f)
                if data:
                    for item in data:
                        supplements[item["pnr"]] = {
                            "special_assistance": bool(item.get("special_assistance", False)),
                            "unaccompanied_minor": bool(item.get("unaccompanied_minor", False)),
                        }

        # --- 3. Get all bookings via tool ---
        all_bookings = []
        page = 1
        while True:
            result = self.tools["list_bookings"](page=page, page_size=20)
            all_bookings.extend(result["bookings"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- 4. Get segments and flight statuses ---
        booking_segments = {}
        flight_status_cache = {}
        tool_call_count = 0

        for bk in all_bookings:
            pnr = bk["pnr"]
            seg_result = self.tools["get_segments"](pnr=pnr)
            tool_call_count += 1
            booking_segments[pnr] = seg_result["segments"]

            for seg in seg_result["segments"]:
                fn = seg["flight_number"]
                if fn not in flight_status_cache:
                    fs = self.tools["get_flight_status"](
                        flight_number=fn, flight_date="2026-04-22")
                    tool_call_count += 1
                    flight_status_cache[fn] = fs

        # Count tool calls from list_bookings
        tool_call_count += page  # pages fetched

        # --- 5. Compute risk for each booking ---
        flagged = []
        for bk in all_bookings:
            pnr = bk["pnr"]
            segs = booking_segments[pnr]
            supp = supplements.get(pnr, {"special_assistance": False, "unaccompanied_minor": False})

            result = self._compute_booking_risk(segs, flight_status_cache,
                                                min_conn_times, risk_config, supp)
            if result is not None:
                flagged.append({
                    "pnr": pnr,
                    "traveler_id": bk["traveler_id"],
                    **result,
                })

        # --- 6. Get traveler info and search alternatives for flagged ---
        for item in flagged:
            trav = self.tools["get_traveler"](traveler_id=item["traveler_id"])
            tool_call_count += 1
            item["traveler_name"] = trav["name"]
            item["loyalty_tier"] = trav["loyalty_tier"]

            # Search alternative
            alts = self.tools["search_alternatives"](
                origin=item["at_risk_origin"],
                destination=item["at_risk_destination"],
                flight_date="2026-04-22",
                min_departure_time=item["at_risk_departure"],
            )
            tool_call_count += 1

            best_alt = None
            for alt in alts.get("alternatives", []):
                if alt["available_seats"] > 0 and alt["departure_time"] > item["at_risk_departure"]:
                    best_alt = alt
                    break  # already sorted by departure_time
            item["recommended_alternative"] = best_alt["flight_number"] if best_alt else "NONE"

            # Priority
            score = item["risk_score"]
            tier = item["loyalty_tier"]
            if score >= 80 and tier in ("Platinum", "Gold"):
                item["rebooking_priority"] = 1
            elif score >= 80:
                item["rebooking_priority"] = 2
            elif tier in ("Platinum", "Gold"):
                item["rebooking_priority"] = 3
            else:
                item["rebooking_priority"] = 4

        # --- 7. Sort ---
        flagged.sort(key=lambda x: (x["rebooking_priority"], -x["risk_score"], x["traveler_name"]))

        # --- 8. Write CSV ---
        csv_path = os.path.join(ws, "rebooking_list.csv")
        fieldnames = ["pnr", "traveler_name", "loyalty_tier", "risk_score",
                       "risk_factors", "at_risk_segment", "recommended_alternative",
                       "rebooking_priority"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in flagged:
                writer.writerow({
                    "pnr": item["pnr"],
                    "traveler_name": item["traveler_name"],
                    "loyalty_tier": item["loyalty_tier"],
                    "risk_score": item["risk_score"],
                    "risk_factors": item["risk_factors"],
                    "at_risk_segment": item["at_risk_segment"],
                    "recommended_alternative": item["recommended_alternative"],
                    "rebooking_priority": item["rebooking_priority"],
                })

        # --- 9. Construct action ---
        total = len(all_bookings)
        n_flagged = len(flagged)
        highest = max(flagged, key=lambda x: x["risk_score"]) if flagged else None

        action = f"Total itineraries analyzed: {total}\n"
        action += f"High-risk itineraries: {n_flagged}\n"
        if highest:
            action += f"Highest risk: PNR {highest['pnr']} with score {highest['risk_score']}"

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need >= 15"

        return self.step(action)
