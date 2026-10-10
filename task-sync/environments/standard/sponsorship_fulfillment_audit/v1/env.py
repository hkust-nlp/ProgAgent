import sqlite3
import os
import json
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

    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ─────────────────────────── Tools ───────────────────────────

    @tool(
        description="List events with optional filtering. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "description": "Filter by event type (match, concert, festival, conference, gala). Optional.",
                },
                "venue": {
                    "type": "string",
                    "description": "Filter by venue name (exact match). Optional.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1. Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page, max 20. Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_events(self, event_type: str = None, venue: str = None,
                    page: int = 1, page_size: int = 20) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conditions, params = [], []
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if venue:
            conditions.append("venue = ?")
            params.append(venue)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        count_row = self._query(f"SELECT COUNT(*) as cnt FROM events{where}", params)
        total = count_row[0]["cnt"]
        rows = self._query(
            f"SELECT * FROM events{where} ORDER BY event_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        return {"events": rows, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="List sponsors with optional filtering. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "description": "Filter by sponsor tier (platinum, gold, silver, bronze). Optional.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting from 1. Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page, max 20. Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_sponsors(self, tier: str = None, page: int = 1,
                      page_size: int = 20) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conditions, params = [], []
        if tier:
            conditions.append("tier = ?")
            params.append(tier)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        count_row = self._query(f"SELECT COUNT(*) as cnt FROM sponsors{where}", params)
        total = count_row[0]["cnt"]
        rows = self._query(
            f"SELECT * FROM sponsors{where} ORDER BY sponsor_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        return {"sponsors": rows, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="Get details for a single sponsor by ID.",
        parameters={
            "type": "object",
            "properties": {
                "sponsor_id": {
                    "type": "integer",
                    "description": "The sponsor's unique identifier.",
                },
            },
            "required": ["sponsor_id"],
        },
    )
    def get_sponsor(self, sponsor_id: int) -> dict:
        rows = self._query("SELECT * FROM sponsors WHERE sponsor_id = ?",
                           (int(sponsor_id),))
        if not rows:
            return {"error": "Sponsor not found"}
        return rows[0]

    @tool(
        description=(
            "Retrieve entitlements (contracted sponsorship assets). "
            "Filter by sponsor_id and/or event_id. At least one filter is required."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sponsor_id": {
                    "type": "integer",
                    "description": "Filter by sponsor ID. Optional if event_id is provided.",
                },
                "event_id": {
                    "type": "integer",
                    "description": "Filter by event ID. Optional if sponsor_id is provided.",
                },
            },
            "required": [],
        },
    )
    def get_entitlements(self, sponsor_id: int = None,
                         event_id: int = None) -> dict:
        if sponsor_id is None and event_id is None:
            return {"error": "Provide at least one of sponsor_id or event_id."}
        conditions, params = [], []
        if sponsor_id is not None:
            conditions.append("sponsor_id = ?")
            params.append(int(sponsor_id))
        if event_id is not None:
            conditions.append("event_id = ?")
            params.append(int(event_id))
        where = " AND ".join(conditions)
        rows = self._query(
            f"SELECT * FROM entitlements WHERE {where} ORDER BY entitlement_id",
            params,
        )
        return {"entitlements": rows}

    @tool(
        description=(
            "Retrieve broadcast camera-angle logs for a specific event and sponsor."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "integer",
                    "description": "Event ID.",
                },
                "sponsor_id": {
                    "type": "integer",
                    "description": "Sponsor ID.",
                },
            },
            "required": ["event_id", "sponsor_id"],
        },
    )
    def get_broadcast_logs(self, event_id: int, sponsor_id: int) -> dict:
        rows = self._query(
            "SELECT * FROM broadcast_logs WHERE event_id = ? AND sponsor_id = ? "
            "ORDER BY log_id",
            (int(event_id), int(sponsor_id)),
        )
        return {"logs": rows, "count": len(rows)}

    @tool(
        description=(
            "Retrieve in-stadium digital signage schedule records for a "
            "specific event and sponsor."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "integer",
                    "description": "Event ID.",
                },
                "sponsor_id": {
                    "type": "integer",
                    "description": "Sponsor ID.",
                },
            },
            "required": ["event_id", "sponsor_id"],
        },
    )
    def get_signage_records(self, event_id: int, sponsor_id: int) -> dict:
        rows = self._query(
            "SELECT * FROM signage_schedules WHERE event_id = ? AND sponsor_id = ? "
            "ORDER BY schedule_id",
            (int(event_id), int(sponsor_id)),
        )
        return {"records": rows, "count": len(rows)}

    @tool(
        description=(
            "Retrieve social media monitoring feed entries for a specific "
            "event and sponsor."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "integer",
                    "description": "Event ID.",
                },
                "sponsor_id": {
                    "type": "integer",
                    "description": "Sponsor ID.",
                },
            },
            "required": ["event_id", "sponsor_id"],
        },
    )
    def get_social_media_feeds(self, event_id: int, sponsor_id: int) -> dict:
        rows = self._query(
            "SELECT * FROM social_media_feeds WHERE event_id = ? AND sponsor_id = ? "
            "ORDER BY feed_id",
            (int(event_id), int(sponsor_id)),
        )
        return {"feeds": rows, "count": len(rows)}

    @tool(
        description=(
            "Get a summary count of entitlements grouped by asset type, "
            "optionally filtered by sponsor_id or event_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sponsor_id": {
                    "type": "integer",
                    "description": "Filter by sponsor ID. Optional.",
                },
                "event_id": {
                    "type": "integer",
                    "description": "Filter by event ID. Optional.",
                },
            },
            "required": [],
        },
    )
    def get_entitlement_summary(self, sponsor_id: int = None,
                                 event_id: int = None) -> dict:
        conditions, params = [], []
        if sponsor_id is not None:
            conditions.append("sponsor_id = ?")
            params.append(int(sponsor_id))
        if event_id is not None:
            conditions.append("event_id = ?")
            params.append(int(event_id))
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = self._query(
            f"SELECT asset_type, COUNT(*) as count, SUM(contracted_impressions) as total_contracted "
            f"FROM entitlements{where} GROUP BY asset_type ORDER BY asset_type",
            params,
        )
        return {"summary": rows}

    # ─────────────────────── Evaluation ───────────────────────

    def _compute_ground_truth(self):
        """Compute the full compliance report ground truth."""
        import yaml

        # Load config files
        with open(os.path.join(self.workspace, "compliance_thresholds.yaml")) as f:
            thresholds_data = yaml.safe_load(f)
        thresholds = thresholds_data["compliance_thresholds"]

        with open(os.path.join(self.workspace, "billing_adjustment_rates.json")) as f:
            adj_data = json.load(f)
        bands = adj_data["shortfall_bands"]

        # Load impression weights
        weights = {}
        with open(os.path.join(self.workspace, "impression_weights.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                weights[row["platform"]] = float(row["weight"])

        # Load venue visibility factors from all venue_report_*.json
        visibility = {}  # (venue_name, screen_id) -> factor
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "venue_report_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
            for venue_entry in data["venues"]:
                vname = venue_entry["venue_name"]
                for scr in venue_entry["screens"]:
                    visibility[(vname, scr["screen_id"])] = scr["visibility_factor"]

        # Load social verification
        verified_map = {}  # feed_id -> bool
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "social_verification_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    verified_map[int(row["feed_id"])] = row["verified"] == "True"

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all entitlements
        entitlements = [dict(r) for r in conn.execute(
            "SELECT * FROM entitlements ORDER BY entitlement_id"
        ).fetchall()]

        # Get sponsor info
        sponsors = {}
        for r in conn.execute("SELECT * FROM sponsors").fetchall():
            sponsors[r["sponsor_id"]] = dict(r)

        # Get event info
        events_map = {}
        for r in conn.execute("SELECT * FROM events").fetchall():
            events_map[r["event_id"]] = dict(r)

        results = []
        for ent in entitlements:
            eid = ent["entitlement_id"]
            sid = ent["sponsor_id"]
            evid = ent["event_id"]
            atype = ent["asset_type"]
            contracted = ent["contracted_impressions"]
            penalty_rate = ent["penalty_rate_pct"]
            sponsor = sponsors[sid]
            event = events_map[evid]

            # Calculate delivered impressions
            delivered = 0.0

            if atype == "broadcast":
                logs = [dict(r) for r in conn.execute(
                    "SELECT * FROM broadcast_logs WHERE event_id = ? AND sponsor_id = ?",
                    (evid, sid),
                ).fetchall()]
                delivered = sum(l["raw_impressions"] for l in logs)

            elif atype == "signage":
                recs = [dict(r) for r in conn.execute(
                    "SELECT * FROM signage_schedules WHERE event_id = ? AND sponsor_id = ?",
                    (evid, sid),
                ).fetchall()]
                venue_name = event["venue"]
                for rec in recs:
                    scr = rec["screen_id"]
                    vis = visibility.get((venue_name, scr), 1.0)
                    delivered += rec["actual_displays"] * vis

            elif atype == "social_media":
                feeds = [dict(r) for r in conn.execute(
                    "SELECT * FROM social_media_feeds WHERE event_id = ? AND sponsor_id = ?",
                    (evid, sid),
                ).fetchall()]
                for feed in feeds:
                    plat_weight = weights.get(feed["platform"], 1.0)
                    is_verified = verified_map.get(feed["feed_id"], False)
                    ver_factor = 1.0 if is_verified else 0.5
                    delivered += feed["impressions"] * plat_weight * ver_factor

            delivered = round(delivered, 2)

            # Compliance check
            tier = sponsor["tier"]
            threshold = thresholds.get(tier, 0.90)
            delivery_pct = delivered / contracted if contracted > 0 else 0.0
            compliant = delivery_pct >= threshold

            # Shortfall and billing adjustment
            shortfall_impressions = max(0, contracted - delivered)
            shortfall_pct = (shortfall_impressions / contracted * 100) if contracted > 0 else 0.0

            adjustment_multiplier = 0.0
            for band in bands:
                if band["min_shortfall_pct"] <= shortfall_pct < band["max_shortfall_pct"]:
                    adjustment_multiplier = band["adjustment_multiplier"]
                    break
            if shortfall_pct >= bands[-1]["max_shortfall_pct"]:
                adjustment_multiplier = bands[-1]["adjustment_multiplier"]

            if compliant or shortfall_impressions == 0:
                billing_adjustment = 0.0
            else:
                billing_adjustment = round(
                    shortfall_impressions * (penalty_rate / 100.0) * adjustment_multiplier, 2
                )

            results.append({
                "entitlement_id": eid,
                "sponsor_id": sid,
                "sponsor_name": sponsor["sponsor_name"],
                "sponsor_tier": tier,
                "event_id": evid,
                "event_name": event["event_name"],
                "asset_type": atype,
                "contracted_impressions": contracted,
                "delivered_impressions": delivered,
                "delivery_pct": round(delivery_pct * 100, 2),
                "compliant": compliant,
                "shortfall_impressions": round(shortfall_impressions, 2),
                "shortfall_pct": round(shortfall_pct, 2),
                "billing_adjustment": billing_adjustment,
            })

        conn.close()
        return results

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        ground_truth = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: compliance_report.csv exists and has correct columns (15 pts) ──
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        c1_score = 0
        c1_max = 15
        required_cols = {
            "entitlement_id", "sponsor_name", "event_name", "asset_type",
            "contracted_impressions", "delivered_impressions", "delivery_pct",
            "compliant", "shortfall_impressions", "billing_adjustment",
        }
        report_rows = []
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    report_rows = list(reader)
                    if required_cols.issubset(set(reader.fieldnames or [])):
                        c1_score = 15
                    else:
                        c1_score = 5  # file exists but wrong columns
            except Exception:
                c1_score = 0
        eval_criteria["report_file_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "Missing or malformed compliance_report.csv",
        }

        # ── Criterion 2: Correct number of rows in report (10 pts) ──
        c2_max = 10
        expected_count = len(ground_truth)
        actual_count = len(report_rows)
        if actual_count == expected_count:
            c2_score = 10
        elif abs(actual_count - expected_count) <= 2:
            c2_score = 5
        else:
            c2_score = 0
        eval_criteria["report_row_count"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score == c2_max else f"Expected {expected_count} rows, got {actual_count}",
        }

        # ── Criterion 3: Delivered impressions accuracy (25 pts) ──
        c3_max = 25
        gt_by_eid = {r["entitlement_id"]: r for r in ground_truth}
        correct_delivered = 0
        total_matched = 0
        for row in report_rows:
            try:
                eid = int(row.get("entitlement_id", -1))
                if eid in gt_by_eid:
                    total_matched += 1
                    gt_val = gt_by_eid[eid]["delivered_impressions"]
                    agent_val = float(row.get("delivered_impressions", 0))
                    if abs(agent_val - gt_val) / max(gt_val, 1) < 0.02:
                        correct_delivered += 1
            except (ValueError, TypeError):
                continue
        if total_matched > 0:
            accuracy = correct_delivered / len(ground_truth)
        else:
            accuracy = 0.0
        c3_score = round(c3_max * min(1.0, accuracy), 1)
        eval_criteria["delivered_impressions_accuracy"] = {
            "passed": c3_score >= c3_max * 0.95,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score >= c3_max * 0.95 else f"Accuracy: {accuracy:.2%} ({correct_delivered}/{len(ground_truth)})",
        }

        # ── Criterion 4: Compliance status accuracy (15 pts) ──
        c4_max = 15
        correct_compliance = 0
        for row in report_rows:
            try:
                eid = int(row.get("entitlement_id", -1))
                if eid in gt_by_eid:
                    gt_comp = gt_by_eid[eid]["compliant"]
                    agent_comp = row.get("compliant", "").strip().lower() in ("true", "yes", "1")
                    if agent_comp == gt_comp:
                        correct_compliance += 1
            except (ValueError, TypeError):
                continue
        if len(ground_truth) > 0:
            comp_accuracy = correct_compliance / len(ground_truth)
        else:
            comp_accuracy = 0.0
        c4_score = round(c4_max * min(1.0, comp_accuracy), 1)
        eval_criteria["compliance_status_accuracy"] = {
            "passed": c4_score >= c4_max * 0.95,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score >= c4_max * 0.95 else f"Compliance accuracy: {comp_accuracy:.2%}",
        }

        # ── Criterion 5: Billing adjustment accuracy (20 pts) ──
        c5_max = 20
        correct_billing = 0
        for row in report_rows:
            try:
                eid = int(row.get("entitlement_id", -1))
                if eid in gt_by_eid:
                    gt_adj = gt_by_eid[eid]["billing_adjustment"]
                    agent_adj = float(row.get("billing_adjustment", 0))
                    if abs(agent_adj - gt_adj) / max(abs(gt_adj), 1) < 0.02:
                        correct_billing += 1
            except (ValueError, TypeError):
                continue
        if len(ground_truth) > 0:
            bill_accuracy = correct_billing / len(ground_truth)
        else:
            bill_accuracy = 0.0
        c5_score = round(c5_max * min(1.0, bill_accuracy), 1)
        eval_criteria["billing_adjustment_accuracy"] = {
            "passed": c5_score >= c5_max * 0.95,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score >= c5_max * 0.95 else f"Billing accuracy: {bill_accuracy:.2%}",
        }

        # ── Criterion 6: Response summary contains key statistics (15 pts) ──
        c6_max = 15
        c6_score = 0
        total_entitlements = len(ground_truth)
        non_compliant_count = sum(1 for r in ground_truth if not r["compliant"])
        total_billing = round(sum(r["billing_adjustment"] for r in ground_truth), 2)

        action_lower = action.lower() if action else ""
        # Check that action mentions total entitlements, non-compliant count, total billing
        found_items = 0
        if str(total_entitlements) in action:
            found_items += 1
        if str(non_compliant_count) in action:
            found_items += 1
        # For total billing, accept any number within $1 of the ground truth
        # to absorb float-accumulation drift between per-row rounded sums.
        import re as _re
        billing_found = False
        for m in _re.finditer(r"[-+]?\d{1,}(?:,\d{3})*(?:\.\d+)?", action or ""):
            try:
                val = float(m.group(0).replace(",", ""))
            except ValueError:
                continue
            if abs(val - total_billing) <= 1.0:
                billing_found = True
                break
        if billing_found:
            found_items += 1
        c6_score = round(c6_max * found_items / 3, 1)
        eval_criteria["response_summary_stats"] = {
            "passed": found_items == 3,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if found_items == 3 else f"Found {found_items}/3 key statistics in response",
        }

        for k, v in eval_criteria.items():
            total_score += v["score"]
            max_score += v["max_score"]

        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files.
        """
        import yaml

        # Step 1: Read workspace config files
        with open(os.path.join(self.workspace, "compliance_thresholds.yaml")) as f:
            thresholds_data = yaml.safe_load(f)
        thresholds = thresholds_data["compliance_thresholds"]

        with open(os.path.join(self.workspace, "billing_adjustment_rates.json")) as f:
            adj_data = json.load(f)
        bands = adj_data["shortfall_bands"]

        weights = {}
        with open(os.path.join(self.workspace, "impression_weights.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                weights[row["platform"]] = float(row["weight"])

        # Read verification policy
        with open(os.path.join(self.workspace, "verification_policy.txt")) as f:
            _ = f.read()

        # Load venue visibility factors
        visibility = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "venue_report_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
            for venue_entry in data["venues"]:
                vname = venue_entry["venue_name"]
                for scr in venue_entry["screens"]:
                    visibility[(vname, scr["screen_id"])] = scr["visibility_factor"]

        # Load social verification
        verified_map = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "social_verification_batch_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    verified_map[int(row["feed_id"])] = row["verified"] == "True"

        # Step 2: Gather all events via tools (paginated)
        tool_call_count = 0

        all_events = []
        page = 1
        while True:
            result = self.tools["list_events"](page=page, page_size=20)
            tool_call_count += 1
            all_events.extend(result["events"])
            if page * 20 >= result["total"]:
                break
            page += 1

        event_map = {e["event_id"]: e for e in all_events}

        # Step 3: Gather all sponsors via tools (paginated)
        all_sponsors = []
        page = 1
        while True:
            result = self.tools["list_sponsors"](page=page, page_size=20)
            tool_call_count += 1
            all_sponsors.extend(result["sponsors"])
            if page * 20 >= result["total"]:
                break
            page += 1

        sponsor_map = {s["sponsor_id"]: s for s in all_sponsors}

        # Step 4: For each event, get entitlements
        all_entitlements = []
        for event in all_events:
            result = self.tools["get_entitlements"](event_id=event["event_id"])
            tool_call_count += 1
            all_entitlements.extend(result["entitlements"])

        # Deduplicate by entitlement_id
        seen_eids = set()
        unique_entitlements = []
        for ent in all_entitlements:
            if ent["entitlement_id"] not in seen_eids:
                seen_eids.add(ent["entitlement_id"])
                unique_entitlements.append(ent)

        # Step 5: For each entitlement, get delivery data
        results = []
        for ent in unique_entitlements:
            sid = ent["sponsor_id"]
            evid = ent["event_id"]
            atype = ent["asset_type"]
            contracted = ent["contracted_impressions"]
            penalty_rate = ent["penalty_rate_pct"]

            # Get sponsor tier
            sponsor = sponsor_map.get(sid)
            if not sponsor:
                sponsor_result = self.tools["get_sponsor"](sponsor_id=sid)
                tool_call_count += 1
                sponsor = sponsor_result
                sponsor_map[sid] = sponsor

            event = event_map.get(evid, {})

            delivered = 0.0

            if atype == "broadcast":
                log_result = self.tools["get_broadcast_logs"](
                    event_id=evid, sponsor_id=sid
                )
                tool_call_count += 1
                delivered = sum(l["raw_impressions"] for l in log_result["logs"])

            elif atype == "signage":
                sig_result = self.tools["get_signage_records"](
                    event_id=evid, sponsor_id=sid
                )
                tool_call_count += 1
                venue_name = event.get("venue", "")
                for rec in sig_result["records"]:
                    scr = rec["screen_id"]
                    vis = visibility.get((venue_name, scr), 1.0)
                    delivered += rec["actual_displays"] * vis

            elif atype == "social_media":
                sm_result = self.tools["get_social_media_feeds"](
                    event_id=evid, sponsor_id=sid
                )
                tool_call_count += 1
                for feed in sm_result["feeds"]:
                    plat_weight = weights.get(feed["platform"], 1.0)
                    is_verified = verified_map.get(feed["feed_id"], False)
                    ver_factor = 1.0 if is_verified else 0.5
                    delivered += feed["impressions"] * plat_weight * ver_factor

            delivered = round(delivered, 2)

            # Compliance
            tier = sponsor["tier"]
            threshold = thresholds.get(tier, 0.90)
            delivery_pct = delivered / contracted if contracted > 0 else 0.0
            compliant = delivery_pct >= threshold

            # Billing adjustment
            shortfall_impressions = max(0, contracted - delivered)
            shortfall_pct_val = (shortfall_impressions / contracted * 100) if contracted > 0 else 0.0

            adjustment_multiplier = 0.0
            for band in bands:
                if band["min_shortfall_pct"] <= shortfall_pct_val < band["max_shortfall_pct"]:
                    adjustment_multiplier = band["adjustment_multiplier"]
                    break
            if shortfall_pct_val >= bands[-1]["max_shortfall_pct"]:
                adjustment_multiplier = bands[-1]["adjustment_multiplier"]

            if compliant or shortfall_impressions == 0:
                billing_adj = 0.0
            else:
                billing_adj = round(
                    shortfall_impressions * (penalty_rate / 100.0) * adjustment_multiplier, 2
                )

            results.append({
                "entitlement_id": ent["entitlement_id"],
                "sponsor_name": sponsor["sponsor_name"],
                "sponsor_tier": tier,
                "event_name": event.get("event_name", ""),
                "asset_type": atype,
                "contracted_impressions": contracted,
                "delivered_impressions": delivered,
                "delivery_pct": round(delivery_pct * 100, 2),
                "compliant": compliant,
                "shortfall_impressions": round(shortfall_impressions, 2),
                "shortfall_pct": round(shortfall_pct_val, 2),
                "billing_adjustment": billing_adj,
            })

        # Step 6: Write compliance_report.csv
        report_path = os.path.join(self.workspace, "compliance_report.csv")
        fieldnames = [
            "entitlement_id", "sponsor_name", "sponsor_tier", "event_name",
            "asset_type", "contracted_impressions", "delivered_impressions",
            "delivery_pct", "compliant", "shortfall_impressions",
            "shortfall_pct", "billing_adjustment",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        # Step 7: Build action summary
        total_entitlements = len(results)
        non_compliant = sum(1 for r in results if not r["compliant"])
        compliant_count = total_entitlements - non_compliant
        total_billing = round(sum(r["billing_adjustment"] for r in results), 2)

        action = (
            f"Compliance report generated with {total_entitlements} entitlements evaluated. "
            f"{compliant_count} are compliant and {non_compliant} are non-compliant. "
            f"Total billing adjustment across all shortfalls: {total_billing:.2f}. "
            f"The detailed compliance_report.csv has been saved."
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made"

        return self.step(action)
