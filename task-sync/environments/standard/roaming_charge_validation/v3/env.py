"""
env.py  --  Task environment for roaming-charge dispute validation.
"""

import sqlite3
import os
import json
import csv
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


# ── Tool decorator ───────────────────────────────────────────────────
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

    # ── keep this implementation unchanged ───────────────────────
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

    # ─────────────────────────────────────────────────────────────
    #  TOOLS
    # ─────────────────────────────────────────────────────────────

    @tool(
        description=(
            "List dispute tickets with status 'open' or 'pending_review'. "
            "Returns a paginated list of ticket summaries (10 per page)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Each page returns up to 10 tickets.",
                },
            },
            "required": ["page"],
        },
    )
    def list_open_disputes(self, page: int = 1) -> dict:
        page_size = 10
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT ticket_id, subscriber_id, status "
            "FROM dispute_tickets "
            "WHERE status IN ('open','pending_review') "
            "ORDER BY ticket_id "
            "LIMIT ? OFFSET ?",
            (page_size + 1, offset),
        )
        rows = cur.fetchall()
        conn.close()
        has_more = len(rows) > page_size
        tickets = [
            {"ticket_id": r[0], "subscriber_id": r[1], "status": r[2]}
            for r in rows[:page_size]
        ]
        return {"tickets": tickets, "has_more": has_more, "page": page}

    @tool(
        description="Get full details of a dispute ticket by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The dispute ticket ID (e.g. 'DT00001').",
                },
            },
            "required": ["ticket_id"],
        },
    )
    def get_dispute_details(self, ticket_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT ticket_id, subscriber_id, roaming_log_id, "
            "dispute_reason, status, filed_date, amount_disputed "
            "FROM dispute_tickets WHERE ticket_id = ?",
            (ticket_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Ticket '{ticket_id}' not found"}
        return {
            "ticket_id": row[0],
            "subscriber_id": row[1],
            "roaming_log_id": row[2],
            "dispute_reason": row[3],
            "status": row[4],
            "filed_date": row[5],
            "amount_disputed": row[6],
        }

    @tool(
        description="Get full details of a roaming log entry by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "log_id": {
                    "type": "string",
                    "description": "The roaming log ID (e.g. 'RL00001').",
                },
            },
            "required": ["log_id"],
        },
    )
    def get_roaming_log(self, log_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT log_id, subscriber_id, event_timestamp, "
            "visited_country, partner_carrier, "
            "call_duration_min, data_usage_mb, sms_count, "
            "billed_amount, billing_currency "
            "FROM roaming_logs WHERE log_id = ?",
            (log_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Log '{log_id}' not found"}
        return {
            "log_id": row[0],
            "subscriber_id": row[1],
            "event_timestamp": row[2],
            "visited_country": row[3],
            "partner_carrier": row[4],
            "call_duration_min": row[5],
            "data_usage_mb": row[6],
            "sms_count": row[7],
            "billed_amount": row[8],
            "billing_currency": row[9],
        }

    @tool(
        description=(
            "Get the tariff rate for a partner carrier in a billing zone on a "
            "specific date. Returns the tariff agreement that is valid on the "
            "given date (effective_date <= date <= expiry_date). "
            "The zone must be one of Zone_A, Zone_B, Zone_C, Zone_D."
        ),
        parameters={
            "type": "object",
            "properties": {
                "partner_carrier": {
                    "type": "string",
                    "description": "Name of the partner carrier.",
                },
                "zone": {
                    "type": "string",
                    "description": "Billing zone (Zone_A, Zone_B, Zone_C, or Zone_D).",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["partner_carrier", "zone", "date"],
        },
    )
    def get_tariff_rate(self, partner_carrier: str, zone: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT agreement_id, partner_carrier, zone, "
            "voice_rate_per_min, data_rate_per_mb, sms_rate, "
            "effective_date, expiry_date, currency "
            "FROM tariff_agreements "
            "WHERE partner_carrier = ? AND zone = ? "
            "AND effective_date <= ? AND expiry_date >= ? "
            "ORDER BY effective_date DESC LIMIT 1",
            (partner_carrier, zone, date, date),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": "No valid tariff agreement found"}
        return {
            "agreement_id": row[0],
            "partner_carrier": row[1],
            "zone": row[2],
            "voice_rate_per_min": row[3],
            "data_rate_per_mb": row[4],
            "sms_rate": row[5],
            "effective_date": row[6],
            "expiry_date": row[7],
            "currency": row[8],
        }

    @tool(
        description="Get subscriber information by subscriber ID.",
        parameters={
            "type": "object",
            "properties": {
                "subscriber_id": {
                    "type": "string",
                    "description": "The subscriber ID (e.g. 'S0001').",
                },
            },
            "required": ["subscriber_id"],
        },
    )
    def get_subscriber_info(self, subscriber_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT subscriber_id, name, phone, home_country, "
            "plan_type, registration_date "
            "FROM subscribers WHERE subscriber_id = ?",
            (subscriber_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Subscriber '{subscriber_id}' not found"}
        return {
            "subscriber_id": row[0],
            "name": row[1],
            "phone": row[2],
            "home_country": row[3],
            "plan_type": row[4],
            "registration_date": row[5],
        }

    @tool(
        description=(
            "Search roaming logs for a specific subscriber on a given date. "
            "Returns a list of roaming log IDs that match. Useful for finding "
            "potential duplicate charges."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subscriber_id": {
                    "type": "string",
                    "description": "The subscriber ID.",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
            },
            "required": ["subscriber_id", "date"],
        },
    )
    def search_roaming_logs(self, subscriber_id: str, date: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT log_id FROM roaming_logs "
            "WHERE subscriber_id = ? AND event_timestamp LIKE ? "
            "ORDER BY log_id",
            (subscriber_id, date + "%"),
        )
        rows = cur.fetchall()
        conn.close()
        return {"log_ids": [r[0] for r in rows]}

    # ─────────────────────────────────────────────────────────────
    #  STEP  (evaluation)
    # ─────────────────────────────────────────────────────────────

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
        # ── Load ground truth ──
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT ticket_id, log_id, subscriber_id, subscriber_name, "
            "error_type, billed_amount, correct_amount, refund_amount, "
            "charge_reference FROM ground_truth WHERE error_type != 'none'"
        )
        gt_rows = cur.fetchall()
        conn.close()

        gt = {}
        for r in gt_rows:
            gt[r[0]] = {
                "ticket_id": r[0], "log_id": r[1],
                "subscriber_id": r[2], "subscriber_name": r[3],
                "error_type": r[4], "billed_amount": r[5],
                "correct_amount": r[6], "refund_amount": r[7],
                "charge_reference": r[8],
            }

        info = {"eval_criteria": {}, "total_score": 0, "max_score": 100}

        # ── Criterion 1: file structure (10 pts) ──
        refund_path = os.path.join(self.workspace, "refund_list.csv")
        expected_cols = [
            "ticket_id", "log_id", "subscriber_id", "subscriber_name",
            "error_type", "billed_amount", "correct_amount",
            "refund_amount", "charge_reference",
        ]

        if not os.path.exists(refund_path):
            info["eval_criteria"]["file_structure"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "refund_list.csv not found",
            }
            info["total_score"] = 0
            return 0.0, info

        agent_entries = []
        with open(refund_path, newline="") as f:
            reader = csv.DictReader(f)
            actual_cols = list(reader.fieldnames or [])
            for row in reader:
                agent_entries.append(row)

        cols_ok = set(expected_cols) == set(actual_cols)
        info["eval_criteria"]["file_structure"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 3,
            "max_score": 10,
            "reason": "" if cols_ok else f"Expected columns {expected_cols}, got {actual_cols}",
        }

        agent = {}
        for e in agent_entries:
            tid = e.get("ticket_id", "")
            if tid:
                agent[tid] = e

        # ── Criterion 2: ticket identification (20 pts) ──
        expected_tids = set(gt.keys())
        actual_tids = set(agent.keys())
        tp = expected_tids & actual_tids
        fp = actual_tids - expected_tids
        fn = expected_tids - actual_tids

        if actual_tids and expected_tids:
            precision = len(tp) / len(actual_tids)
            recall = len(tp) / len(expected_tids)
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )
        elif not expected_tids and not actual_tids:
            f1 = 1.0
        else:
            f1 = 0.0

        score2 = round(f1 * 20)
        info["eval_criteria"]["ticket_identification"] = {
            "passed": f1 == 1.0,
            "score": score2,
            "max_score": 20,
            "reason": (
                "" if f1 == 1.0
                else f"F1={f1:.3f}, TP={len(tp)}, FP={len(fp)}, FN={len(fn)}"
            ),
        }

        # ── Criterion 3: error classification (15 pts) ──
        correct_types = 0
        for tid in tp:
            if agent[tid].get("error_type", "").strip() == gt[tid]["error_type"]:
                correct_types += 1
        type_acc = correct_types / max(1, len(tp))
        score3 = round(type_acc * 15)
        info["eval_criteria"]["error_classification"] = {
            "passed": type_acc == 1.0,
            "score": score3,
            "max_score": 15,
            "reason": "" if type_acc == 1.0 else f"Accuracy={type_acc:.3f}",
        }

        # ── Criterion 4: refund amounts (20 pts) ──
        correct_amts = 0
        for tid in tp:
            try:
                a = float(agent[tid].get("refund_amount", 0))
                e = gt[tid]["refund_amount"]
                if abs(a - e) <= 0.02:
                    correct_amts += 1
            except (ValueError, TypeError):
                pass
        amt_acc = correct_amts / max(1, len(tp))
        score4 = round(amt_acc * 20)
        info["eval_criteria"]["refund_amounts"] = {
            "passed": amt_acc == 1.0,
            "score": score4,
            "max_score": 20,
            "reason": "" if amt_acc == 1.0 else f"Accuracy={amt_acc:.3f}",
        }

        # ── Criterion 5: charge references (10 pts) ──
        correct_refs = 0
        for tid in tp:
            if agent[tid].get("charge_reference", "").strip() == gt[tid]["charge_reference"]:
                correct_refs += 1
        ref_acc = correct_refs / max(1, len(tp))
        score5 = round(ref_acc * 10)
        info["eval_criteria"]["charge_references"] = {
            "passed": ref_acc == 1.0,
            "score": score5,
            "max_score": 10,
            "reason": "" if ref_acc == 1.0 else f"Accuracy={ref_acc:.3f}",
        }

        # ── Criterion 6: sort order (10 pts) ──
        sort_ok = True
        if len(agent_entries) >= 2:
            for i in range(len(agent_entries) - 1):
                try:
                    ra = float(agent_entries[i].get("refund_amount", 0))
                    rb = float(agent_entries[i + 1].get("refund_amount", 0))
                    ta = agent_entries[i].get("ticket_id", "")
                    tb = agent_entries[i + 1].get("ticket_id", "")
                    if ra < rb or (ra == rb and ta > tb):
                        sort_ok = False
                        break
                except ValueError:
                    sort_ok = False
                    break
        elif len(agent_entries) != len(gt):
            sort_ok = False

        score6 = 10 if sort_ok else 0
        info["eval_criteria"]["sort_order"] = {
            "passed": sort_ok,
            "score": score6,
            "max_score": 10,
            "reason": "" if sort_ok else "Rows not sorted by refund_amount desc then ticket_id asc",
        }

        # ── Criterion 7: summary in response (15 pts) ──
        summary_score = 0
        n_erroneous = len(gt)
        total_refund = round(sum(g["refund_amount"] for g in gt.values()), 2)
        error_types_present = set(g["error_type"] for g in gt.values())

        if str(n_erroneous) in action:
            summary_score += 5
        if f"{total_refund:.2f}" in action:
            summary_score += 5
        if all(et in action for et in error_types_present):
            summary_score += 5

        info["eval_criteria"]["summary_response"] = {
            "passed": summary_score == 15,
            "score": summary_score,
            "max_score": 15,
            "reason": "" if summary_score == 15 else "Incomplete summary statistics in response",
        }

        total = sum(c["score"] for c in info["eval_criteria"].values())
        info["total_score"] = total
        info["max_score"] = 100
        return total / 100.0, info

    # ─────────────────────────────────────────────────────────────
    #  VERIFY  (self-test)
    # ─────────────────────────────────────────────────────────────

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
        import json
        import csv
        import os
        from datetime import datetime, timedelta

        # ── 1. Read workspace config files ──
        # billing_rules.yaml (simple key:value)
        rules = {}
        with open(os.path.join(self.workspace, "billing_rules.yaml")) as f:
            for line in f:
                line = line.strip()
                if ":" in line and not line.startswith("#"):
                    k, v = line.split(":", 1)
                    try:
                        rules[k.strip()] = float(v.strip())
                    except ValueError:
                        rules[k.strip()] = v.strip()

        tolerance_pct = rules.get("rate_overcharge_tolerance_pct", 5.0) / 100.0
        loc_window_min = rules.get("location_check_window_minutes", 60)
        min_refund = rules.get("minimum_refund_amount", 1.0)

        # carrier_zones.json
        with open(os.path.join(self.workspace, "carrier_zones.json")) as f:
            zones = json.load(f)
        country_to_zone = {}
        for zone, countries in zones.items():
            for c in countries:
                country_to_zone[c] = zone

        # Location records (all JSON files)
        location_records = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("location_records_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    location_records.extend(json.load(f))

        # Charge references (all CSV files)
        charge_refs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("charge_references_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        charge_refs[row["log_id"]] = row["charge_reference"]

        # ── 2. List all open disputes via tool ──
        all_disputes = []
        page = 1
        while True:
            result = self.tools["list_open_disputes"](page=page)
            all_disputes.extend(result["tickets"])
            if not result["has_more"]:
                break
            page += 1

        # ── 3. Process each dispute ──
        refund_entries = []
        subscriber_cache = {}

        for dispute_summary in all_disputes:
            ticket_id = dispute_summary["ticket_id"]

            # Get full dispute details
            details = self.tools["get_dispute_details"](ticket_id=ticket_id)
            log_id = details["roaming_log_id"]

            # Get roaming log
            log = self.tools["get_roaming_log"](log_id=log_id)

            # Get subscriber info (with cache)
            sub_id = log["subscriber_id"]
            if sub_id not in subscriber_cache:
                subscriber_cache[sub_id] = self.tools["get_subscriber_info"](
                    subscriber_id=sub_id
                )
            sub = subscriber_cache[sub_id]

            # Look up zone from carrier_zones.json
            visited = log["visited_country"]
            zone = country_to_zone.get(visited, "Zone_D")

            # Get tariff rate
            event_date = log["event_timestamp"].split(" ")[0]
            tariff = self.tools["get_tariff_rate"](
                partner_carrier=log["partner_carrier"],
                zone=zone,
                date=event_date,
            )

            if "error" in tariff:
                # No valid tariff; skip
                continue

            # Calculate correct amount
            correct = round(
                log["call_duration_min"] * tariff["voice_rate_per_min"]
                + log["data_usage_mb"] * tariff["data_rate_per_mb"]
                + log["sms_count"] * tariff["sms_rate"],
                2,
            )

            # ── Check 1: not_roaming ──
            event_dt = datetime.strptime(
                log["event_timestamp"], "%Y-%m-%d %H:%M:%S"
            )
            is_home = False
            for loc in location_records:
                if loc["subscriber_id"] != sub_id:
                    continue
                loc_dt = datetime.strptime(loc["timestamp"], "%Y-%m-%d %H:%M:%S")
                if abs((loc_dt - event_dt).total_seconds()) <= loc_window_min * 60:
                    if loc["detected_country"] == sub["home_country"]:
                        is_home = True
                        break

            if is_home:
                refund_entries.append({
                    "ticket_id": ticket_id,
                    "log_id": log_id,
                    "subscriber_id": sub_id,
                    "subscriber_name": sub["name"],
                    "error_type": "not_roaming",
                    "billed_amount": f"{log['billed_amount']:.2f}",
                    "correct_amount": "0.00",
                    "refund_amount": f"{log['billed_amount']:.2f}",
                    "charge_reference": charge_refs.get(log_id, ""),
                })
                continue

            # ── Check 2: rate_overcharge ──
            if log["billed_amount"] > correct * (1 + tolerance_pct):
                refund_amount = round(log["billed_amount"] - correct, 2)
                if refund_amount >= min_refund:
                    refund_entries.append({
                        "ticket_id": ticket_id,
                        "log_id": log_id,
                        "subscriber_id": sub_id,
                        "subscriber_name": sub["name"],
                        "error_type": "rate_overcharge",
                        "billed_amount": f"{log['billed_amount']:.2f}",
                        "correct_amount": f"{correct:.2f}",
                        "refund_amount": f"{refund_amount:.2f}",
                        "charge_reference": charge_refs.get(log_id, ""),
                    })
                    continue

            # ── Check 3: duplicate_charge ──
            matches = self.tools["search_roaming_logs"](
                subscriber_id=sub_id, date=event_date
            )
            duplicate_found = False
            for match_id in matches["log_ids"]:
                if match_id == log_id:
                    continue
                match_log = self.tools["get_roaming_log"](log_id=match_id)
                if (
                    match_log["event_timestamp"] == log["event_timestamp"]
                    and match_log["call_duration_min"] == log["call_duration_min"]
                    and match_log["data_usage_mb"] == log["data_usage_mb"]
                    and match_log["sms_count"] == log["sms_count"]
                ):
                    dup_id = max(log_id, match_id)
                    refund_entries.append({
                        "ticket_id": ticket_id,
                        "log_id": dup_id,
                        "subscriber_id": sub_id,
                        "subscriber_name": sub["name"],
                        "error_type": "duplicate_charge",
                        "billed_amount": f"{log['billed_amount']:.2f}",
                        "correct_amount": "0.00",
                        "refund_amount": f"{log['billed_amount']:.2f}",
                        "charge_reference": charge_refs.get(dup_id, ""),
                    })
                    duplicate_found = True
                    break

            # If none of the checks triggered, the dispute is legitimate -> no refund

        # ── 4. Sort: refund_amount desc, ticket_id asc ──
        refund_entries.sort(
            key=lambda x: (-float(x["refund_amount"]), x["ticket_id"])
        )

        # ── 5. Write refund_list.csv ──
        fieldnames = [
            "ticket_id", "log_id", "subscriber_id", "subscriber_name",
            "error_type", "billed_amount", "correct_amount",
            "refund_amount", "charge_reference",
        ]
        with open(
            os.path.join(self.workspace, "refund_list.csv"), "w", newline=""
        ) as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(refund_entries)

        # ── 6. Build summary action string ──
        total_refund = round(
            sum(float(e["refund_amount"]) for e in refund_entries), 2
        )
        by_type: Dict[str, int] = {}
        for e in refund_entries:
            by_type[e["error_type"]] = by_type.get(e["error_type"], 0) + 1

        action = (
            f"Completed roaming charge dispute analysis. "
            f"Found {len(refund_entries)} erroneous charges out of "
            f"{len(all_disputes)} open disputes investigated. "
            f"Total refund amount: ${total_refund:.2f}. "
            f"Breakdown by error type: "
            + ", ".join(f"{k}: {v}" for k, v in sorted(by_type.items()))
            + ". Results saved to refund_list.csv."
        )

        return self.step(action)
