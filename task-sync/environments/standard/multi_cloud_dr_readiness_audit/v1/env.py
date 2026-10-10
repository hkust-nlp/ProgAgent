#!/usr/bin/env python3
"""Environment for disaster recovery compliance audit task."""
import csv
import json
import math
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np
import yaml


# ── Tool decorator ───────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── Task environment ─────────────────────────────────────────────────────────

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

    # ── Tools ────────────────────────────────────────────────────────────────

    @tool(
        description="List all cloud infrastructure providers in the monitoring system. Returns each provider's name and its associated service tier distribution.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_providers(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT provider FROM dr_services ORDER BY provider"
        ).fetchall()
        providers = []
        for (pname,) in rows:
            tier_counts = {}
            for (tier, cnt) in conn.execute(
                "SELECT tier, COUNT(*) FROM dr_services WHERE provider=? GROUP BY tier",
                (pname,),
            ).fetchall():
                tier_counts[tier] = cnt
            total = sum(tier_counts.values())
            providers.append({"name": pname, "total_services": total, "tier_distribution": tier_counts})
        conn.close()
        return {"providers": providers}

    @tool(
        description="List all regions for a given provider, including whether each region is used as a primary deployment region and the number of services deployed there.",
        parameters={
            "type": "object",
            "properties": {
                "provider_name": {
                    "type": "string",
                    "description": "The name of the cloud provider.",
                },
            },
            "required": ["provider_name"],
        },
    )
    def list_regions(self, provider_name: str):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT region, COUNT(*), SUM(is_primary) FROM dr_services WHERE provider=? GROUP BY region ORDER BY region",
            (provider_name,),
        ).fetchall()
        regions = []
        for region, cnt, primary_cnt in rows:
            regions.append({
                "region_name": region,
                "service_count": cnt,
                "primary_services": primary_cnt,
            })
        conn.close()
        return {"provider": provider_name, "regions": regions}

    @tool(
        description="Get aggregated database replication lag metrics for all services in a specific provider-region combination. Returns per-service average lag, max lag, P95 lag, measurement count, and latest status. Results are paginated.",
        parameters={
            "type": "object",
            "properties": {
                "provider_name": {"type": "string", "description": "Provider name."},
                "region_name": {"type": "string", "description": "Region name."},
                "page": {"type": "integer", "description": "Page number (1-based, default 1)."},
                "page_size": {"type": "integer", "description": "Results per page (default 20)."},
            },
            "required": ["provider_name", "region_name"],
        },
    )
    def get_replication_report(self, provider_name: str, region_name: str, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(DISTINCT s.id) FROM dr_services s INNER JOIN replication_metrics r ON s.id=r.service_id WHERE s.provider=? AND s.region=?",
            (provider_name, region_name),
        ).fetchone()[0]
        offset = (page - 1) * page_size
        sids = [r[0] for r in conn.execute(
            "SELECT DISTINCT s.id FROM dr_services s INNER JOIN replication_metrics r ON s.id=r.service_id WHERE s.provider=? AND s.region=? ORDER BY s.id LIMIT ? OFFSET ?",
            (provider_name, region_name, page_size, offset),
        ).fetchall()]

        results = []
        for sid in sids:
            svc = conn.execute("SELECT service_name, tier FROM dr_services WHERE id=?", (sid,)).fetchone()
            lags = [r[0] for r in conn.execute("SELECT lag_ms FROM replication_metrics WHERE service_id=?", (sid,)).fetchall()]
            latest_status = conn.execute(
                "SELECT replication_status FROM replication_metrics WHERE service_id=? ORDER BY measured_at DESC LIMIT 1", (sid,)
            ).fetchone()[0]
            avg_lag = sum(lags) / len(lags)
            p95_lag = float(np.percentile(lags, 95))
            results.append({
                "service_id": sid,
                "service_name": svc[0],
                "tier": svc[1],
                "avg_lag_ms": round(avg_lag, 2),
                "max_lag_ms": round(max(lags), 2),
                "p95_lag_ms": round(p95_lag, 2),
                "measurement_count": len(lags),
                "latest_status": latest_status,
            })
        conn.close()
        total_pages = max(1, math.ceil(total / page_size))
        return {"services": results, "page": page, "page_size": page_size, "total_services": total, "total_pages": total_pages}

    @tool(
        description="Get snapshot compliance metrics for all services in a provider-region. Returns per-service total/successful/failed snapshot counts, success rate, minimum and maximum retention days, average size, and last snapshot time. Results are paginated.",
        parameters={
            "type": "object",
            "properties": {
                "provider_name": {"type": "string", "description": "Provider name."},
                "region_name": {"type": "string", "description": "Region name."},
                "page": {"type": "integer", "description": "Page number (1-based, default 1)."},
                "page_size": {"type": "integer", "description": "Results per page (default 20)."},
            },
            "required": ["provider_name", "region_name"],
        },
    )
    def get_snapshot_report(self, provider_name: str, region_name: str, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(DISTINCT s.id) FROM dr_services s INNER JOIN snapshot_records sr ON s.id=sr.service_id WHERE s.provider=? AND s.region=?",
            (provider_name, region_name),
        ).fetchone()[0]
        offset = (page - 1) * page_size
        sids = [r[0] for r in conn.execute(
            "SELECT DISTINCT s.id FROM dr_services s INNER JOIN snapshot_records sr ON s.id=sr.service_id WHERE s.provider=? AND s.region=? ORDER BY s.id LIMIT ? OFFSET ?",
            (provider_name, region_name, page_size, offset),
        ).fetchall()]

        results = []
        for sid in sids:
            svc = conn.execute("SELECT service_name, tier FROM dr_services WHERE id=?", (sid,)).fetchone()
            snaps = conn.execute(
                "SELECT status, retention_days, size_gb, snapshot_time FROM snapshot_records WHERE service_id=?", (sid,)
            ).fetchall()
            total_snaps = len(snaps)
            successful = sum(1 for s in snaps if s[0] == "completed")
            retentions = [s[1] for s in snaps]
            sizes = [s[2] for s in snaps]
            last_time = max(s[3] for s in snaps)
            results.append({
                "service_id": sid,
                "service_name": svc[0],
                "tier": svc[1],
                "total_snapshots": total_snaps,
                "successful_snapshots": successful,
                "failed_snapshots": total_snaps - successful,
                "success_rate_pct": round(successful / total_snaps * 100, 2) if total_snaps else 100.0,
                "min_retention_days": min(retentions),
                "max_retention_days": max(retentions),
                "avg_size_gb": round(sum(sizes) / len(sizes), 2),
                "last_snapshot_time": last_time,
            })
        conn.close()
        total_pages = max(1, math.ceil(total / page_size))
        return {"services": results, "page": page, "page_size": page_size, "total_services": total, "total_pages": total_pages}

    @tool(
        description="Get DNS failover test results for all services in a provider-region. Returns per-service total/successful tests, success rate, average response time, most common failover target region, and last test time. Results are paginated.",
        parameters={
            "type": "object",
            "properties": {
                "provider_name": {"type": "string", "description": "Provider name."},
                "region_name": {"type": "string", "description": "Region name."},
                "page": {"type": "integer", "description": "Page number (1-based, default 1)."},
                "page_size": {"type": "integer", "description": "Results per page (default 20)."},
            },
            "required": ["provider_name", "region_name"],
        },
    )
    def get_dns_report(self, provider_name: str, region_name: str, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(DISTINCT s.id) FROM dr_services s INNER JOIN dns_failover_logs d ON s.id=d.service_id WHERE s.provider=? AND s.region=?",
            (provider_name, region_name),
        ).fetchone()[0]
        offset = (page - 1) * page_size
        sids = [r[0] for r in conn.execute(
            "SELECT DISTINCT s.id FROM dr_services s INNER JOIN dns_failover_logs d ON s.id=d.service_id WHERE s.provider=? AND s.region=? ORDER BY s.id LIMIT ? OFFSET ?",
            (provider_name, region_name, page_size, offset),
        ).fetchall()]

        results = []
        for sid in sids:
            svc = conn.execute("SELECT service_name, tier FROM dr_services WHERE id=?", (sid,)).fetchone()
            logs = conn.execute(
                "SELECT success, response_time_ms, failover_target_region, test_time FROM dns_failover_logs WHERE service_id=?",
                (sid,),
            ).fetchall()
            total_tests = len(logs)
            successful = sum(1 for l in logs if l[0] == 1)
            resp_times = [l[1] for l in logs]
            targets = [l[2] for l in logs]
            target_counter = Counter(targets)
            most_common = target_counter.most_common(1)[0][0] if target_counter else ""
            last_time = max(l[3] for l in logs)
            results.append({
                "service_id": sid,
                "service_name": svc[0],
                "tier": svc[1],
                "total_tests": total_tests,
                "successful_tests": successful,
                "success_rate_pct": round(successful / total_tests * 100, 2) if total_tests else 100.0,
                "avg_response_time_ms": round(sum(resp_times) / len(resp_times), 2),
                "most_common_failover_target": most_common,
                "last_test_time": last_time,
            })
        conn.close()
        total_pages = max(1, math.ceil(total / page_size))
        return {"services": results, "page": page, "page_size": page_size, "total_services": total, "total_pages": total_pages}

    @tool(
        description="Get regional health check history for all services in a provider-region. Returns per-service total/healthy check counts, uptime percentage, average latency, and last check status. Results are paginated.",
        parameters={
            "type": "object",
            "properties": {
                "provider_name": {"type": "string", "description": "Provider name."},
                "region_name": {"type": "string", "description": "Region name."},
                "page": {"type": "integer", "description": "Page number (1-based, default 1)."},
                "page_size": {"type": "integer", "description": "Results per page (default 20)."},
            },
            "required": ["provider_name", "region_name"],
        },
    )
    def get_health_report(self, provider_name: str, region_name: str, page: int = 1, page_size: int = 20):
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(DISTINCT s.id) FROM dr_services s INNER JOIN health_checks h ON s.id=h.service_id WHERE s.provider=? AND s.region=?",
            (provider_name, region_name),
        ).fetchone()[0]
        offset = (page - 1) * page_size
        sids = [r[0] for r in conn.execute(
            "SELECT DISTINCT s.id FROM dr_services s INNER JOIN health_checks h ON s.id=h.service_id WHERE s.provider=? AND s.region=? ORDER BY s.id LIMIT ? OFFSET ?",
            (provider_name, region_name, page_size, offset),
        ).fetchall()]

        results = []
        for sid in sids:
            svc = conn.execute("SELECT service_name, tier FROM dr_services WHERE id=?", (sid,)).fetchone()
            checks = conn.execute(
                "SELECT healthy, latency_ms, check_time FROM health_checks WHERE service_id=?", (sid,)
            ).fetchall()
            total_checks = len(checks)
            healthy_cnt = sum(1 for c in checks if c[0] == 1)
            lats = [c[1] for c in checks]
            last_time = max(c[2] for c in checks)
            last_status = conn.execute(
                "SELECT healthy FROM health_checks WHERE service_id=? ORDER BY check_time DESC LIMIT 1", (sid,)
            ).fetchone()[0]
            results.append({
                "service_id": sid,
                "service_name": svc[0],
                "tier": svc[1],
                "total_checks": total_checks,
                "healthy_checks": healthy_cnt,
                "uptime_pct": round(healthy_cnt / total_checks * 100, 2) if total_checks else 100.0,
                "avg_latency_ms": round(sum(lats) / len(lats), 2),
                "last_check_healthy": bool(last_status),
            })
        conn.close()
        total_pages = max(1, math.ceil(total / page_size))
        return {"services": results, "page": page, "page_size": page_size, "total_services": total, "total_pages": total_pages}

    # ── Helpers (internal) ───────────────────────────────────────────────────

    def _read_severity_matrix(self):
        """Parse severity_matrix.csv from workspace."""
        rows = []
        with open(os.path.join(self.workspace, "severity_matrix.csv"), newline="") as f:
            for row in csv.DictReader(f):
                rows.append(row)
        return rows

    def _lookup_severity(self, matrix, category, deviation):
        for row in matrix:
            if row["gap_category"] != category:
                continue
            lo = float(row["deviation_pct_min"])
            hi = float(row["deviation_pct_max"]) if row["deviation_pct_max"] else float("inf")
            if lo <= deviation < hi:
                return row["severity"]
        return "unknown"

    def _read_all_service_configs(self):
        """Read all service DR config batch files from workspace."""
        configs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("service_dr_config_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            ext = fname.rsplit(".", 1)[-1]
            batch = []

            if ext == "json":
                with open(fpath) as f:
                    batch = json.load(f)
            elif ext == "csv":
                with open(fpath, newline="") as f:
                    for row in csv.DictReader(f):
                        for k in ("service_id", "rto_minutes", "rpo_minutes", "backup_retention_required_days"):
                            if k in row:
                                row[k] = int(row[k])
                        batch.append(row)
            elif ext == "yaml":
                with open(fpath) as f:
                    batch = yaml.safe_load(f) or []
            elif ext == "txt":
                with open(fpath) as f:
                    current = {}
                    for line in f:
                        line = line.strip()
                        if not line:
                            if current:
                                batch.append(current)
                                current = {}
                        elif "=" in line:
                            k, v = line.split("=", 1)
                            current[k] = v
                    if current:
                        batch.append(current)
                for item in batch:
                    for k in ("service_id", "rto_minutes", "rpo_minutes", "backup_retention_required_days"):
                        if k in item:
                            item[k] = int(item[k])
            else:
                continue

            for cfg in batch:
                sid = int(cfg["service_id"]) if not isinstance(cfg["service_id"], int) else cfg["service_id"]
                # Normalise date objects from YAML
                if "last_dr_drill_date" in cfg:
                    cfg["last_dr_drill_date"] = str(cfg["last_dr_drill_date"])
                if "backup_retention_required_days" in cfg and not isinstance(cfg["backup_retention_required_days"], int):
                    cfg["backup_retention_required_days"] = int(cfg["backup_retention_required_days"])
                configs[sid] = cfg
        return configs

    def _compute_ground_truth(self):
        """Compute all expected compliance gaps from DB + workspace."""
        conn = sqlite3.connect(self.db_path)

        # Load workspace data
        with open(os.path.join(self.workspace, "compliance_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)["tiers"]
        with open(os.path.join(self.workspace, "dr_policy.json")) as f:
            policy = json.load(f)
        reference_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        sev_matrix = self._read_severity_matrix()
        svc_configs = self._read_all_service_configs()

        services = conn.execute(
            "SELECT id, provider, region, service_name, service_type, tier FROM dr_services ORDER BY id"
        ).fetchall()

        gaps = []
        for sid, provider, region, sname, stype, tier in services:
            tt = thresholds[tier]
            cfg = svc_configs.get(sid, {})

            # 1. Replication lag
            lags = [r[0] for r in conn.execute(
                "SELECT lag_ms FROM replication_metrics WHERE service_id=?", (sid,)
            ).fetchall()]
            if lags:
                avg_lag = sum(lags) / len(lags)
                thresh = tt["max_avg_replication_lag_ms"]
                if avg_lag > thresh:
                    dev = (avg_lag - thresh) / thresh * 100
                    sev = self._lookup_severity(sev_matrix, "replication_lag", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "replication_lag", "avg_replication_lag_ms",
                                              avg_lag, thresh, dev, sev))

            # 2. Snapshot compliance
            snaps = conn.execute(
                "SELECT status, retention_days FROM snapshot_records WHERE service_id=?", (sid,)
            ).fetchall()
            if snaps:
                total_s = len(snaps)
                ok_s = sum(1 for s in snaps if s[0] == "completed")
                rate = ok_s / total_s * 100
                thresh = tt["min_snapshot_success_rate_pct"]
                if rate < thresh:
                    dev = (thresh - rate) / thresh * 100
                    sev = self._lookup_severity(sev_matrix, "snapshot_compliance", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "snapshot_compliance", "snapshot_success_rate_pct",
                                              rate, thresh, dev, sev))

                # 3. Retention shortfall
                min_ret = min(s[1] for s in snaps)
                req_ret = cfg.get("backup_retention_required_days", 0)
                if isinstance(req_ret, str):
                    req_ret = int(req_ret)
                if req_ret > 0 and min_ret < req_ret:
                    dev = (req_ret - min_ret) / req_ret * 100
                    sev = self._lookup_severity(sev_matrix, "retention_shortfall", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "retention_shortfall", "min_retention_days",
                                              min_ret, req_ret, dev, sev))

            # 4. DNS failover
            dns_rows = conn.execute(
                "SELECT success, failover_target_region FROM dns_failover_logs WHERE service_id=?", (sid,)
            ).fetchall()
            if dns_rows:
                total_d = len(dns_rows)
                ok_d = sum(1 for d in dns_rows if d[0] == 1)
                rate_d = ok_d / total_d * 100
                thresh = tt["min_dns_success_rate_pct"]
                if rate_d < thresh:
                    dev = (thresh - rate_d) / thresh * 100
                    sev = self._lookup_severity(sev_matrix, "dns_failover", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "dns_failover", "dns_success_rate_pct",
                                              rate_d, thresh, dev, sev))

                # 5. Failover mismatch
                targets = [d[1] for d in dns_rows]
                most_common = Counter(targets).most_common(1)[0][0]
                designated = cfg.get("designated_failover_region", "")
                if designated and most_common != designated:
                    dev = 100.0
                    sev = self._lookup_severity(sev_matrix, "failover_mismatch", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "failover_mismatch", "failover_target_region",
                                              most_common, designated, dev, sev,
                                              string_values=True))

            # 6. Health uptime
            hrows = conn.execute(
                "SELECT healthy FROM health_checks WHERE service_id=?", (sid,)
            ).fetchall()
            if hrows:
                total_h = len(hrows)
                ok_h = sum(1 for h in hrows if h[0] == 1)
                uptime = ok_h / total_h * 100
                thresh = tt["min_health_uptime_pct"]
                if uptime < thresh:
                    dev = (thresh - uptime) / thresh * 100
                    sev = self._lookup_severity(sev_matrix, "health_uptime", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "health_uptime", "health_uptime_pct",
                                              uptime, thresh, dev, sev))

            # 7. DR drill overdue
            drill_date_str = cfg.get("last_dr_drill_date", "")
            if drill_date_str:
                drill_date = datetime.strptime(str(drill_date_str), "%Y-%m-%d")
                days_since = (reference_date - drill_date).days
                max_age = tt["max_dr_drill_age_days"]
                if days_since > max_age:
                    dev = (days_since - max_age) / max_age * 100
                    sev = self._lookup_severity(sev_matrix, "dr_drill_overdue", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "dr_drill_overdue", "days_since_last_drill",
                                              days_since, max_age, dev, sev))

        conn.close()
        gaps.sort(key=lambda g: (g["provider"], g["region"], g["service_name"], g["gap_category"]))
        return gaps

    @staticmethod
    def _gap_row(sid, provider, region, sname, tier, category, metric,
                 actual, required, dev, sev, string_values=False):
        if string_values:
            return {
                "service_id": sid, "provider": provider, "region": region,
                "service_name": sname, "tier": tier, "gap_category": category,
                "metric_name": metric,
                "actual_value": str(actual),
                "required_value": str(required),
                "deviation_pct": f"{dev:.1f}",
                "severity": sev,
            }
        return {
            "service_id": sid, "provider": provider, "region": region,
            "service_name": sname, "tier": tier, "gap_category": category,
            "metric_name": metric,
            "actual_value": f"{actual:.2f}",
            "required_value": f"{required:.2f}",
            "deviation_pct": f"{dev:.1f}",
            "severity": sev,
        }

    # ── Evaluation ───────────────────────────────────────────────────────────

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
        gt_gaps = self._compute_ground_truth()
        gt_keys = {(g["service_id"], g["gap_category"]) for g in gt_gaps}
        gt_map = {(g["service_id"], g["gap_category"]): g for g in gt_gaps}

        criteria = {}

        # ── 1. Report structure (10 pts) ─────────────────────────────────────
        csv_path = os.path.join(self.workspace, "compliance_gap_report.csv")
        expected_cols = [
            "service_id", "provider", "region", "service_name", "tier",
            "gap_category", "metric_name", "actual_value", "required_value",
            "deviation_pct", "severity",
        ]
        reported_gaps = []
        report_ok = False
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = list(reader.fieldnames or [])
                    if cols == expected_cols:
                        for row in reader:
                            row["service_id"] = int(row["service_id"])
                            reported_gaps.append(row)
                        report_ok = True
            except Exception:
                pass

        criteria["report_structure"] = {
            "passed": report_ok,
            "score": 10 if report_ok else 0,
            "max_score": 10,
            "reason": "" if report_ok else "CSV missing or columns mismatch",
        }

        # Build reported key set
        rep_keys = set()
        rep_map = {}
        for g in reported_gaps:
            k = (g["service_id"], g["gap_category"])
            rep_keys.add(k)
            rep_map[k] = g

        # ── 2. Gap completeness – recall (25 pts) ───────────────────────────
        tp = gt_keys & rep_keys
        recall = len(tp) / len(gt_keys) if gt_keys else 1.0
        completeness_score = round(recall * 25)
        criteria["gap_completeness"] = {
            "passed": recall >= 0.95,
            "score": completeness_score,
            "max_score": 25,
            "reason": f"recall={recall:.3f} ({len(tp)}/{len(gt_keys)})" if recall < 1.0 else "",
        }

        # ── 3. Gap precision (20 pts) ───────────────────────────────────────
        precision = len(tp) / len(rep_keys) if rep_keys else (1.0 if not gt_keys else 0.0)
        precision_score = round(precision * 20)
        criteria["gap_precision"] = {
            "passed": precision >= 0.95,
            "score": precision_score,
            "max_score": 20,
            "reason": f"precision={precision:.3f} ({len(tp)}/{len(rep_keys)})" if precision < 1.0 else "",
        }

        # ── 4. Metric accuracy (15 pts) ─────────────────────────────────────
        if tp:
            correct_metrics = 0
            for k in tp:
                gt = gt_map[k]
                rp = rep_map[k]
                if gt["gap_category"] == "failover_mismatch":
                    if rp.get("actual_value", "") == gt["actual_value"] and rp.get("required_value", "") == gt["required_value"]:
                        correct_metrics += 1
                else:
                    try:
                        av_ok = abs(float(rp["actual_value"]) - float(gt["actual_value"])) < 0.1
                        rv_ok = abs(float(rp["required_value"]) - float(gt["required_value"])) < 0.1
                        if av_ok and rv_ok:
                            correct_metrics += 1
                    except (ValueError, KeyError):
                        pass
            metric_ratio = correct_metrics / len(tp)
        else:
            metric_ratio = 0.0
        metric_score = round(metric_ratio * 15)
        criteria["metric_accuracy"] = {
            "passed": metric_ratio >= 0.95,
            "score": metric_score,
            "max_score": 15,
            "reason": f"accuracy={metric_ratio:.3f}" if metric_ratio < 1.0 else "",
        }

        # ── 5. Severity accuracy (15 pts) ───────────────────────────────────
        if tp:
            correct_sev = sum(1 for k in tp if rep_map[k].get("severity", "") == gt_map[k]["severity"])
            sev_ratio = correct_sev / len(tp)
        else:
            sev_ratio = 0.0
        sev_score = round(sev_ratio * 15)
        criteria["severity_accuracy"] = {
            "passed": sev_ratio >= 0.95,
            "score": sev_score,
            "max_score": 15,
            "reason": f"accuracy={sev_ratio:.3f}" if sev_ratio < 1.0 else "",
        }

        # ── 6. Summary response (15 pts) ────────────────────────────────────
        summary_score = 0
        max_summary = 15
        reasons = []

        # Expected summary values
        total_gt = len(gt_gaps)
        sev_counts = Counter(g["severity"] for g in gt_gaps)
        provider_counts = Counter(g["provider"] for g in gt_gaps)
        category_counts = Counter(g["gap_category"] for g in gt_gaps)
        top_provider = provider_counts.most_common(1)[0] if provider_counts else ("N/A", 0)
        top_category = category_counts.most_common(1)[0] if category_counts else ("N/A", 0)

        # Check Total Gaps
        m = re.search(r"Total Gaps:\s*(\d+)", action)
        if m and int(m.group(1)) == total_gt:
            summary_score += 4
        else:
            reasons.append(f"total_gaps expected {total_gt}")

        # Check severity breakdown
        crit_m = re.search(r"Critical:\s*(\d+)", action)
        high_m = re.search(r"High:\s*(\d+)", action)
        med_m = re.search(r"Medium:\s*(\d+)", action)
        low_m = re.search(r"Low:\s*(\d+)", action)
        if (crit_m and high_m and med_m and low_m
                and int(crit_m.group(1)) == sev_counts.get("critical", 0)
                and int(high_m.group(1)) == sev_counts.get("high", 0)
                and int(med_m.group(1)) == sev_counts.get("medium", 0)
                and int(low_m.group(1)) == sev_counts.get("low", 0)):
            summary_score += 4
        else:
            reasons.append("severity breakdown mismatch")

        # Check provider with most gaps
        pm = re.search(r"Provider with Most Gaps:\s*(\S+)\s*\((\d+)\)", action)
        if pm and pm.group(1) == top_provider[0] and int(pm.group(2)) == top_provider[1]:
            summary_score += 4
        else:
            reasons.append(f"top_provider expected {top_provider[0]}({top_provider[1]})")

        # Check most common gap category
        cm = re.search(r"Most Common Gap Category:\s*(\S+)\s*\((\d+)\)", action)
        if cm and cm.group(1) == top_category[0] and int(cm.group(2)) == top_category[1]:
            summary_score += 3
        else:
            reasons.append(f"top_category expected {top_category[0]}({top_category[1]})")

        criteria["summary_response"] = {
            "passed": summary_score == max_summary,
            "score": summary_score,
            "max_score": max_summary,
            "reason": "; ".join(reasons) if reasons else "",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ── Self-verification ────────────────────────────────────────────────────

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
        ws = self.workspace
        tool_call_count = 0

        # ── 1. Discover providers and regions via tools ──────────────────────
        prov_resp = self.tools["list_providers"]()
        tool_call_count += 1
        providers = prov_resp["providers"]

        # Collect all per-service data
        service_data = {}  # sid -> {provider, region, service_name, tier, repl, snap, dns, health}

        for p in providers:
            pname = p["name"]
            reg_resp = self.tools["list_regions"](provider_name=pname)
            tool_call_count += 1

            for rinfo in reg_resp["regions"]:
                rname = rinfo["region_name"]

                # Replication
                page = 1
                while True:
                    resp = self.tools["get_replication_report"](provider_name=pname, region_name=rname, page=page, page_size=20)
                    tool_call_count += 1
                    for svc in resp["services"]:
                        sid = svc["service_id"]
                        service_data.setdefault(sid, {"provider": pname, "region": rname,
                                                       "service_name": svc["service_name"],
                                                       "tier": svc["tier"]})
                        service_data[sid]["replication"] = svc
                    if page >= resp["total_pages"]:
                        break
                    page += 1

                # Snapshot
                page = 1
                while True:
                    resp = self.tools["get_snapshot_report"](provider_name=pname, region_name=rname, page=page, page_size=20)
                    tool_call_count += 1
                    for svc in resp["services"]:
                        service_data[svc["service_id"]]["snapshot"] = svc
                    if page >= resp["total_pages"]:
                        break
                    page += 1

                # DNS
                page = 1
                while True:
                    resp = self.tools["get_dns_report"](provider_name=pname, region_name=rname, page=page, page_size=20)
                    tool_call_count += 1
                    for svc in resp["services"]:
                        service_data[svc["service_id"]]["dns"] = svc
                    if page >= resp["total_pages"]:
                        break
                    page += 1

                # Health
                page = 1
                while True:
                    resp = self.tools["get_health_report"](provider_name=pname, region_name=rname, page=page, page_size=20)
                    tool_call_count += 1
                    for svc in resp["services"]:
                        service_data[svc["service_id"]]["health"] = svc
                    if page >= resp["total_pages"]:
                        break
                    page += 1

        # ── 2. Read workspace configuration files ────────────────────────────
        with open(os.path.join(ws, "compliance_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)["tiers"]
        with open(os.path.join(ws, "dr_policy.json")) as f:
            policy = json.load(f)
        reference_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        sev_matrix = self._read_severity_matrix()
        svc_configs = self._read_all_service_configs()

        # ── 3. Identify compliance gaps ──────────────────────────────────────
        gaps = []
        for sid in sorted(service_data):
            d = service_data[sid]
            provider = d["provider"]
            region = d["region"]
            sname = d["service_name"]
            tier = d["tier"]
            tt = thresholds[tier]
            cfg = svc_configs.get(sid, {})

            # Replication lag
            repl = d.get("replication", {})
            avg_lag = repl.get("avg_lag_ms", 0)
            thresh_val = tt["max_avg_replication_lag_ms"]
            if avg_lag > thresh_val:
                dev = (avg_lag - thresh_val) / thresh_val * 100
                sev = self._lookup_severity(sev_matrix, "replication_lag", dev)
                gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                          "replication_lag", "avg_replication_lag_ms",
                                          avg_lag, thresh_val, dev, sev))

            # Snapshot compliance
            snap = d.get("snapshot", {})
            snap_rate = snap.get("success_rate_pct", 100)
            thresh_val = tt["min_snapshot_success_rate_pct"]
            if snap_rate < thresh_val:
                dev = (thresh_val - snap_rate) / thresh_val * 100
                sev = self._lookup_severity(sev_matrix, "snapshot_compliance", dev)
                gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                          "snapshot_compliance", "snapshot_success_rate_pct",
                                          snap_rate, thresh_val, dev, sev))

            # Retention shortfall
            min_ret = snap.get("min_retention_days", 999)
            req_ret = cfg.get("backup_retention_required_days", 0)
            if isinstance(req_ret, str):
                req_ret = int(req_ret)
            if req_ret > 0 and min_ret < req_ret:
                dev = (req_ret - min_ret) / req_ret * 100
                sev = self._lookup_severity(sev_matrix, "retention_shortfall", dev)
                gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                          "retention_shortfall", "min_retention_days",
                                          min_ret, req_ret, dev, sev))

            # DNS failover
            dns = d.get("dns", {})
            dns_rate = dns.get("success_rate_pct", 100)
            thresh_val = tt["min_dns_success_rate_pct"]
            if dns_rate < thresh_val:
                dev = (thresh_val - dns_rate) / thresh_val * 100
                sev = self._lookup_severity(sev_matrix, "dns_failover", dev)
                gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                          "dns_failover", "dns_success_rate_pct",
                                          dns_rate, thresh_val, dev, sev))

            # Failover mismatch
            target = dns.get("most_common_failover_target", "")
            designated = cfg.get("designated_failover_region", "")
            if target and designated and target != designated:
                dev = 100.0
                sev = self._lookup_severity(sev_matrix, "failover_mismatch", dev)
                gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                          "failover_mismatch", "failover_target_region",
                                          target, designated, dev, sev,
                                          string_values=True))

            # Health uptime
            health = d.get("health", {})
            uptime = health.get("uptime_pct", 100)
            thresh_val = tt["min_health_uptime_pct"]
            if uptime < thresh_val:
                dev = (thresh_val - uptime) / thresh_val * 100
                sev = self._lookup_severity(sev_matrix, "health_uptime", dev)
                gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                          "health_uptime", "health_uptime_pct",
                                          uptime, thresh_val, dev, sev))

            # DR drill overdue
            drill_str = cfg.get("last_dr_drill_date", "")
            if drill_str:
                drill_dt = datetime.strptime(str(drill_str), "%Y-%m-%d")
                days_since = (reference_date - drill_dt).days
                max_age = tt["max_dr_drill_age_days"]
                if days_since > max_age:
                    dev = (days_since - max_age) / max_age * 100
                    sev = self._lookup_severity(sev_matrix, "dr_drill_overdue", dev)
                    gaps.append(self._gap_row(sid, provider, region, sname, tier,
                                              "dr_drill_overdue", "days_since_last_drill",
                                              days_since, max_age, dev, sev))

        # ── 4. Sort and write CSV ────────────────────────────────────────────
        gaps.sort(key=lambda g: (g["provider"], g["region"], g["service_name"], g["gap_category"]))

        fieldnames = [
            "service_id", "provider", "region", "service_name", "tier",
            "gap_category", "metric_name", "actual_value", "required_value",
            "deviation_pct", "severity",
        ]
        csv_path = os.path.join(ws, "compliance_gap_report.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(gaps)

        # ── 5. Build summary action string ───────────────────────────────────
        total = len(gaps)
        sev_counts = Counter(g["severity"] for g in gaps)
        prov_counts = Counter(g["provider"] for g in gaps)
        cat_counts = Counter(g["gap_category"] for g in gaps)
        top_prov = prov_counts.most_common(1)[0] if prov_counts else ("N/A", 0)
        top_cat = cat_counts.most_common(1)[0] if cat_counts else ("N/A", 0)

        action = (
            f"Total Gaps: {total}\n"
            f"Critical: {sev_counts.get('critical',0)}, High: {sev_counts.get('high',0)}, "
            f"Medium: {sev_counts.get('medium',0)}, Low: {sev_counts.get('low',0)}\n"
            f"Provider with Most Gaps: {top_prov[0]} ({top_prov[1]})\n"
            f"Most Common Gap Category: {top_cat[0]} ({top_cat[1]})"
        )

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls; need >=15"
        return self.step(action)
