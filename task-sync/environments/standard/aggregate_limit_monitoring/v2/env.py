import sqlite3
import os
import json
import csv
import math
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

    # ──────────────────────────────────────────────────────────
    # TOOLS
    # ──────────────────────────────────────────────────────────

    @tool(
        description=(
            "Returns a paginated list of reinsurance treaties. "
            "Each entry contains treaty_id, treaty_name, cedent_name, "
            "line_of_business, currency, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of treaties per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_treaties(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT treaty_id, treaty_name, cedent_name, "
            "line_of_business, currency, status "
            "FROM treaties ORDER BY treaty_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM treaties").fetchone()[0]
        conn.close()
        return json.dumps({
            "page": page,
            "page_size": page_size,
            "total_treaties": total,
            "total_pages": math.ceil(total / page_size),
            "treaties": [dict(r) for r in rows],
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns full database record for a single treaty, including "
            "treaty_id, treaty_name, cedent_name, line_of_business, "
            "effective_date, expiry_date, currency, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "Treaty identifier, e.g. TR-0001.",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_treaty_info(self, treaty_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM treaties WHERE treaty_id = ?", (treaty_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Treaty {treaty_id} not found."}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns all loss advices for a given treaty, optionally "
            "filtered by event. Each record includes advice_id, treaty_id, "
            "event_id, gross_loss_amount, advice_date, and advice_sequence."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "Treaty identifier.",
                },
                "event_id": {
                    "type": "string",
                    "description": "Optional event identifier to filter by.",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_loss_advices(self, treaty_id: str, event_id: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if event_id:
            rows = conn.execute(
                "SELECT * FROM loss_advices "
                "WHERE treaty_id = ? AND event_id = ? "
                "ORDER BY event_id, advice_sequence",
                (treaty_id, event_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM loss_advices "
                "WHERE treaty_id = ? "
                "ORDER BY event_id, advice_sequence",
                (treaty_id,),
            ).fetchall()
        conn.close()
        return _envelope({"treaty_id": treaty_id, "advices": [dict(r) for r in rows]})

    @tool(
        description=(
            "Returns all inuring reinsurance recoveries for a given treaty. "
            "Each record includes recovery_id, treaty_id, event_id, "
            "recovery_amount, recovery_type, and effective_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "Treaty identifier.",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_inuring_recoveries(self, treaty_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM inuring_recoveries WHERE treaty_id = ? "
            "ORDER BY event_id",
            (treaty_id,),
        ).fetchall()
        conn.close()
        return json.dumps({"treaty_id": treaty_id, "recoveries": [dict(r) for r in rows]}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns details for a catastrophe event: event_id, event_name, "
            "peril_type, region, occurrence_date, reported_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event identifier, e.g. EVT-0001.",
                },
            },
            "required": ["event_id"],
        },
    )
    def get_event_details(self, event_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM catastrophe_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"error": f"Event {event_id} not found."}, ensure_ascii=False, default=str)
        return json.dumps(dict(row), ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns the industry loss index record for a catastrophe event: "
            "index_id, event_id, index_provider, index_value_usd_bn, "
            "publication_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event identifier.",
                },
            },
            "required": ["event_id"],
        },
    )
    def get_industry_loss_index(self, event_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM industry_loss_indices WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"No ILI found for event {event_id}."})
        return _envelope(dict(row))

    @tool(
        description=(
            "Returns a paginated list of catastrophe events. Each entry "
            "contains event_id, event_name, peril_type, region, "
            "occurrence_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of events per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_events(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event_id, event_name, peril_type, region, "
            "occurrence_date FROM catastrophe_events "
            "ORDER BY event_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM catastrophe_events"
        ).fetchone()[0]
        conn.close()
        return _envelope({
            "page": page,
            "page_size": page_size,
            "total_events": total,
            "total_pages": math.ceil(total / page_size),
            "events": [dict(r) for r in rows],
        })

    # ──────────────────────────────────────────────────────────
    # GROUND-TRUTH COMPUTATION (shared by step & verify)
    # ──────────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the full treaty dashboard from DB + workspace files."""
        import yaml

        ws = self.workspace

        # --- workspace files ---
        with open(os.path.join(ws, "treaty_terms.yaml")) as f:
            treaty_terms = yaml.safe_load(f)

        with open(os.path.join(ws, "ili_trigger_thresholds.json")) as f:
            ili_thresholds = json.load(f)

        ldf_map = {}
        with open(os.path.join(ws, "loss_development_factors.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ldf_map[row["development_stage"]] = float(row["factor"])

        with open(os.path.join(ws, "currency_conversion.json")) as f:
            fx_rates = json.load(f)

        disputed = set()
        with open(os.path.join(ws, "disputed_events.txt")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    disputed.add(line)

        # bulletin dev-stage map: advice_id -> development_stage
        dev_stage_map = {}
        for fname in os.listdir(ws):
            if fname.startswith("cedent_bulletin_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        dev_stage_map[row["advice_id"]] = row["development_stage"]

        # --- DB ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        treaties = conn.execute(
            "SELECT treaty_id, treaty_name, currency FROM treaties "
            "ORDER BY treaty_id"
        ).fetchall()

        ili_rows = conn.execute(
            "SELECT event_id, index_value_usd_bn FROM industry_loss_indices"
        ).fetchall()
        ili_map = {r["event_id"]: r["index_value_usd_bn"] for r in ili_rows}

        results = []
        for tr in treaties:
            tid = tr["treaty_id"]
            currency = tr["currency"]
            fx = fx_rates.get(currency, 1.0)
            terms = treaty_terms.get(tid, {})
            ttype = terms.get("treaty_type", "AGG_XL")
            attachment = terms.get("attachment_usd", 0.0)
            limit_usd = terms.get("limit_usd", 0.0)
            per_occ_ret = terms.get("per_occurrence_retention_usd", 0.0)

            # Loss advices: keep latest sequence per event
            advices = conn.execute(
                "SELECT advice_id, event_id, gross_loss_amount, advice_sequence "
                "FROM loss_advices WHERE treaty_id = ? "
                "ORDER BY event_id, advice_sequence",
                (tid,),
            ).fetchall()

            # Group by event, pick max sequence
            event_latest = {}
            for a in advices:
                eid = a["event_id"]
                if eid in disputed:
                    continue
                seq = a["advice_sequence"]
                if eid not in event_latest or seq > event_latest[eid]["seq"]:
                    event_latest[eid] = {
                        "seq": seq,
                        "advice_id": a["advice_id"],
                        "gross": a["gross_loss_amount"],
                    }

            # Inuring recoveries per event
            recoveries = conn.execute(
                "SELECT event_id, SUM(recovery_amount) as total "
                "FROM inuring_recoveries WHERE treaty_id = ? "
                "GROUP BY event_id",
                (tid,),
            ).fetchall()
            recovery_map = {r["event_id"]: r["total"] for r in recoveries}

            gross_total_usd = 0.0
            inuring_total_usd = 0.0
            qualified_net_losses = []  # per-event net losses that pass filters

            for eid, info in event_latest.items():
                # Develop gross loss
                dev_stage = dev_stage_map.get(info["advice_id"], "final")
                ldf = ldf_map.get(dev_stage, 1.0)
                developed_gross = info["gross"] * ldf

                # Convert to USD
                developed_gross_usd = developed_gross * fx

                # Inuring recovery (also in local currency)
                recovery_local = recovery_map.get(eid, 0.0)
                recovery_usd = recovery_local * fx

                net_usd = max(developed_gross_usd - recovery_usd, 0.0)

                gross_total_usd += developed_gross_usd
                inuring_total_usd += recovery_usd

                # Treaty-type filters
                if ttype == "ILW":
                    threshold = ili_thresholds.get(tid, 0.0)
                    ili_val = ili_map.get(eid, 0.0)
                    if ili_val < threshold:
                        continue  # event doesn't qualify

                if ttype == "CAT_XL":
                    if net_usd < per_occ_ret:
                        continue  # below per-occurrence retention

                qualified_net_losses.append(net_usd)

            aggregate_net = sum(qualified_net_losses)
            erosion = min(max(aggregate_net - attachment, 0.0), limit_usd)
            remaining = limit_usd - erosion
            exhaustion_pct = (
                round(erosion / limit_usd * 100, 2) if limit_usd > 0 else 0.0
            )

            if remaining <= 0.0:
                status = "EXHAUSTED"
            elif erosion > 0.0:
                status = "PARTIALLY_ERODED"
            else:
                status = "ACTIVE"

            results.append({
                "treaty_id": tid,
                "treaty_name": tr["treaty_name"],
                "treaty_type": ttype,
                "currency": currency,
                "attachment_usd": round(attachment, 2),
                "limit_usd": round(limit_usd, 2),
                "gross_incurred_usd": round(gross_total_usd, 2),
                "inuring_recoveries_usd": round(inuring_total_usd, 2),
                "net_incurred_usd": round(gross_total_usd - inuring_total_usd, 2),
                "erosion_usd": round(erosion, 2),
                "remaining_limit_usd": round(remaining, 2),
                "exhaustion_pct": exhaustion_pct,
                "status": status,
            })

        conn.close()
        return results

    # ──────────────────────────────────────────────────────────
    # STEP — evaluation
    # ──────────────────────────────────────────────────────────

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
        gt_map = {r["treaty_id"]: r for r in ground_truth}

        criteria = {}

        # ── Criterion 1: Dashboard file exists with correct columns (10 pts) ──
        dashboard_path = os.path.join(self.workspace, "treaty_dashboard.csv")
        expected_cols = [
            "treaty_id", "treaty_name", "treaty_type", "currency",
            "attachment_usd", "limit_usd", "gross_incurred_usd",
            "inuring_recoveries_usd", "net_incurred_usd", "erosion_usd",
            "remaining_limit_usd", "exhaustion_pct", "status",
        ]

        agent_rows = []
        file_ok = False
        cols_ok = False
        if os.path.exists(dashboard_path):
            try:
                with open(dashboard_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    cols_ok = all(c in actual_cols for c in expected_cols)
                    for row in reader:
                        cleaned = {k.strip(): v.strip() for k, v in row.items()}
                        agent_rows.append(cleaned)
                    file_ok = True
            except Exception:
                pass

        criteria["dashboard_structure"] = {
            "passed": file_ok and cols_ok,
            "score": 10 if (file_ok and cols_ok) else (5 if file_ok else 0),
            "max_score": 10,
            "reason": (
                None if (file_ok and cols_ok) else
                "Missing columns" if file_ok else "Dashboard file not found"
            ),
        }

        if not (file_ok and cols_ok):
            # Can't evaluate further without a valid dashboard
            total = criteria["dashboard_structure"]["score"]
            return total / 100.0, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": 100,
            }

        # ── Criterion 2: Correct treaty count (10 pts) ──
        agent_map = {}
        for r in agent_rows:
            agent_map[r.get("treaty_id", "")] = r

        count_ok = len(agent_map) == len(gt_map)
        criteria["treaty_count"] = {
            "passed": count_ok,
            "score": 10 if count_ok else 0,
            "max_score": 10,
            "reason": (
                None if count_ok else
                f"Expected {len(gt_map)} treaties, got {len(agent_map)}"
            ),
        }

        # Helper: per-treaty numeric comparison with tolerance
        def _score_numeric_field(field_name, max_pts, label):
            if not gt_map:
                return
            correct = 0
            for tid, gt in gt_map.items():
                if tid not in agent_map:
                    continue
                try:
                    agent_val = float(agent_map[tid].get(field_name, ""))
                    gt_val = float(gt[field_name])
                    if abs(agent_val - gt_val) < 0.02:
                        correct += 1
                except (ValueError, TypeError):
                    pass
            frac = correct / len(gt_map)
            earned = round(frac * max_pts, 2)
            criteria[label] = {
                "passed": correct == len(gt_map),
                "score": earned,
                "max_score": max_pts,
                "reason": (
                    None if correct == len(gt_map) else
                    f"{correct}/{len(gt_map)} treaties matched"
                ),
            }

        # ── Criterion 3: Gross incurred (20 pts) ──
        _score_numeric_field("gross_incurred_usd", 20, "gross_incurred")

        # ── Criterion 4: Inuring recoveries (10 pts) ──
        _score_numeric_field("inuring_recoveries_usd", 10, "inuring_recoveries")

        # ── Criterion 5: Erosion (20 pts) ──
        _score_numeric_field("erosion_usd", 20, "erosion")

        # ── Criterion 6: Remaining limit (15 pts) ──
        _score_numeric_field("remaining_limit_usd", 15, "remaining_limit")

        # ── Criterion 7: Status labels (15 pts) ──
        status_correct = 0
        for tid, gt in gt_map.items():
            if tid in agent_map:
                if agent_map[tid].get("status", "").strip().upper() == gt["status"]:
                    status_correct += 1
        status_frac = status_correct / len(gt_map) if gt_map else 0
        status_earned = round(status_frac * 15, 2)
        criteria["status_labels"] = {
            "passed": status_correct == len(gt_map),
            "score": status_earned,
            "max_score": 15,
            "reason": (
                None if status_correct == len(gt_map) else
                f"{status_correct}/{len(gt_map)} statuses matched"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ──────────────────────────────────────────────────────────
    # VERIFY — self-test proving solvability
    # ──────────────────────────────────────────────────────────

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
        import yaml

        ws = self.workspace
        call_count = 0

        def call_tool(name, **kwargs):
            nonlocal call_count
            call_count += 1
            return self.tools[name](**kwargs)

        # ── 1. Read workspace config files ──
        with open(os.path.join(ws, "treaty_terms.yaml")) as f:
            treaty_terms = yaml.safe_load(f)

        with open(os.path.join(ws, "ili_trigger_thresholds.json")) as f:
            ili_thresholds = json.load(f)

        ldf_map = {}
        with open(os.path.join(ws, "loss_development_factors.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ldf_map[row["development_stage"]] = float(row["factor"])

        with open(os.path.join(ws, "currency_conversion.json")) as f:
            fx_rates = json.load(f)

        disputed = set()
        with open(os.path.join(ws, "disputed_events.txt")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    disputed.add(line)

        # Read all cedent bulletins for development-stage lookup
        dev_stage_map = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("cedent_bulletin_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        dev_stage_map[row["advice_id"]] = row["development_stage"]

        # ── 2. List all treaties via tool ──
        all_treaties = []
        page = 1
        while True:
            resp = json.loads(call_tool("list_treaties", page=page, page_size=20))
            all_treaties.extend(resp["treaties"])
            if page >= resp["total_pages"]:
                break
            page += 1

        # ── 3. Collect ILI values for all events via tool ──
        # First list all events
        all_events = []
        page = 1
        while True:
            resp = json.loads(call_tool("list_events", page=page, page_size=20)["content"][0]["text"])
            all_events.extend(resp["events"])
            if page >= resp["total_pages"]:
                break
            page += 1

        ili_map = {}
        for evt in all_events:
            eid = evt["event_id"]
            resp = json.loads(call_tool("get_industry_loss_index", event_id=eid)["content"][0]["text"])
            if "error" not in resp:
                ili_map[eid] = resp["index_value_usd_bn"]

        # ── 4. For each treaty, compute dashboard row ──
        dashboard_rows = []

        for tr in all_treaties:
            tid = tr["treaty_id"]
            currency = tr["currency"]
            fx = fx_rates.get(currency, 1.0)
            terms = treaty_terms.get(tid, {})
            ttype = terms.get("treaty_type", "AGG_XL")
            attachment = terms.get("attachment_usd", 0.0)
            limit_usd = terms.get("limit_usd", 0.0)
            per_occ_ret = terms.get("per_occurrence_retention_usd", 0.0)

            # Get loss advices
            adv_resp = json.loads(call_tool("get_loss_advices", treaty_id=tid)["content"][0]["text"])
            advices = adv_resp["advices"]

            # Group by event, keep latest sequence
            event_latest = {}
            for a in advices:
                eid = a["event_id"]
                if eid in disputed:
                    continue
                seq = a["advice_sequence"]
                if eid not in event_latest or seq > event_latest[eid]["seq"]:
                    event_latest[eid] = {
                        "seq": seq,
                        "advice_id": a["advice_id"],
                        "gross": a["gross_loss_amount"],
                    }

            # Get inuring recoveries
            rec_resp = json.loads(call_tool("get_inuring_recoveries", treaty_id=tid))
            recovery_by_event = {}
            for r in rec_resp["recoveries"]:
                eid = r["event_id"]
                recovery_by_event[eid] = recovery_by_event.get(eid, 0.0) + r["recovery_amount"]

            gross_total_usd = 0.0
            inuring_total_usd = 0.0
            qualified_net_losses = []

            for eid, info in event_latest.items():
                dev_stage = dev_stage_map.get(info["advice_id"], "final")
                ldf = ldf_map.get(dev_stage, 1.0)
                developed_gross_usd = info["gross"] * ldf * fx
                recovery_usd = recovery_by_event.get(eid, 0.0) * fx
                net_usd = max(developed_gross_usd - recovery_usd, 0.0)

                gross_total_usd += developed_gross_usd
                inuring_total_usd += recovery_usd

                # Treaty-type filter
                if ttype == "ILW":
                    threshold = ili_thresholds.get(tid, 0.0)
                    if ili_map.get(eid, 0.0) < threshold:
                        continue

                if ttype == "CAT_XL":
                    if net_usd < per_occ_ret:
                        continue

                qualified_net_losses.append(net_usd)

            aggregate_net = sum(qualified_net_losses)
            erosion = min(max(aggregate_net - attachment, 0.0), limit_usd)
            remaining = limit_usd - erosion
            exhaustion_pct = (
                round(erosion / limit_usd * 100, 2) if limit_usd > 0 else 0.0
            )

            if remaining <= 0.0:
                status = "EXHAUSTED"
            elif erosion > 0.0:
                status = "PARTIALLY_ERODED"
            else:
                status = "ACTIVE"

            dashboard_rows.append({
                "treaty_id": tid,
                "treaty_name": tr["treaty_name"],
                "treaty_type": ttype,
                "currency": currency,
                "attachment_usd": round(attachment, 2),
                "limit_usd": round(limit_usd, 2),
                "gross_incurred_usd": round(gross_total_usd, 2),
                "inuring_recoveries_usd": round(inuring_total_usd, 2),
                "net_incurred_usd": round(gross_total_usd - inuring_total_usd, 2),
                "erosion_usd": round(erosion, 2),
                "remaining_limit_usd": round(remaining, 2),
                "exhaustion_pct": exhaustion_pct,
                "status": status,
            })

        # ── 5. Write dashboard CSV ──
        fieldnames = [
            "treaty_id", "treaty_name", "treaty_type", "currency",
            "attachment_usd", "limit_usd", "gross_incurred_usd",
            "inuring_recoveries_usd", "net_incurred_usd", "erosion_usd",
            "remaining_limit_usd", "exhaustion_pct", "status",
        ]
        dashboard_path = os.path.join(ws, "treaty_dashboard.csv")
        with open(dashboard_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in dashboard_rows:
                writer.writerow(row)

        # ── 6. Build action string ──
        n_exhausted = sum(1 for r in dashboard_rows if r["status"] == "EXHAUSTED")
        n_eroded = sum(
            1 for r in dashboard_rows if r["status"] == "PARTIALLY_ERODED"
        )
        n_active = sum(1 for r in dashboard_rows if r["status"] == "ACTIVE")

        action = (
            f"Treaty exhaustion dashboard saved to treaty_dashboard.csv. "
            f"Summary: {n_exhausted} treaties EXHAUSTED, "
            f"{n_eroded} PARTIALLY_ERODED, {n_active} ACTIVE."
        )

        assert call_count >= 15, (
            f"Tool-call floor not met: {call_count} calls < 15"
        )

        return self.step(action)
