"""
env.py - Canary Release Decision Task Environment
"""

import sqlite3
import json
import os
import re
import csv
import math
import glob as globmod
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

    # ─────────────────────── Tool Methods ───────────────────────

    @tool(
        description=(
            "List services, optionally filtered by deployment status. "
            "Returns paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["canary", "stable"],
                    "description": "Filter by deployment_status. Omit to list all.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 10.",
                },
            },
            "required": [],
        },
    )
    def list_services(self, status: str = None, page: int = 1, page_size: int = 10):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                "SELECT service_id, service_name, deployment_status "
                "FROM services WHERE deployment_status=? ORDER BY service_id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT service_id, service_name, deployment_status "
                "FROM services ORDER BY service_id"
            ).fetchall()
        conn.close()

        total = len(rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = rows[start:end]
        return {
            "services": [dict(r) for r in page_rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    @tool(
        description="Get full details of a single service by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "The service identifier, e.g. svc_0001",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_service_details(self, service_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM services WHERE service_id=?", (service_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Service {service_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Get performance metric readings for a service. "
            "Optionally filter by metric_type and/or environment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "Service identifier",
                },
                "metric_type": {
                    "type": "string",
                    "enum": ["latency_p50", "latency_p95", "error_rate",
                             "cpu_usage", "memory_usage"],
                    "description": "Filter by metric type. Omit for all types.",
                },
                "environment": {
                    "type": "string",
                    "enum": ["canary", "stable"],
                    "description": "Filter by environment. Omit for both.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_performance_metrics(self, service_id: str,
                                metric_type: str = None,
                                environment: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM performance_metrics WHERE service_id=?"
        params: list = [service_id]
        if metric_type:
            sql += " AND metric_type=?"
            params.append(metric_type)
        if environment:
            sql += " AND environment=?"
            params.append(environment)
        sql += " ORDER BY timestamp"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return {"metrics": [dict(r) for r in rows]}

    @tool(
        description=(
            "Get synthetic transaction results for a service. "
            "Paginated. Optionally filter by environment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "Service identifier",
                },
                "environment": {
                    "type": "string",
                    "enum": ["canary", "stable"],
                    "description": "Filter by environment. Omit for both.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 10.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_synthetic_transactions(self, service_id: str,
                                   environment: str = None,
                                   page: int = 1,
                                   page_size: int = 10):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM synthetic_transactions WHERE service_id=?"
        params: list = [service_id]
        if environment:
            sql += " AND environment=?"
            params.append(environment)
        sql += " ORDER BY timestamp"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        total = len(rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "transactions": [dict(r) for r in rows[start:end]],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    @tool(
        description=(
            "Get error log entries for a service. "
            "Paginated. Optionally filter by severity and/or environment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "Service identifier",
                },
                "severity": {
                    "type": "string",
                    "enum": ["critical", "warning", "info"],
                    "description": "Filter by severity. Omit for all.",
                },
                "environment": {
                    "type": "string",
                    "enum": ["canary", "stable"],
                    "description": "Filter by environment. Omit for both.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 10.",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_error_logs(self, service_id: str,
                       severity: str = None,
                       environment: str = None,
                       page: int = 1,
                       page_size: int = 10):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM error_logs WHERE service_id=?"
        params: list = [service_id]
        if severity:
            sql += " AND severity=?"
            params.append(severity)
        if environment:
            sql += " AND environment=?"
            params.append(environment)
        sql += " ORDER BY timestamp"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        total = len(rows)
        total_pages = max(1, math.ceil(total / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "logs": [dict(r) for r in rows[start:end]],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    @tool(
        description="Get all feature flags for a service.",
        parameters={
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "description": "Service identifier",
                },
            },
            "required": ["service_id"],
        },
    )
    def get_feature_flags(self, service_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM feature_flags WHERE service_id=? ORDER BY flag_name",
            (service_id,),
        ).fetchall()
        conn.close()
        return {"flags": [dict(r) for r in rows]}

    # ─────────────────────── Ground-truth helper ───────────────────────

    def _compute_ground_truth(self):
        """Compute the correct answer using direct DB + workspace access."""
        import yaml

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load workspace configs
        with open(os.path.join(self.workspace, "canary_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        weights = policy["scoring"]["weights"]
        thresholds = policy["scoring"]["decision_thresholds"]

        with open(os.path.join(self.workspace, "tier_config.json")) as f:
            tier_config = json.load(f)

        # Load baselines from CSV files
        baselines = {}
        for fpath in sorted(globmod.glob(
                os.path.join(self.workspace, "service_baseline_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    baselines[row["service_id"]] = {
                        "baseline_latency_p50_ms": float(row["baseline_latency_p50_ms"]),
                    }

        # Load rollout targets from YAML
        rollout_targets = {}
        for fpath in sorted(globmod.glob(
                os.path.join(self.workspace, "rollout_target_*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f)
            if data:
                for sid, info in data.items():
                    rollout_targets[sid] = info.get("flags", {})

        # Load manual overrides from TXT
        manual_overrides = set()
        for fpath in sorted(globmod.glob(
                os.path.join(self.workspace, "deployment_notes_*.txt"))):
            with open(fpath) as f:
                content = f.read()
            for m in re.finditer(
                    r"=== (svc_\d+) \(.*?\) ===\n(.*?)(?=\n=== |\Z)",
                    content, re.DOTALL):
                sid = m.group(1)
                body = m.group(2)
                if "manual_rollback_override: true" in body:
                    manual_overrides.add(sid)

        # Get canary services
        canary_svcs = conn.execute(
            "SELECT * FROM services WHERE deployment_status='canary' "
            "ORDER BY service_id"
        ).fetchall()

        gt = {}  # service_id -> dict
        for svc in canary_svcs:
            sid = svc["service_id"]
            tier = svc["tier"]
            tc = tier_config[tier]

            # Latency
            lat_rows = conn.execute(
                "SELECT value FROM performance_metrics "
                "WHERE service_id=? AND metric_type='latency_p50' "
                "AND environment='canary'", (sid,)
            ).fetchall()
            avg_lat = (sum(r["value"] for r in lat_rows) / len(lat_rows)
                       if lat_rows else 0.0)
            bl_lat = baselines.get(sid, {}).get("baseline_latency_p50_ms", avg_lat)
            deg_pct = ((avg_lat - bl_lat) / bl_lat * 100.0) if bl_lat > 0 else 0.0
            max_d = tc["max_latency_degradation_pct"]
            if deg_pct <= max_d:
                lat_score = 1.0
            elif deg_pct >= 2 * max_d:
                lat_score = 0.0
            else:
                lat_score = 1.0 - (deg_pct - max_d) / max_d
            lat_score = max(0.0, min(1.0, lat_score))

            # Error rate
            err_rows = conn.execute(
                "SELECT value FROM performance_metrics "
                "WHERE service_id=? AND metric_type='error_rate' "
                "AND environment='canary'", (sid,)
            ).fetchall()
            avg_err = (sum(r["value"] for r in err_rows) / len(err_rows)
                       if err_rows else 0.0)
            max_e = tc["max_error_rate"]
            if avg_err <= max_e:
                err_score = 1.0
            elif avg_err >= 2 * max_e:
                err_score = 0.0
            else:
                err_score = 1.0 - (avg_err - max_e) / max_e
            err_score = max(0.0, min(1.0, err_score))

            # Synthetic success rate
            tx_all = conn.execute(
                "SELECT status FROM synthetic_transactions "
                "WHERE service_id=? AND environment='canary'", (sid,)
            ).fetchall()
            n_total = len(tx_all)
            n_success = sum(1 for t in tx_all if t["status"] == "success")
            syn_rate = n_success / n_total if n_total > 0 else 1.0
            min_s = tc["min_synthetic_success_rate"]
            if syn_rate >= min_s:
                syn_score = 1.0
            elif syn_rate <= min_s - 0.10:
                syn_score = 0.0
            else:
                syn_score = (syn_rate - (min_s - 0.10)) / 0.10
            syn_score = max(0.0, min(1.0, syn_score))

            # Flag coverage
            flags = conn.execute(
                "SELECT flag_name, rollout_percentage FROM feature_flags "
                "WHERE service_id=?", (sid,)
            ).fetchall()
            svc_targets = rollout_targets.get(sid, {})
            coverages = []
            for fl in flags:
                fname = fl["flag_name"]
                if fname in svc_targets:
                    tgt = svc_targets[fname].get("target_rollout_pct", 0)
                    if tgt > 0:
                        coverages.append(fl["rollout_percentage"] / tgt)
            avg_cov = sum(coverages) / len(coverages) if coverages else 1.0
            min_fc = tc["min_flag_coverage"]
            if avg_cov >= min_fc:
                flag_score = 1.0
            else:
                flag_score = avg_cov / min_fc
            flag_score = max(0.0, min(1.0, flag_score))

            # Weighted
            w_score = (lat_score * weights["latency"]
                       + err_score * weights["error_rate"]
                       + syn_score * weights["synthetic_success"]
                       + flag_score * weights["flag_coverage"])

            # Critical errors
            crit_cnt = conn.execute(
                "SELECT COUNT(*) as cnt FROM error_logs "
                "WHERE service_id=? AND environment='canary' "
                "AND severity='critical'", (sid,)
            ).fetchone()["cnt"]
            has_crit = crit_cnt > 0

            has_override = sid in manual_overrides

            if has_crit or has_override:
                decision = "ROLLBACK"
            elif w_score >= thresholds["promote"]:
                decision = "PROMOTE"
            elif w_score < thresholds["rollback"]:
                decision = "ROLLBACK"
            else:
                decision = "HOLD"

            gt[sid] = {
                "service_name": svc["service_name"],
                "tier": tier,
                "latency_degradation_pct": round(deg_pct, 4),
                "latency_score": round(lat_score, 4),
                "error_rate": round(avg_err, 4),
                "error_score": round(err_score, 4),
                "synthetic_success_rate": round(syn_rate, 4),
                "synthetic_score": round(syn_score, 4),
                "flag_coverage": round(avg_cov, 4),
                "flag_score": round(flag_score, 4),
                "weighted_score": round(w_score, 4),
                "has_critical_errors": has_crit,
                "has_manual_override": has_override,
                "decision": decision,
            }

        conn.close()

        # Overall decision
        has_crit_rollback = any(
            v["decision"] == "ROLLBACK" and v["tier"] == "critical"
            for v in gt.values()
        )
        all_promote = all(v["decision"] == "PROMOTE" for v in gt.values())
        if has_crit_rollback:
            overall = "ROLLBACK"
        elif all_promote:
            overall = "PROMOTE"
        else:
            overall = "HOLD"

        rollback_names = sorted(
            v["service_name"] for v in gt.values() if v["decision"] == "ROLLBACK"
        )

        return gt, overall, rollback_names, thresholds, weights

    # ─────────────────────── step ───────────────────────

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
        gt, overall_gt, rollback_names_gt, thresholds, weights = \
            self._compute_ground_truth()

        criteria = {}
        svc_ids = sorted(gt.keys())
        n_svcs = len(svc_ids)

        # ── 1. report_structure (10 pts) ──
        report_path = os.path.join(self.workspace, "decision_report.csv")
        expected_cols = [
            "service_id", "service_name", "tier",
            "latency_degradation_pct", "latency_score",
            "error_rate", "error_score",
            "synthetic_success_rate", "synthetic_score",
            "flag_coverage", "flag_score",
            "weighted_score", "has_critical_errors",
            "has_manual_override", "decision",
        ]
        report_rows = {}
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = list(reader.fieldnames or [])
                    for row in reader:
                        report_rows[row.get("service_id", "")] = row
                cols_ok = actual_cols == expected_cols
            except Exception:
                cols_ok = False
        else:
            cols_ok = False

        has_all_svcs = all(sid in report_rows for sid in svc_ids)
        struct_ok = cols_ok and has_all_svcs
        criteria["report_structure"] = {
            "passed": struct_ok,
            "score": 10 if struct_ok else (5 if cols_ok else 0),
            "max_score": 10,
            "reason": "" if struct_ok else
                      ("columns mismatch" if not cols_ok else "missing services"),
        }

        # ── 2. service_decisions (25 pts) ──
        correct_decisions = 0
        for sid in svc_ids:
            if sid in report_rows:
                if report_rows[sid].get("decision", "").strip().upper() == gt[sid]["decision"]:
                    correct_decisions += 1
        dec_score = round(25 * correct_decisions / n_svcs) if n_svcs > 0 else 0
        criteria["service_decisions"] = {
            "passed": correct_decisions == n_svcs,
            "score": dec_score,
            "max_score": 25,
            "reason": "" if correct_decisions == n_svcs else
                      f"{correct_decisions}/{n_svcs} correct",
        }

        # ── 3. score_accuracy (20 pts) ──
        TOLERANCE = 0.03
        score_fields = [
            "latency_score", "error_score", "synthetic_score",
            "flag_score", "weighted_score",
        ]
        correct_scores = 0
        for sid in svc_ids:
            if sid not in report_rows:
                continue
            row = report_rows[sid]
            all_close = True
            for sf in score_fields:
                try:
                    agent_val = float(row.get(sf, -999))
                    gt_val = gt[sid][sf]
                    if abs(agent_val - gt_val) > TOLERANCE:
                        all_close = False
                        break
                except (ValueError, TypeError):
                    all_close = False
                    break
            if all_close:
                correct_scores += 1
        sc_score = round(20 * correct_scores / n_svcs) if n_svcs > 0 else 0
        criteria["score_accuracy"] = {
            "passed": correct_scores == n_svcs,
            "score": sc_score,
            "max_score": 20,
            "reason": "" if correct_scores == n_svcs else
                      f"{correct_scores}/{n_svcs} within tolerance",
        }

        # ── 4. summary_file (15 pts) ──
        summary_path = os.path.join(self.workspace, "overall_summary.json")
        summary_ok = False
        summary_pts = 0
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                od_ok = summary.get("overall_decision", "").upper() == overall_gt
                cnt_ok = (summary.get("promote_count", -1) ==
                          sum(1 for v in gt.values() if v["decision"] == "PROMOTE") and
                          summary.get("rollback_count", -1) ==
                          sum(1 for v in gt.values() if v["decision"] == "ROLLBACK") and
                          summary.get("hold_count", -1) ==
                          sum(1 for v in gt.values() if v["decision"] == "HOLD"))
                rb_ok = sorted(summary.get("rollback_services", [])) == rollback_names_gt
                total_ok = summary.get("total_canary_services", -1) == n_svcs
                if od_ok and cnt_ok and rb_ok and total_ok:
                    summary_ok = True
                    summary_pts = 15
                else:
                    summary_pts = (5 if od_ok else 0) + (5 if cnt_ok else 0) + (3 if rb_ok else 0) + (2 if total_ok else 0)
                    summary_pts = min(summary_pts, 14)
            except Exception:
                pass
        criteria["summary_file"] = {
            "passed": summary_ok,
            "score": summary_pts,
            "max_score": 15,
        }

        # ── 5. response_overall_decision (10 pts) ──
        action_upper = action.upper() if action else ""
        resp_dec_ok = overall_gt in action_upper
        criteria["response_overall_decision"] = {
            "passed": resp_dec_ok,
            "score": 10 if resp_dec_ok else 0,
            "max_score": 10,
            "reason": "" if resp_dec_ok else f"expected {overall_gt} in response",
        }

        # ── 6. response_rollback_list (10 pts) ──
        if rollback_names_gt:
            found = sum(1 for nm in rollback_names_gt
                        if nm.lower() in action.lower())
            rb_list_score = round(10 * found / len(rollback_names_gt))
            rb_ok = found == len(rollback_names_gt)
        else:
            rb_ok = True
            rb_list_score = 10
        criteria["response_rollback_list"] = {
            "passed": rb_ok,
            "score": rb_list_score,
            "max_score": 10,
            "reason": "" if rb_ok else
                      f"found {found}/{len(rollback_names_gt)} rollback names",
        }

        # ── 7. override_handling (10 pts) ──
        override_sids = [sid for sid in svc_ids
                         if gt[sid]["has_critical_errors"] or
                         gt[sid]["has_manual_override"]]
        if override_sids:
            ov_correct = 0
            for sid in override_sids:
                if sid in report_rows:
                    r = report_rows[sid]
                    if (r.get("decision", "").strip().upper() == "ROLLBACK" and
                        ((r.get("has_critical_errors", "").strip().lower() ==
                          str(gt[sid]["has_critical_errors"]).lower()) and
                         (r.get("has_manual_override", "").strip().lower() ==
                          str(gt[sid]["has_manual_override"]).lower()))):
                        ov_correct += 1
            ov_score = round(10 * ov_correct / len(override_sids))
            ov_ok = ov_correct == len(override_sids)
        else:
            ov_ok = True
            ov_score = 10
        criteria["override_handling"] = {
            "passed": ov_ok,
            "score": ov_score,
            "max_score": 10,
            "reason": "" if ov_ok else
                      f"{ov_correct}/{len(override_sids)} overrides correct",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # ─────────────────────── verify ───────────────────────

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

        workspace = self.workspace
        tool_calls = 0

        # ── Read workspace config files ──
        with open(os.path.join(workspace, "canary_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        w = policy["scoring"]["weights"]
        thr = policy["scoring"]["decision_thresholds"]

        with open(os.path.join(workspace, "tier_config.json")) as f:
            tier_config = json.load(f)

        # Read baselines
        baselines = {}
        for fpath in sorted(globmod.glob(
                os.path.join(workspace, "service_baseline_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    baselines[row["service_id"]] = float(row["baseline_latency_p50_ms"])

        # Read rollout targets
        rollout_targets = {}
        for fpath in sorted(globmod.glob(
                os.path.join(workspace, "rollout_target_*.yaml"))):
            with open(fpath) as f:
                data = yaml.safe_load(f)
            if data:
                for sid, info in data.items():
                    rollout_targets[sid] = info.get("flags", {})

        # Read manual overrides
        manual_overrides = set()
        for fpath in sorted(globmod.glob(
                os.path.join(workspace, "deployment_notes_*.txt"))):
            with open(fpath) as f:
                content = f.read()
            for m_obj in re.finditer(
                    r"=== (svc_\d+) \(.*?\) ===\n(.*?)(?=\n=== |\Z)",
                    content, re.DOTALL):
                sid = m_obj.group(1)
                body = m_obj.group(2)
                if "manual_rollback_override: true" in body:
                    manual_overrides.add(sid)

        # ── Gather canary services via tools ──
        canary_services = []
        page = 1
        while True:
            res = self.tools["list_services"](status="canary", page=page, page_size=10)
            tool_calls += 1
            canary_services.extend(res["services"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ── Process each canary service ──
        report_rows = []
        for svc_summary in canary_services:
            sid = svc_summary["service_id"]

            # Get service details (for tier)
            details = self.tools["get_service_details"](service_id=sid)
            tool_calls += 1
            tier = details["tier"]
            tc = tier_config[tier]

            # --- Latency ---
            met_res = self.tools["get_performance_metrics"](
                service_id=sid, metric_type="latency_p50", environment="canary")
            tool_calls += 1
            lat_vals = [m["value"] for m in met_res["metrics"]]
            avg_lat = sum(lat_vals) / len(lat_vals) if lat_vals else 0.0
            bl_lat = baselines.get(sid, avg_lat)
            deg_pct = ((avg_lat - bl_lat) / bl_lat * 100.0) if bl_lat > 0 else 0.0
            max_d = tc["max_latency_degradation_pct"]
            if deg_pct <= max_d:
                lat_score = 1.0
            elif deg_pct >= 2 * max_d:
                lat_score = 0.0
            else:
                lat_score = 1.0 - (deg_pct - max_d) / max_d
            lat_score = max(0.0, min(1.0, lat_score))

            # --- Error rate ---
            err_res = self.tools["get_performance_metrics"](
                service_id=sid, metric_type="error_rate", environment="canary")
            tool_calls += 1
            err_vals = [m["value"] for m in err_res["metrics"]]
            avg_err = sum(err_vals) / len(err_vals) if err_vals else 0.0
            max_e = tc["max_error_rate"]
            if avg_err <= max_e:
                err_score = 1.0
            elif avg_err >= 2 * max_e:
                err_score = 0.0
            else:
                err_score = 1.0 - (avg_err - max_e) / max_e
            err_score = max(0.0, min(1.0, err_score))

            # --- Synthetic transactions ---
            all_txns = []
            tx_page = 1
            while True:
                tx_res = self.tools["get_synthetic_transactions"](
                    service_id=sid, environment="canary",
                    page=tx_page, page_size=10)
                tool_calls += 1
                all_txns.extend(tx_res["transactions"])
                if tx_page >= tx_res["total_pages"]:
                    break
                tx_page += 1
            n_success = sum(1 for t in all_txns if t["status"] == "success")
            n_total = len(all_txns)
            syn_rate = n_success / n_total if n_total > 0 else 1.0
            min_s = tc["min_synthetic_success_rate"]
            if syn_rate >= min_s:
                syn_score = 1.0
            elif syn_rate <= min_s - 0.10:
                syn_score = 0.0
            else:
                syn_score = (syn_rate - (min_s - 0.10)) / 0.10
            syn_score = max(0.0, min(1.0, syn_score))

            # --- Error logs (check for critical) ---
            all_errors = []
            err_page = 1
            while True:
                el_res = self.tools["get_error_logs"](
                    service_id=sid, environment="canary",
                    page=err_page, page_size=10)
                tool_calls += 1
                all_errors.extend(el_res["logs"])
                if err_page >= el_res["total_pages"]:
                    break
                err_page += 1
            has_crit = any(e["severity"] == "critical" for e in all_errors)

            # --- Feature flags ---
            fl_res = self.tools["get_feature_flags"](service_id=sid)
            tool_calls += 1
            svc_tgts = rollout_targets.get(sid, {})
            coverages = []
            for fl in fl_res["flags"]:
                fname = fl["flag_name"]
                if fname in svc_tgts:
                    tgt = svc_tgts[fname].get("target_rollout_pct", 0)
                    if tgt > 0:
                        coverages.append(fl["rollout_percentage"] / tgt)
            avg_cov = sum(coverages) / len(coverages) if coverages else 1.0
            min_fc = tc["min_flag_coverage"]
            if avg_cov >= min_fc:
                flag_score = 1.0
            else:
                flag_score = avg_cov / min_fc
            flag_score = max(0.0, min(1.0, flag_score))

            # Weighted score
            w_score = (lat_score * w["latency"]
                       + err_score * w["error_rate"]
                       + syn_score * w["synthetic_success"]
                       + flag_score * w["flag_coverage"])

            # Decision
            has_override = sid in manual_overrides
            if has_crit or has_override:
                decision = "ROLLBACK"
            elif w_score >= thr["promote"]:
                decision = "PROMOTE"
            elif w_score < thr["rollback"]:
                decision = "ROLLBACK"
            else:
                decision = "HOLD"

            report_rows.append({
                "service_id": sid,
                "service_name": details["service_name"],
                "tier": tier,
                "latency_degradation_pct": round(deg_pct, 4),
                "latency_score": round(lat_score, 4),
                "error_rate": round(avg_err, 4),
                "error_score": round(err_score, 4),
                "synthetic_success_rate": round(syn_rate, 4),
                "synthetic_score": round(syn_score, 4),
                "flag_coverage": round(avg_cov, 4),
                "flag_score": round(flag_score, 4),
                "weighted_score": round(w_score, 4),
                "has_critical_errors": "true" if has_crit else "false",
                "has_manual_override": "true" if has_override else "false",
                "decision": decision,
            })

        # Sort by service_id
        report_rows.sort(key=lambda x: x["service_id"])

        # Write decision_report.csv
        columns = [
            "service_id", "service_name", "tier",
            "latency_degradation_pct", "latency_score",
            "error_rate", "error_score",
            "synthetic_success_rate", "synthetic_score",
            "flag_coverage", "flag_score",
            "weighted_score", "has_critical_errors",
            "has_manual_override", "decision",
        ]
        csv_path = os.path.join(workspace, "decision_report.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(report_rows)

        # Compute overall
        promote_count = sum(1 for r in report_rows if r["decision"] == "PROMOTE")
        rollback_count = sum(1 for r in report_rows if r["decision"] == "ROLLBACK")
        hold_count = sum(1 for r in report_rows if r["decision"] == "HOLD")
        rollback_names = sorted(
            r["service_name"] for r in report_rows if r["decision"] == "ROLLBACK"
        )

        has_crit_rb = any(
            r["decision"] == "ROLLBACK" and r["tier"] == "critical"
            for r in report_rows
        )
        if has_crit_rb:
            overall = "ROLLBACK"
        elif promote_count == len(report_rows):
            overall = "PROMOTE"
        else:
            overall = "HOLD"

        # Write overall_summary.json
        summary = {
            "overall_decision": overall,
            "total_canary_services": len(report_rows),
            "promote_count": promote_count,
            "rollback_count": rollback_count,
            "hold_count": hold_count,
            "rollback_services": rollback_names,
        }
        with open(os.path.join(workspace, "overall_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # Construct action string
        action_lines = [
            f"Overall Decision: {overall}",
            f"Total canary services evaluated: {len(report_rows)}",
            f"Promote: {promote_count}, Rollback: {rollback_count}, Hold: {hold_count}",
        ]
        if rollback_names:
            action_lines.append(
                f"Rollback services: {', '.join(rollback_names)}"
            )
        action = "\n".join(action_lines)

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made (need >= 15)"

        return self.step(action)
