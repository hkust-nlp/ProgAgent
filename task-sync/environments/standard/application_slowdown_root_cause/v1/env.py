#!/usr/bin/env python3
"""Environment for application slowdown root cause analysis task."""

import csv
import glob
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# --- Decorator (keep unchanged) ---
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


PAGE_SIZE = 20


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
    # Helper
    # ------------------------------------------------------------------
    def _query(self, sql: str, params: tuple = ()) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="List network devices with optional filtering. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "segment_id": {
                    "type": "string",
                    "description": "Filter by segment ID (e.g. 'SEG-01'). Omit to list all.",
                },
                "device_type": {
                    "type": "string",
                    "description": "Filter by device type: router, switch, firewall, load_balancer.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page returns up to 20 records.",
                },
            },
            "required": ["page"],
        },
    )
    def list_devices(self, page: int, segment_id: str = None, device_type: str = None) -> dict:
        conditions = []
        params = []
        if segment_id:
            conditions.append("segment_id = ?")
            params.append(segment_id)
        if device_type:
            conditions.append("device_type = ?")
            params.append(device_type)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        total = self._query(f"SELECT COUNT(*) as cnt FROM network_devices{where}", tuple(params))[0]["cnt"]
        offset = (page - 1) * PAGE_SIZE
        rows = self._query(
            f"SELECT * FROM network_devices{where} ORDER BY device_id LIMIT ? OFFSET ?",
            tuple(params) + (PAGE_SIZE, offset),
        )
        return {"devices": rows, "total": total, "page": page, "page_size": PAGE_SIZE}

    @tool(
        description="Query SNMP trap logs with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Filter by device ID (e.g. 'DEV-0001').",
                },
                "severity": {
                    "type": "string",
                    "description": "Filter by severity: critical, major, minor, informational.",
                },
                "trap_type": {
                    "type": "string",
                    "description": "Filter by trap type (e.g. 'linkDown', 'highCPU').",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page returns up to 20 records.",
                },
            },
            "required": ["page"],
        },
    )
    def query_snmp_traps(self, page: int, device_id: str = None, severity: str = None, trap_type: str = None) -> dict:
        conditions = []
        params = []
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if trap_type:
            conditions.append("trap_type = ?")
            params.append(trap_type)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        total = self._query(f"SELECT COUNT(*) as cnt FROM snmp_traps{where}", tuple(params))[0]["cnt"]
        offset = (page - 1) * PAGE_SIZE
        rows = self._query(
            f"SELECT * FROM snmp_traps{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            tuple(params) + (PAGE_SIZE, offset),
        )
        return {"traps": rows, "total": total, "page": page, "page_size": PAGE_SIZE}

    @tool(
        description="Query NetFlow session records with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Filter by device ID.",
                },
                "app_tag": {
                    "type": "string",
                    "description": "Filter by application tag (e.g. 'PaymentGateway').",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page returns up to 20 records.",
                },
            },
            "required": ["page"],
        },
    )
    def query_netflow_sessions(self, page: int, device_id: str = None, app_tag: str = None) -> dict:
        conditions = []
        params = []
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if app_tag:
            conditions.append("app_tag = ?")
            params.append(app_tag)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        total = self._query(f"SELECT COUNT(*) as cnt FROM netflow_sessions{where}", tuple(params))[0]["cnt"]
        offset = (page - 1) * PAGE_SIZE
        rows = self._query(
            f"SELECT * FROM netflow_sessions{where} ORDER BY start_time DESC LIMIT ? OFFSET ?",
            tuple(params) + (PAGE_SIZE, offset),
        )
        return {"sessions": rows, "total": total, "page": page, "page_size": PAGE_SIZE}

    @tool(
        description="Query APM (Application Performance Monitoring) trace records with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Filter by application name (e.g. 'PaymentGateway').",
                },
                "error_flag": {
                    "type": "integer",
                    "description": "Filter by error flag: 1 for errors only, 0 for non-errors.",
                },
                "min_response_time_ms": {
                    "type": "number",
                    "description": "Return only traces with response_time_ms >= this value.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page returns up to 20 records.",
                },
            },
            "required": ["page"],
        },
    )
    def query_apm_traces(self, page: int, app_name: str = None, error_flag: int = None, min_response_time_ms: float = None) -> dict:
        conditions = []
        params = []
        if app_name:
            conditions.append("app_name = ?")
            params.append(app_name)
        if error_flag is not None:
            conditions.append("error_flag = ?")
            params.append(error_flag)
        if min_response_time_ms is not None:
            conditions.append("response_time_ms >= ?")
            params.append(min_response_time_ms)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        total = self._query(f"SELECT COUNT(*) as cnt FROM apm_traces{where}", tuple(params))[0]["cnt"]
        offset = (page - 1) * PAGE_SIZE
        rows = self._query(
            f"SELECT * FROM apm_traces{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            tuple(params) + (PAGE_SIZE, offset),
        )
        return {"traces": rows, "total": total, "page": page, "page_size": PAGE_SIZE}

    @tool(
        description="Get detailed information about a specific network device by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "The device ID (e.g. 'DEV-0001').",
                },
            },
            "required": ["device_id"],
        },
    )
    def get_device_info(self, device_id: str) -> dict:
        rows = self._query("SELECT * FROM network_devices WHERE device_id = ?", (device_id,))
        if not rows:
            return {"error": f"Device {device_id} not found."}
        return rows[0]

    @tool(
        description="Query change management tickets with optional filters. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Filter by device ID.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by ticket status: completed, in_progress, rolled_back, failed.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page returns up to 20 records.",
                },
            },
            "required": ["page"],
        },
    )
    def query_change_tickets(self, page: int, device_id: str = None, status: str = None) -> dict:
        conditions = []
        params = []
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        total = self._query(f"SELECT COUNT(*) as cnt FROM change_tickets{where}", tuple(params))[0]["cnt"]
        offset = (page - 1) * PAGE_SIZE
        rows = self._query(
            f"SELECT * FROM change_tickets{where} ORDER BY scheduled_time DESC LIMIT ? OFFSET ?",
            tuple(params) + (PAGE_SIZE, offset),
        )
        return {"tickets": rows, "total": total, "page": page, "page_size": PAGE_SIZE}

    @tool(
        description="Get a summary of SNMP trap counts grouped by device, returning each device's trap count per severity level. Useful for identifying which devices have the most issues.",
        parameters={
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "description": "If provided, only count traps of this severity.",
                },
            },
            "required": [],
        },
    )
    def get_trap_summary_by_device(self, severity: str = None) -> dict:
        if severity:
            rows = self._query(
                "SELECT device_id, severity, COUNT(*) as count FROM snmp_traps WHERE severity = ? GROUP BY device_id, severity ORDER BY count DESC",
                (severity,),
            )
        else:
            rows = self._query(
                "SELECT device_id, severity, COUNT(*) as count FROM snmp_traps GROUP BY device_id, severity ORDER BY device_id, severity",
            )
        return {"summary": rows}

    @tool(
        description="Get NetFlow sessions that match specific source or destination IPs. Useful for tracing which network device carried traffic for a given server IP.",
        parameters={
            "type": "object",
            "properties": {
                "ip_address": {
                    "type": "string",
                    "description": "IP address to search for in src_ip or dst_ip fields.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
            },
            "required": ["ip_address", "page"],
        },
    )
    def search_netflow_by_ip(self, ip_address: str, page: int) -> dict:
        total = self._query(
            "SELECT COUNT(*) as cnt FROM netflow_sessions WHERE src_ip = ? OR dst_ip = ?",
            (ip_address, ip_address),
        )[0]["cnt"]
        offset = (page - 1) * PAGE_SIZE
        rows = self._query(
            "SELECT * FROM netflow_sessions WHERE src_ip = ? OR dst_ip = ? ORDER BY start_time DESC LIMIT ? OFFSET ?",
            (ip_address, ip_address, PAGE_SIZE, offset),
        )
        return {"sessions": rows, "total": total, "page": page, "page_size": PAGE_SIZE}

    @tool(
        description="Get the list of distinct application names that have NetFlow sessions traversing a specific device.",
        parameters={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "The device ID to look up.",
                },
            },
            "required": ["device_id"],
        },
    )
    def get_apps_on_device(self, device_id: str) -> dict:
        rows = self._query(
            "SELECT DISTINCT app_tag FROM netflow_sessions WHERE device_id = ? ORDER BY app_tag",
            (device_id,),
        )
        return {"device_id": device_id, "apps": [r["app_tag"] for r in rows]}

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------
    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        total_score = 0
        max_score = 0
        criteria = {}

        # --- Compute ground truth ---
        gt = self._compute_ground_truth()

        # Criterion 1: remediation_list.csv exists and has correct columns (15 pts)
        c1_max = 15
        max_score += c1_max
        csv_path = os.path.join(self.workspace, "remediation_list.csv")
        expected_cols = [
            "rank", "segment_name", "device_hostname", "root_cause",
            "priority_score", "affected_apps", "correlated_ticket_id",
            "evidence_summary", "recommended_action",
        ]
        csv_ok = False
        csv_rows = []
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                csv_rows = list(reader)
                actual_cols = list(reader.fieldnames) if reader.fieldnames else []
            if set(expected_cols) <= set(actual_cols):
                csv_ok = True
        if csv_ok:
            criteria["csv_format"] = {"passed": True, "score": c1_max, "max_score": c1_max}
            total_score += c1_max
        else:
            criteria["csv_format"] = {
                "passed": False,
                "score": 0,
                "max_score": c1_max,
                "reason": f"remediation_list.csv missing or wrong columns. Expected: {expected_cols}",
            }

        # Criterion 2: Correct set of problematic devices (20 pts)
        c2_max = 20
        max_score += c2_max
        gt_devices = set(gt["devices"].keys())
        submitted_devices = set()
        for row in csv_rows:
            hostname = row.get("device_hostname", "").strip()
            if hostname:
                submitted_devices.add(hostname)
        if gt_devices and submitted_devices:
            precision = len(gt_devices & submitted_devices) / len(submitted_devices) if submitted_devices else 0
            recall = len(gt_devices & submitted_devices) / len(gt_devices) if gt_devices else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            c2_score = round(c2_max * f1)
        else:
            c2_score = 0
        criteria["device_identification"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
            "reason": "" if c2_score == c2_max else f"Expected devices: {sorted(gt_devices)}, got: {sorted(submitted_devices)}",
        }
        total_score += c2_score

        # Criterion 3: Correct root cause classification (20 pts)
        c3_max = 20
        max_score += c3_max
        correct_rc = 0
        total_rc = len(gt["devices"])
        for row in csv_rows:
            hostname = row.get("device_hostname", "").strip()
            rc = row.get("root_cause", "").strip()
            if hostname in gt["devices"] and gt["devices"][hostname]["root_cause"] == rc:
                correct_rc += 1
        c3_score = round(c3_max * correct_rc / total_rc) if total_rc > 0 else 0
        criteria["root_cause_classification"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score == c3_max else f"Correct root causes: {correct_rc}/{total_rc}",
        }
        total_score += c3_score

        # Criterion 4: Priority scores match within tolerance (20 pts)
        c4_max = 20
        max_score += c4_max
        correct_ps = 0
        for row in csv_rows:
            hostname = row.get("device_hostname", "").strip()
            try:
                score_val = float(row.get("priority_score", "0"))
            except (ValueError, TypeError):
                score_val = -1
            if hostname in gt["devices"]:
                expected = gt["devices"][hostname]["priority_score"]
                if abs(score_val - expected) < 0.01:
                    correct_ps += 1
        c4_score = round(c4_max * correct_ps / total_rc) if total_rc > 0 else 0
        criteria["priority_scores"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score == c4_max else f"Correct priority scores: {correct_ps}/{total_rc}",
        }
        total_score += c4_score

        # Criterion 5: Correct ranking order (10 pts)
        c5_max = 10
        max_score += c5_max
        gt_order = sorted(
            gt["devices"].items(),
            key=lambda x: (-x[1]["priority_score"], x[1]["segment_name"], x[0]),
        )
        gt_hostnames_ordered = [h for h, _ in gt_order]
        submitted_hostnames_ordered = [r.get("device_hostname", "").strip() for r in csv_rows]
        if gt_hostnames_ordered == submitted_hostnames_ordered:
            c5_score = c5_max
        else:
            # partial: longest common prefix
            lcp = 0
            for a, b in zip(gt_hostnames_ordered, submitted_hostnames_ordered):
                if a == b:
                    lcp += 1
                else:
                    break
            c5_score = round(c5_max * lcp / len(gt_hostnames_ordered)) if gt_hostnames_ordered else 0
        criteria["ranking_order"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
            "reason": "" if c5_score == c5_max else f"Expected order: {gt_hostnames_ordered}, got: {submitted_hostnames_ordered}",
        }
        total_score += c5_score

        # Criterion 6: Correlated ticket IDs correct (15 pts)
        c6_max = 15
        max_score += c6_max
        correct_tickets = 0
        for row in csv_rows:
            hostname = row.get("device_hostname", "").strip()
            ticket = row.get("correlated_ticket_id", "").strip()
            if hostname in gt["devices"]:
                expected_ticket = gt["devices"][hostname]["correlated_ticket_id"]
                if ticket == expected_ticket:
                    correct_tickets += 1
        c6_score = round(c6_max * correct_tickets / total_rc) if total_rc > 0 else 0
        criteria["correlated_tickets"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else f"Correct tickets: {correct_tickets}/{total_rc}",
        }
        total_score += c6_score

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # Ground truth computation
    # ------------------------------------------------------------------
    def _compute_ground_truth(self) -> dict:
        """Compute the full ground truth for evaluation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load configs from workspace
        with open(os.path.join(self.workspace, "severity_scoring.yaml")) as f:
            sev_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "priority_formula.yaml")) as f:
            pf_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "sla_thresholds.json")) as f:
            sla_config = json.load(f)
        with open(os.path.join(self.workspace, "segment_definitions.json")) as f:
            seg_defs = json.load(f)

        sev_weights = sev_config["severity_weights"]
        crit_weights = pf_config["criticality_weights"]
        change_bonus_map = pf_config["change_correlation_bonus"]
        sla_tiers = sla_config["tiers"]
        app_tier_map = sla_config["app_tier_mapping"]
        seg_crit_map = {s["segment_id"]: s["criticality"] for s in seg_defs}

        # Load interface stats from workspace
        iface_stats = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "interface_stats_*.csv"))):
            import csv as csv_mod
            with open(fpath) as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    key = (row["device_id"], row["interface_name"])
                    iface_stats[key] = {
                        "packet_loss_rate": float(row["packet_loss_rate"]),
                        "crc_errors": int(row["crc_errors"]),
                        "input_errors": int(row["input_errors"]),
                        "output_drops": int(row["output_drops"]),
                        "avg_utilization_pct": float(row["avg_utilization_pct"]),
                    }

        # Step 1: Identify problematic devices (those with at least one critical or major trap)
        cur = conn.cursor()
        cur.execute("SELECT * FROM snmp_traps WHERE severity IN ('critical', 'major')")
        serious_traps = [dict(r) for r in cur.fetchall()]

        problem_device_ids = set(t["device_id"] for t in serious_traps)

        # Step 2: For each problem device, compute device_severity_score
        cur.execute("SELECT * FROM snmp_traps")
        all_traps = [dict(r) for r in cur.fetchall()]
        device_sev_scores = {}
        device_traps = {}
        for t in all_traps:
            did = t["device_id"]
            if did not in device_sev_scores:
                device_sev_scores[did] = 0.0
                device_traps[did] = []
            device_sev_scores[did] += sev_weights.get(t["severity"], 0)
            device_traps[did].append(t)

        # Step 3: Get device info
        cur.execute("SELECT * FROM network_devices")
        all_devices = {d["device_id"]: dict(d) for d in cur.fetchall()}

        # Step 4: For each problem device, find SLA-breaching apps
        cur.execute("SELECT * FROM netflow_sessions")
        all_netflow = [dict(r) for r in cur.fetchall()]
        device_apps = {}
        for nf in all_netflow:
            did = nf["device_id"]
            if did not in device_apps:
                device_apps[did] = set()
            device_apps[did].add(nf["app_tag"])

        # Check which apps are SLA-breaching
        cur.execute("SELECT * FROM apm_traces")
        all_apm = [dict(r) for r in cur.fetchall()]
        app_breach = {}  # app_name -> True if any trace breaches SLA
        for trace in all_apm:
            app = trace["app_name"]
            tier = app_tier_map.get(app, "bronze")
            threshold = sla_tiers[tier]["max_response_time_ms"]
            if trace["response_time_ms"] > threshold:
                app_breach[app] = True

        # Step 5: Compute max_sla_impact_factor per device
        device_sla_factor = {}
        device_affected_apps = {}
        for did in problem_device_ids:
            apps_on_dev = device_apps.get(did, set())
            breaching_apps = [a for a in apps_on_dev if app_breach.get(a, False)]
            if breaching_apps:
                max_factor = max(sla_tiers[app_tier_map.get(a, "bronze")]["sla_impact_factor"] for a in breaching_apps)
            else:
                max_factor = 1.0
            device_sla_factor[did] = max_factor
            device_affected_apps[did] = sorted(breaching_apps) if breaching_apps else []

        # Step 6: Change correlation (per change_correlation_rules.md):
        # consider tickets within the 72-hour window before 2025-03-15 08:00:00
        # whose status is one of the bonus map keys; pick highest bonus, tie-break
        # by most recent scheduled_time. If none qualify, ticket = "NONE".
        from datetime import datetime as _dt, timedelta as _td
        analysis_time = _dt(2025, 3, 15, 8, 0, 0)
        window_start = analysis_time - _td(hours=72)
        cur.execute("SELECT * FROM change_tickets")
        all_tickets = [dict(r) for r in cur.fetchall()]
        device_corr_ticket = {}
        device_change_bonus = {}
        for did in problem_device_ids:
            dev_tickets = []
            for t in all_tickets:
                if t["device_id"] != did:
                    continue
                if t["status"] not in change_bonus_map:
                    continue
                try:
                    st = _dt.strptime(t["scheduled_time"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if not (window_start <= st <= analysis_time):
                    continue
                dev_tickets.append((change_bonus_map[t["status"]], st, t))
            if dev_tickets:
                # Sort by (bonus desc, scheduled_time desc)
                dev_tickets.sort(key=lambda x: (-x[0], -x[1].timestamp()))
                best_bonus, _, best_ticket = dev_tickets[0]
                device_corr_ticket[did] = best_ticket["ticket_id"]
                device_change_bonus[did] = best_bonus
            else:
                device_corr_ticket[did] = "NONE"
                device_change_bonus[did] = 0.0

        # Step 7: Root cause classification
        rc_rules = pf_config["root_cause_classification"]["rules"]
        recommended_actions = pf_config["recommended_actions"]

        def classify_root_cause(did):
            traps = device_traps.get(did, [])
            trap_types = set(t["trap_type"] for t in traps)
            trap_severities = set(t["severity"] for t in traps)
            has_serious_trap = bool(trap_severities & {"critical", "major"})

            # Check change correlation first
            ticket_id = device_corr_ticket.get(did, "NONE")
            has_change_fail = False
            if ticket_id != "NONE":
                for t in all_tickets:
                    if t["ticket_id"] == ticket_id and t["status"] in ("rolled_back", "failed"):
                        has_change_fail = True
                        break

            if has_change_fail and has_serious_trap:
                return "Change-Induced Failure"

            # Check resource exhaustion
            for t in traps:
                if t["trap_type"] in ("highCPU", "highMemory") and t["value"] >= 90:
                    return "Resource Exhaustion"

            # Check interface degradation
            if trap_types & {"linkDown", "interfaceError"}:
                for t in traps:
                    if t["trap_type"] in ("linkDown", "interfaceError"):
                        key = (did, t["interface_name"])
                        stats = iface_stats.get(key)
                        if stats and stats["packet_loss_rate"] > 5.0:
                            return "Interface Degradation"

            # Check packet loss
            if "packetLoss" in trap_types:
                for t in traps:
                    if t["trap_type"] == "packetLoss":
                        key = (did, t["interface_name"])
                        stats = iface_stats.get(key)
                        if stats and stats["packet_loss_rate"] > 2.0:
                            return "Packet Loss"

            # Latency
            if "latencySpike" in trap_types:
                return "Latency Anomaly"

            # Routing
            if trap_types & {"bgpPeerDown", "ospfNeighborLoss"}:
                return "Routing Protocol Failure"

            return "General Degradation"

        # Step 8: Compute final scores and build result
        devices_result = {}
        for did in problem_device_ids:
            dev = all_devices[did]
            seg_id = dev["segment_id"]
            seg_crit = seg_crit_map.get(seg_id, "low")
            seg_name = None
            for s in seg_defs:
                if s["segment_id"] == seg_id:
                    seg_name = s["segment_name"]
                    break

            sev_score = device_sev_scores.get(did, 0)
            crit_w = crit_weights.get(seg_crit, 1.0)
            sla_f = device_sla_factor.get(did, 1.0)
            ch_bonus = device_change_bonus.get(did, 0.0)
            priority = round(sev_score * crit_w * sla_f * (1 + ch_bonus), 2)

            rc = classify_root_cause(did)
            rec_action = recommended_actions.get(rc, "Perform comprehensive device health check")

            hostname = dev["hostname"]
            devices_result[hostname] = {
                "device_id": did,
                "segment_name": seg_name,
                "root_cause": rc,
                "priority_score": priority,
                "affected_apps": ", ".join(device_affected_apps.get(did, [])),
                "correlated_ticket_id": device_corr_ticket.get(did, "NONE"),
                "recommended_action": rec_action,
            }

        conn.close()
        return {"devices": devices_result}

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------
    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod

        # Read config files
        with open(os.path.join(self.workspace, "severity_scoring.yaml")) as f:
            sev_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "priority_formula.yaml")) as f:
            pf_config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "sla_thresholds.json")) as f:
            sla_config = json.load(f)
        with open(os.path.join(self.workspace, "segment_definitions.json")) as f:
            seg_defs = json.load(f)

        sev_weights = sev_config["severity_weights"]
        crit_weights = pf_config["criticality_weights"]
        change_bonus_map = pf_config["change_correlation_bonus"]
        sla_tiers = sla_config["tiers"]
        app_tier_map = sla_config["app_tier_mapping"]
        seg_crit_map = {s["segment_id"]: s["criticality"] for s in seg_defs}
        seg_name_map = {s["segment_id"]: s["segment_name"] for s in seg_defs}

        rc_rules = pf_config["root_cause_classification"]["rules"]
        recommended_actions = pf_config["recommended_actions"]

        # Read interface stats from workspace files
        iface_stats = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "interface_stats_*.csv"))):
            with open(fpath) as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    key = (row["device_id"], row["interface_name"])
                    iface_stats[key] = {
                        "packet_loss_rate": float(row["packet_loss_rate"]),
                    }

        tool_call_count = 0

        # --- Step 1: Get trap summary to identify problem devices ---
        result = self.tools["get_trap_summary_by_device"](severity="critical")
        tool_call_count += 1
        critical_devs = {r["device_id"]: r["count"] for r in result["summary"]}

        result = self.tools["get_trap_summary_by_device"](severity="major")
        tool_call_count += 1
        major_devs = {r["device_id"]: r["count"] for r in result["summary"]}

        problem_device_ids = set(critical_devs.keys()) | set(major_devs.keys())

        # --- Step 2: For each problem device, get ALL traps to compute severity score ---
        device_all_traps = {}
        for did in sorted(problem_device_ids):
            page = 1
            traps = []
            while True:
                result = self.tools["query_snmp_traps"](device_id=did, page=page)
                tool_call_count += 1
                traps.extend(result["traps"])
                if page * PAGE_SIZE >= result["total"]:
                    break
                page += 1
            device_all_traps[did] = traps

        # Compute device_severity_score
        device_sev_scores = {}
        for did, traps in device_all_traps.items():
            device_sev_scores[did] = sum(sev_weights.get(t["severity"], 0) for t in traps)

        # --- Step 3: Get device info for each problem device ---
        device_info = {}
        for did in sorted(problem_device_ids):
            result = self.tools["get_device_info"](device_id=did)
            tool_call_count += 1
            device_info[did] = result

        # --- Step 4: Get apps on each problem device ---
        device_apps_map = {}
        for did in sorted(problem_device_ids):
            result = self.tools["get_apps_on_device"](device_id=did)
            tool_call_count += 1
            device_apps_map[did] = result["apps"]

        # --- Step 5: Check which apps are SLA-breaching ---
        app_names_to_check = set()
        for apps in device_apps_map.values():
            app_names_to_check.update(apps)

        app_breach = {}
        for app in sorted(app_names_to_check):
            tier = app_tier_map.get(app, "bronze")
            threshold = sla_tiers[tier]["max_response_time_ms"]
            page = 1
            is_breaching = False
            while True:
                result = self.tools["query_apm_traces"](app_name=app, min_response_time_ms=threshold + 0.01, page=page)
                tool_call_count += 1
                if result["total"] > 0:
                    is_breaching = True
                    break
                if page * PAGE_SIZE >= result["total"]:
                    break
                page += 1
            app_breach[app] = is_breaching

        # --- Step 6: Compute max_sla_impact_factor per device ---
        device_sla_factor = {}
        device_affected_apps = {}
        for did in problem_device_ids:
            apps_on_dev = device_apps_map.get(did, [])
            breaching_apps = [a for a in apps_on_dev if app_breach.get(a, False)]
            if breaching_apps:
                max_factor = max(sla_tiers[app_tier_map.get(a, "bronze")]["sla_impact_factor"] for a in breaching_apps)
            else:
                max_factor = 1.0
            device_sla_factor[did] = max_factor
            device_affected_apps[did] = sorted(breaching_apps)

        # --- Step 7: Get change tickets for each problem device ---
        from datetime import datetime as _dt, timedelta as _td
        analysis_time = _dt(2025, 3, 15, 8, 0, 0)
        window_start = analysis_time - _td(hours=72)
        device_corr_ticket = {}
        device_change_bonus = {}
        for did in sorted(problem_device_ids):
            page = 1
            all_tickets = []
            while True:
                result = self.tools["query_change_tickets"](device_id=did, page=page)
                tool_call_count += 1
                all_tickets.extend(result["tickets"])
                if page * PAGE_SIZE >= result["total"]:
                    break
                page += 1

            best_ticket = None
            best_bonus = 0.0
            for t in all_tickets:
                if t["status"] not in change_bonus_map:
                    continue
                try:
                    scheduled = _dt.strptime(t["scheduled_time"], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if not window_start <= scheduled <= analysis_time:
                    continue
                bonus = change_bonus_map[t["status"]]
                if best_ticket is None or bonus > best_bonus or (bonus == best_bonus and t["scheduled_time"] > best_ticket["scheduled_time"]):
                    best_bonus = bonus
                    best_ticket = t

            device_corr_ticket[did] = best_ticket["ticket_id"] if best_ticket is not None else "NONE"
            device_change_bonus[did] = best_bonus

        # --- Step 8: Classify root cause using traps + interface stats ---
        def classify_root_cause(did):
            traps = device_all_traps.get(did, [])
            trap_types = set(t["trap_type"] for t in traps)
            trap_severities = set(t["severity"] for t in traps)
            has_serious_trap = bool(trap_severities & {"critical", "major"})

            # Check change correlation
            ticket_id = device_corr_ticket.get(did, "NONE")
            has_change_fail = False
            if ticket_id != "NONE":
                # Find the ticket's status from the previously queried tickets
                for t_entry in device_all_traps_tickets.get(did, []):
                    if t_entry["ticket_id"] == ticket_id and t_entry["status"] in ("rolled_back", "failed"):
                        has_change_fail = True
                        break

            if has_change_fail and has_serious_trap:
                return "Change-Induced Failure"

            for t in traps:
                if t["trap_type"] in ("highCPU", "highMemory") and t["value"] >= 90:
                    return "Resource Exhaustion"

            if trap_types & {"linkDown", "interfaceError"}:
                for t in traps:
                    if t["trap_type"] in ("linkDown", "interfaceError"):
                        key = (did, t["interface_name"])
                        stats = iface_stats.get(key)
                        if stats and stats["packet_loss_rate"] > 5.0:
                            return "Interface Degradation"

            if "packetLoss" in trap_types:
                for t in traps:
                    if t["trap_type"] == "packetLoss":
                        key = (did, t["interface_name"])
                        stats = iface_stats.get(key)
                        if stats and stats["packet_loss_rate"] > 2.0:
                            return "Packet Loss"

            if "latencySpike" in trap_types:
                return "Latency Anomaly"

            if trap_types & {"bgpPeerDown", "ospfNeighborLoss"}:
                return "Routing Protocol Failure"

            return "General Degradation"

        # We need the ticket data for classification - store it
        # Re-query: we already have ticket data from step 7, let's store it properly
        device_all_traps_tickets = {}
        for did in sorted(problem_device_ids):
            page = 1
            tickets = []
            while True:
                result = self.tools["query_change_tickets"](device_id=did, page=page)
                tool_call_count += 1
                tickets.extend(result["tickets"])
                if page * PAGE_SIZE >= result["total"]:
                    break
                page += 1
            device_all_traps_tickets[did] = tickets

        # --- Step 9: Compute priority and build output ---
        output_rows = []
        for did in problem_device_ids:
            dev = device_info[did]
            seg_id = dev["segment_id"]
            seg_crit = seg_crit_map.get(seg_id, "low")
            seg_name = seg_name_map.get(seg_id, "Unknown")

            sev_score = device_sev_scores.get(did, 0)
            crit_w = crit_weights.get(seg_crit, 1.0)
            sla_f = device_sla_factor.get(did, 1.0)
            ch_bonus = device_change_bonus.get(did, 0.0)
            priority = round(sev_score * crit_w * sla_f * (1 + ch_bonus), 2)

            rc = classify_root_cause(did)
            rec_action = recommended_actions.get(rc, "Perform comprehensive device health check")

            output_rows.append({
                "rank": 0,  # filled after sort
                "segment_name": seg_name,
                "device_hostname": dev["hostname"],
                "root_cause": rc,
                "priority_score": priority,
                "affected_apps": ", ".join(device_affected_apps.get(did, [])),
                "correlated_ticket_id": device_corr_ticket.get(did, "NONE"),
                "evidence_summary": f"Severity score {sev_score}, segment {seg_name} ({seg_crit}), SLA factor {sla_f}, change bonus {ch_bonus}",
                "recommended_action": rec_action,
            })

        # Sort by priority_score descending, then segment_name ascending
        output_rows.sort(key=lambda x: (-x["priority_score"], x["segment_name"], x["device_hostname"]))
        for i, row in enumerate(output_rows):
            row["rank"] = i + 1

        # Write remediation_list.csv
        csv_path = os.path.join(self.workspace, "remediation_list.csv")
        fieldnames = [
            "rank", "segment_name", "device_hostname", "root_cause",
            "priority_score", "affected_apps", "correlated_ticket_id",
            "evidence_summary", "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(output_rows)

        # Build action string
        action_lines = ["Remediation List Summary:", ""]
        for row in output_rows:
            action_lines.append(
                f"#{row['rank']}: {row['device_hostname']} ({row['segment_name']}) - "
                f"{row['root_cause']} - Priority: {row['priority_score']} - "
                f"Affected: {row['affected_apps']} - Ticket: {row['correlated_ticket_id']}"
            )
        action_lines.append("")
        action_lines.append(f"Total problematic devices: {len(output_rows)}")
        action_lines.append(f"Total tool calls used: {tool_call_count}")
        action = "\n".join(action_lines)

        return self.step(action)
