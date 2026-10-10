"""
VoIP Call Drop Triage - Task Environment
"""

import csv
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


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

    # ---------- Tool methods ----------

    @tool(
        description="List all SIP servers with their status and load information.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_sip_servers(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM sip_servers").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description="Get SIP error logs for a specific server, optionally filtered by error code. Returns up to 50 results per call; use the offset parameter to paginate.",
        parameters={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "SIP server ID (e.g. SIP-001)"},
                "error_code": {"type": "string", "description": "Optional SIP error code filter (e.g. 503)"},
                "offset": {"type": "integer", "description": "Pagination offset, default 0"},
            },
            "required": ["server_id"],
        },
    )
    def get_sip_errors(self, server_id: str, error_code: str = None, offset: int = 0) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if error_code:
            rows = conn.execute(
                "SELECT * FROM sip_error_logs WHERE sip_server_id = ? AND error_code = ? ORDER BY timestamp LIMIT 50 OFFSET ?",
                (server_id, error_code, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM sip_error_logs WHERE sip_server_id = ? AND error_code = ?",
                (server_id, error_code),
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM sip_error_logs WHERE sip_server_id = ? ORDER BY timestamp LIMIT 50 OFFSET ?",
                (server_id, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM sip_error_logs WHERE sip_server_id = ?",
                (server_id,),
            ).fetchone()[0]
        conn.close()
        return {"total": total, "offset": offset, "results": [dict(r) for r in rows]}

    @tool(
        description="Get detailed information about a specific endpoint by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "endpoint_id": {"type": "string", "description": "Endpoint ID (e.g. EP-00001)"},
            },
            "required": ["endpoint_id"],
        },
    )
    def get_endpoint_info(self, endpoint_id: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM endpoints WHERE endpoint_id = ?", (endpoint_id,)).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Endpoint {endpoint_id} not found"}

    @tool(
        description="List network probes, optionally filtered by location. Returns probe IDs, names, locations, and status.",
        parameters={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Optional location filter"},
            },
            "required": [],
        },
    )
    def list_probes(self, location: str = None) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if location:
            rows = conn.execute("SELECT * FROM network_probes WHERE location = ?", (location,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM network_probes").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description="Get aggregated packet loss metrics for a specific probe. Returns per-endpoint averages of packet loss, jitter, latency, and MOS.",
        parameters={
            "type": "object",
            "properties": {
                "probe_id": {"type": "string", "description": "Probe ID (e.g. PRB-0001)"},
            },
            "required": ["probe_id"],
        },
    )
    def get_probe_metrics(self, probe_id: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Return per-endpoint aggregates
        rows = conn.execute(
            """SELECT endpoint_id,
                      COUNT(*) as sample_count,
                      ROUND(AVG(packet_loss_pct), 2) as avg_packet_loss,
                      ROUND(AVG(jitter_ms), 2) as avg_jitter,
                      ROUND(AVG(latency_ms), 2) as avg_latency,
                      ROUND(AVG(mos_score), 2) as avg_mos
               FROM packet_loss_metrics
               WHERE probe_id = ?
               GROUP BY endpoint_id
               ORDER BY avg_packet_loss DESC""",
            (probe_id,),
        ).fetchall()
        conn.close()
        return {"probe_id": probe_id, "endpoint_metrics": [dict(r) for r in rows]}

    @tool(
        description="Get wireless access point details by AP ID, including health score and connected client count.",
        parameters={
            "type": "object",
            "properties": {
                "ap_id": {"type": "string", "description": "Access point ID (e.g. AP-0001)"},
            },
            "required": ["ap_id"],
        },
    )
    def get_ap_details(self, ap_id: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM wireless_aps WHERE ap_id = ?", (ap_id,)).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"AP {ap_id} not found"}

    @tool(
        description="Get call records for a specific endpoint (as caller or callee). Returns up to 50 records per call; use offset to paginate. Optionally filter by call status.",
        parameters={
            "type": "object",
            "properties": {
                "endpoint_id": {"type": "string", "description": "Endpoint ID"},
                "status_filter": {"type": "string", "description": "Optional status filter: completed, dropped, failed, busy"},
                "offset": {"type": "integer", "description": "Pagination offset, default 0"},
            },
            "required": ["endpoint_id"],
        },
    )
    def get_call_records(self, endpoint_id: str, status_filter: str = None, offset: int = 0) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        base_q = "FROM call_records WHERE (caller_endpoint_id = ? OR callee_endpoint_id = ?)"
        params: list = [endpoint_id, endpoint_id]
        if status_filter:
            base_q += " AND status = ?"
            params.append(status_filter)
        total = conn.execute(f"SELECT COUNT(*) {base_q}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * {base_q} ORDER BY start_time LIMIT 50 OFFSET ?",
            params + [offset],
        ).fetchall()
        conn.close()
        return {"total": total, "offset": offset, "results": [dict(r) for r in rows]}

    @tool(
        description="Get SIP error summary for a specific endpoint across all servers. Returns error counts grouped by error code.",
        parameters={
            "type": "object",
            "properties": {
                "endpoint_id": {"type": "string", "description": "Endpoint ID"},
            },
            "required": ["endpoint_id"],
        },
    )
    def get_endpoint_sip_errors(self, endpoint_id: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT error_code, error_message, COUNT(*) as count, sip_server_id
               FROM sip_error_logs WHERE endpoint_id = ?
               GROUP BY error_code, sip_server_id
               ORDER BY count DESC""",
            (endpoint_id,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM sip_error_logs WHERE endpoint_id = ?",
            (endpoint_id,),
        ).fetchone()[0]
        conn.close()
        return {
            "endpoint_id": endpoint_id,
            "total_errors": total,
            "by_code_and_server": [
                {"error_code": r[0], "error_message": r[1], "count": r[2], "server_id": r[3]}
                for r in rows
            ],
        }

    @tool(
        description="Search endpoints by firmware version. Returns a list of endpoint IDs running the specified firmware.",
        parameters={
            "type": "object",
            "properties": {
                "firmware_version": {"type": "string", "description": "Firmware version string (e.g. 4.1.0)"},
            },
            "required": ["firmware_version"],
        },
    )
    def search_endpoints_by_firmware(self, firmware_version: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT endpoint_id, model, location, ap_id, sip_server_id FROM endpoints WHERE firmware_version = ?",
            (firmware_version,),
        ).fetchall()
        conn.close()
        return {
            "firmware_version": firmware_version,
            "count": len(rows),
            "endpoints": [
                {"endpoint_id": r[0], "model": r[1], "location": r[2], "ap_id": r[3], "sip_server_id": r[4]}
                for r in rows
            ],
        }

    @tool(
        description="Get dropped call statistics grouped by location. Returns location, drop count, and total calls for each location.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_drop_stats_by_location(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT e.location,
                      SUM(CASE WHEN c.status = 'dropped' THEN 1 ELSE 0 END) as drop_count,
                      COUNT(*) as total_calls,
                      ROUND(100.0 * SUM(CASE WHEN c.status = 'dropped' THEN 1 ELSE 0 END) / COUNT(*), 2) as drop_rate_pct
               FROM call_records c
               JOIN endpoints e ON c.caller_endpoint_id = e.endpoint_id
               GROUP BY e.location
               ORDER BY drop_rate_pct DESC""",
        ).fetchall()
        conn.close()
        return [
            {"location": r[0], "drop_count": r[1], "total_calls": r[2], "drop_rate_pct": r[3]}
            for r in rows
        ]

    # ---------- step ----------

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load config from workspace
        with open(os.path.join(self.workspace, "thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "firmware_compatibility.json")) as f:
            fw_compat = json.load(f)

        # Compute ground truth
        gt_faults = self._compute_ground_truth(conn, thresholds, fw_compat)
        conn.close()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: fault_localization_report.csv exists and has correct structure (15 pts) ---
        c1_max = 15
        c1_score = 0
        report_path = os.path.join(self.workspace, "fault_localization_report.csv")
        report_rows = []
        if os.path.exists(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    report_rows = list(reader)
                required_cols = {"endpoint_id", "severity", "fault_source", "avg_packet_loss", "avg_jitter", "avg_mos", "sip_error_count", "firmware_version", "ap_health_score", "location"}
                actual_cols = set(reader.fieldnames or [])
                if required_cols.issubset(actual_cols) and len(report_rows) > 0:
                    c1_score = c1_max
                elif len(report_rows) > 0:
                    c1_score = 5
            except Exception:
                pass
        eval_criteria["report_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
            "reason": "" if c1_score == c1_max else "fault_localization_report.csv missing or has wrong columns",
        }
        total_score += c1_score
        max_score += c1_max

        # --- Criterion 2: Correct endpoint identification (25 pts) ---
        c2_max = 25
        c2_score = 0
        gt_ep_ids = set(gt_faults.keys())
        report_ep_ids = set()
        for row in report_rows:
            eid = row.get("endpoint_id", "").strip()
            if eid:
                report_ep_ids.add(eid)
        if gt_ep_ids:
            precision = len(report_ep_ids & gt_ep_ids) / max(len(report_ep_ids), 1)
            recall = len(report_ep_ids & gt_ep_ids) / len(gt_ep_ids)
            if precision + recall > 0:
                f1 = 2 * precision * recall / (precision + recall)
            else:
                f1 = 0
            c2_score = round(c2_max * f1)
        eval_criteria["endpoint_identification"] = {
            "passed": c2_score >= c2_max * 0.8,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score >= c2_max * 0.8 else f"Expected {len(gt_ep_ids)} faulty endpoints, report has {len(report_ep_ids)} (overlap: {len(report_ep_ids & gt_ep_ids)})",
        }
        total_score += c2_score
        max_score += c2_max

        # --- Criterion 3: Severity classification accuracy (20 pts) ---
        c3_max = 20
        c3_correct = 0
        c3_total = 0
        report_map = {}
        for row in report_rows:
            eid = row.get("endpoint_id", "").strip()
            if eid:
                report_map[eid] = row
        for eid, gt in gt_faults.items():
            if eid in report_map:
                c3_total += 1
                if report_map[eid].get("severity", "").strip().upper() == gt["severity"].upper():
                    c3_correct += 1
        if c3_total > 0:
            c3_score = round(c3_max * c3_correct / c3_total)
        else:
            c3_score = 0
        eval_criteria["severity_accuracy"] = {
            "passed": c3_total > 0 and c3_correct / max(c3_total, 1) >= 0.8,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score >= c3_max * 0.8 else f"Severity correct: {c3_correct}/{c3_total}",
        }
        total_score += c3_score
        max_score += c3_max

        # --- Criterion 4: Fault source attribution accuracy (20 pts) ---
        c4_max = 20
        c4_correct = 0
        c4_total = 0
        for eid, gt in gt_faults.items():
            if eid in report_map:
                c4_total += 1
                if report_map[eid].get("fault_source", "").strip().lower() == gt["fault_source"].lower():
                    c4_correct += 1
        if c4_total > 0:
            c4_score = round(c4_max * c4_correct / c4_total)
        else:
            c4_score = 0
        eval_criteria["fault_source_accuracy"] = {
            "passed": c4_total > 0 and c4_correct / max(c4_total, 1) >= 0.8,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score >= c4_max * 0.8 else f"Fault source correct: {c4_correct}/{c4_total}",
        }
        total_score += c4_score
        max_score += c4_max

        # --- Criterion 5: Response summary completeness (10 pts) ---
        c5_max = 10
        c5_score = 0
        action_lower = action.lower()
        required_phrases = ["critical", "high", "network", "firmware"]
        found = sum(1 for p in required_phrases if p in action_lower)
        c5_score = round(c5_max * found / len(required_phrases))
        eval_criteria["response_summary"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score == c5_max else "Response missing key summary terms",
        }
        total_score += c5_score
        max_score += c5_max

        # --- Criterion 6: Numeric precision in report (10 pts) ---
        c6_max = 10
        c6_score = 0
        precision_ok = 0
        precision_total = 0
        for eid, gt in gt_faults.items():
            if eid in report_map:
                row = report_map[eid]
                for field in ["avg_packet_loss", "avg_jitter", "avg_mos"]:
                    try:
                        reported = float(row.get(field, ""))
                        expected = float(gt[field])
                        precision_total += 1
                        if abs(reported - expected) < 0.1:
                            precision_ok += 1
                    except (ValueError, KeyError):
                        precision_total += 1
        if precision_total > 0:
            c6_score = round(c6_max * precision_ok / precision_total)
        eval_criteria["numeric_precision"] = {
            "passed": precision_total > 0 and precision_ok / max(precision_total, 1) >= 0.8,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score >= c6_max * 0.8 else f"Numeric precision: {precision_ok}/{precision_total} within tolerance",
        }
        total_score += c6_score
        max_score += c6_max

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    def _compute_ground_truth(self, conn, thresholds, fw_compat):
        """Compute the full set of faulty endpoints and their classifications."""
        # Get per-endpoint aggregated metrics across all probes
        ep_metrics = {}
        rows = conn.execute(
            """SELECT endpoint_id,
                      ROUND(AVG(packet_loss_pct), 2) as avg_pl,
                      ROUND(AVG(jitter_ms), 2) as avg_jitter,
                      ROUND(AVG(latency_ms), 2) as avg_latency,
                      ROUND(AVG(mos_score), 2) as avg_mos
               FROM packet_loss_metrics
               GROUP BY endpoint_id"""
        ).fetchall()
        for r in rows:
            ep_metrics[r["endpoint_id"]] = {
                "avg_packet_loss": r["avg_pl"],
                "avg_jitter": r["avg_jitter"],
                "avg_latency": r["avg_latency"],
                "avg_mos": r["avg_mos"],
            }

        # Get per-endpoint SIP error counts and codes
        ep_sip = {}
        rows = conn.execute(
            """SELECT endpoint_id, COUNT(*) as cnt,
                      GROUP_CONCAT(DISTINCT error_code) as codes
               FROM sip_error_logs GROUP BY endpoint_id"""
        ).fetchall()
        for r in rows:
            ep_sip[r["endpoint_id"]] = {
                "sip_error_count": r["cnt"],
                "error_codes": set(r["codes"].split(",")) if r["codes"] else set(),
            }

        # Get endpoint info
        ep_info = {}
        rows = conn.execute("SELECT * FROM endpoints").fetchall()
        for r in rows:
            ep_info[r["endpoint_id"]] = dict(r)

        # Get AP info
        ap_info = {}
        rows = conn.execute("SELECT * FROM wireless_aps").fetchall()
        for r in rows:
            ap_info[r["ap_id"]] = dict(r)

        # Get SIP server info
        sip_info = {}
        rows = conn.execute("SELECT * FROM sip_servers").fetchall()
        for r in rows:
            sip_info[r["server_id"]] = dict(r)

        # Classify each endpoint
        buggy = set(fw_compat.get("known_buggy_versions", []))
        eol = set(fw_compat.get("eol_versions", []))
        pl_crit = thresholds["packet_loss_critical_pct"]
        pl_warn = thresholds["packet_loss_warning_pct"]
        jitter_crit = thresholds["jitter_critical_ms"]
        mos_warn = thresholds["mos_warning"]
        ap_crit = thresholds["ap_health_critical"]
        ap_warn = thresholds["ap_health_warning"]
        srv_load_crit = thresholds["server_load_critical_pct"]

        faults = {}
        for eid, info in ep_info.items():
            metrics = ep_metrics.get(eid, {"avg_packet_loss": 0, "avg_jitter": 0, "avg_latency": 0, "avg_mos": 5.0})
            sip = ep_sip.get(eid, {"sip_error_count": 0, "error_codes": set()})
            fw = info["firmware_version"]
            ap_id = info["ap_id"]
            ap = ap_info.get(ap_id, {"client_health_score": 100})
            ap_health = ap["client_health_score"]
            sip_srv = sip_info.get(info["sip_server_id"], {"current_load_pct": 0})

            avg_pl = metrics["avg_packet_loss"]
            avg_jitter = metrics["avg_jitter"]
            avg_mos = metrics["avg_mos"]

            severity = None
            fault_source = None

            # Check CRITICAL conditions
            if avg_pl > pl_crit and (sip["error_codes"] & {"503", "500"}):
                severity = "CRITICAL"
                fault_source = "network"
            elif ap_health < ap_crit and avg_pl > pl_warn:
                severity = "CRITICAL"
                fault_source = "wireless"
            elif fw in buggy and sip["sip_error_count"] > 3:
                severity = "CRITICAL"
                fault_source = "firmware"

            # Check HIGH conditions
            if severity is None:
                if avg_pl > pl_warn and avg_pl <= pl_crit and avg_jitter > jitter_crit:
                    severity = "HIGH"
                    fault_source = "network"
                elif sip_srv["current_load_pct"] > srv_load_crit and sip["sip_error_count"] >= 2:
                    severity = "HIGH"
                    fault_source = "sip_server"
                elif fw in eol:
                    severity = "HIGH"
                    fault_source = "firmware"

            # Check MEDIUM conditions
            if severity is None:
                if avg_pl > pl_warn:
                    severity = "MEDIUM"
                    fault_source = "network"
                elif avg_mos < mos_warn:
                    severity = "MEDIUM"
                    fault_source = "network"
                elif ap_health < ap_warn and ap_health >= ap_crit:
                    severity = "MEDIUM"
                    fault_source = "wireless"

            if severity is not None:
                faults[eid] = {
                    "severity": severity,
                    "fault_source": fault_source,
                    "avg_packet_loss": metrics["avg_packet_loss"],
                    "avg_jitter": metrics["avg_jitter"],
                    "avg_mos": metrics["avg_mos"],
                    "avg_latency": metrics["avg_latency"],
                    "sip_error_count": sip["sip_error_count"],
                    "firmware_version": fw,
                    "ap_health_score": ap_health,
                    "location": info["location"],
                    "ap_id": ap_id,
                }

        return faults

    # ---------- verify ----------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Read config files from workspace
        with open(os.path.join(self.workspace, "thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "firmware_compatibility.json")) as f:
            fw_compat = json.load(f)
        with open(os.path.join(self.workspace, "severity_rules.md")) as f:
            _rules_text = f.read()

        buggy = set(fw_compat.get("known_buggy_versions", []))
        eol = set(fw_compat.get("eol_versions", []))
        pl_crit = thresholds["packet_loss_critical_pct"]
        pl_warn = thresholds["packet_loss_warning_pct"]
        jitter_crit = thresholds["jitter_critical_ms"]
        mos_warn = thresholds["mos_warning"]
        ap_crit = thresholds["ap_health_critical"]
        ap_warn = thresholds["ap_health_warning"]
        srv_load_crit = thresholds["server_load_critical_pct"]

        # Step 2: List SIP servers
        sip_servers = call_tool("list_sip_servers")
        sip_info = {s["server_id"]: s for s in sip_servers}

        # Step 3: List all probes
        probes = call_tool("list_probes")

        # Step 4: Get probe metrics for each probe to find endpoints with issues
        ep_metrics_agg = {}  # endpoint_id -> list of metric dicts
        for probe in probes:
            result = call_tool("get_probe_metrics", probe_id=probe["probe_id"])
            for em in result.get("endpoint_metrics", []):
                eid = em["endpoint_id"]
                if eid not in ep_metrics_agg:
                    ep_metrics_agg[eid] = []
                ep_metrics_agg[eid].append(em)

        # Aggregate across probes per endpoint
        ep_avg = {}
        for eid, mlist in ep_metrics_agg.items():
            total_samples = sum(m["sample_count"] for m in mlist)
            if total_samples == 0:
                continue
            avg_pl = sum(m["avg_packet_loss"] * m["sample_count"] for m in mlist) / total_samples
            avg_jit = sum(m["avg_jitter"] * m["sample_count"] for m in mlist) / total_samples
            avg_mos = sum(m["avg_mos"] * m["sample_count"] for m in mlist) / total_samples
            avg_lat = sum(m.get("avg_latency", 0) * m["sample_count"] for m in mlist) / total_samples
            ep_avg[eid] = {
                "avg_packet_loss": round(avg_pl, 2),
                "avg_jitter": round(avg_jit, 2),
                "avg_mos": round(avg_mos, 2),
                "avg_latency": round(avg_lat, 2),
            }

        # Step 5: For all endpoints, get SIP errors and endpoint info
        # First identify candidate endpoints (those with any metric concern)
        all_ep_ids = set(ep_avg.keys())

        ep_sip = {}
        ep_info_map = {}
        for eid in sorted(all_ep_ids):
            info = call_tool("get_endpoint_info", endpoint_id=eid)
            ep_info_map[eid] = info
            sip_result = call_tool("get_endpoint_sip_errors", endpoint_id=eid)
            ep_sip[eid] = sip_result

        # Step 6: Get AP details for all unique APs
        unique_aps = set()
        for eid, info in ep_info_map.items():
            ap_id = info.get("ap_id")
            if ap_id:
                unique_aps.add(ap_id)

        ap_details = {}
        for ap_id in sorted(unique_aps):
            ap_details[ap_id] = call_tool("get_ap_details", ap_id=ap_id)

        # Step 7: Classify faults
        faults = {}
        for eid in sorted(all_ep_ids):
            metrics = ep_avg.get(eid, {"avg_packet_loss": 0, "avg_jitter": 0, "avg_mos": 5.0, "avg_latency": 0})
            sip = ep_sip.get(eid, {"total_errors": 0, "by_code_and_server": []})
            info = ep_info_map.get(eid, {})
            fw = info.get("firmware_version", "")
            ap_id = info.get("ap_id", "")
            ap = ap_details.get(ap_id, {"client_health_score": 100})
            ap_health = ap.get("client_health_score", 100)
            sip_srv_id = info.get("sip_server_id", "")
            sip_srv = sip_info.get(sip_srv_id, {"current_load_pct": 0})

            avg_pl = metrics["avg_packet_loss"]
            avg_jitter = metrics["avg_jitter"]
            avg_mos = metrics["avg_mos"]
            sip_err_count = sip.get("total_errors", 0)
            error_codes = set()
            for entry in sip.get("by_code_and_server", []):
                error_codes.add(entry["error_code"])

            severity = None
            fault_source = None

            # CRITICAL
            if avg_pl > pl_crit and (error_codes & {"503", "500"}):
                severity = "CRITICAL"
                fault_source = "network"
            elif ap_health < ap_crit and avg_pl > pl_warn:
                severity = "CRITICAL"
                fault_source = "wireless"
            elif fw in buggy and sip_err_count > 3:
                severity = "CRITICAL"
                fault_source = "firmware"

            # HIGH
            if severity is None:
                if avg_pl > pl_warn and avg_pl <= pl_crit and avg_jitter > jitter_crit:
                    severity = "HIGH"
                    fault_source = "network"
                elif sip_srv["current_load_pct"] > srv_load_crit and sip_err_count >= 2:
                    severity = "HIGH"
                    fault_source = "sip_server"
                elif fw in eol:
                    severity = "HIGH"
                    fault_source = "firmware"

            # MEDIUM
            if severity is None:
                if avg_pl > pl_warn:
                    severity = "MEDIUM"
                    fault_source = "network"
                elif avg_mos < mos_warn:
                    severity = "MEDIUM"
                    fault_source = "network"
                elif ap_health < ap_warn and ap_health >= ap_crit:
                    severity = "MEDIUM"
                    fault_source = "wireless"

            if severity is not None:
                faults[eid] = {
                    "endpoint_id": eid,
                    "severity": severity,
                    "fault_source": fault_source,
                    "avg_packet_loss": metrics["avg_packet_loss"],
                    "avg_jitter": metrics["avg_jitter"],
                    "avg_mos": metrics["avg_mos"],
                    "sip_error_count": sip_err_count,
                    "firmware_version": fw,
                    "ap_health_score": ap_health,
                    "location": info.get("location", ""),
                }

        # Step 8: Write fault_localization_report.csv
        report_path = os.path.join(self.workspace, "fault_localization_report.csv")
        fieldnames = [
            "endpoint_id", "severity", "fault_source", "avg_packet_loss",
            "avg_jitter", "avg_mos", "sip_error_count", "firmware_version",
            "ap_health_score", "location",
        ]
        sorted_faults = sorted(
            faults.values(),
            key=lambda x: ({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(x["severity"], 4), x["endpoint_id"]),
        )
        with open(report_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for fault in sorted_faults:
                writer.writerow(fault)

        # Step 9: Build summary action
        sev_counts = {}
        source_counts = {}
        for fault in sorted_faults:
            sev = fault["severity"]
            src = fault["fault_source"]
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            source_counts[src] = source_counts.get(src, 0) + 1

        summary_parts = ["Fault Localization Report Summary:"]
        summary_parts.append(f"Total faulty endpoints identified: {len(sorted_faults)}")
        summary_parts.append("Severity breakdown: " + ", ".join(f"{k}: {v}" for k, v in sorted(sev_counts.items())))
        summary_parts.append("Fault source breakdown: " + ", ".join(f"{k}: {v}" for k, v in sorted(source_counts.items())))
        summary_parts.append("The report has been saved to fault_localization_report.csv with columns: endpoint_id, severity, fault_source, avg_packet_loss, avg_jitter, avg_mos, sip_error_count, firmware_version, ap_health_score, location.")
        summary_parts.append("Critical and high severity faults require immediate attention from the network engineering team.")

        action = "\n".join(summary_parts)

        print(f"[verify] Tool calls made: {tool_call_count}")
        return self.step(action)
