#!/usr/bin/env python3
"""Task environment for LLM inference routing optimization."""

import sqlite3
import os
import json
import csv
import re
import math
import glob
from typing import Tuple, Dict, List, Any

import numpy as np
import yaml
import pandas as pd


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
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

        # Snapshot original routing rules before any agent modifications
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM routing_rules")
        self._original_rules = {
            row["model_id"]: dict(row) for row in cur.fetchall()
        }
        conn.close()

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

    # ------------------------------------------------------------------ #
    #                          TOOL METHODS                                #
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "List models registered on the routing platform. "
            "Returns model_id, model_name, provider, tier, status, "
            "input_price_per_mtok, output_price_per_mtok, and max_context_tokens. "
            "Supports optional tier filter and pagination."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": ["economy", "standard", "premium", "enterprise"],
                    "description": "Filter by service tier. Omit to list all tiers.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_models(self, tier: str = None, page: int = 1, page_size: int = 20):
        page_size = min(int(page_size), 20)
        page = max(1, int(page))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if tier:
            cur.execute(
                "SELECT model_id, model_name, provider, tier, status, "
                "input_price_per_mtok, output_price_per_mtok, max_context_tokens "
                "FROM models WHERE tier = ? ORDER BY model_id",
                (tier,),
            )
        else:
            cur.execute(
                "SELECT model_id, model_name, provider, tier, status, "
                "input_price_per_mtok, output_price_per_mtok, max_context_tokens "
                "FROM models ORDER BY model_id"
            )
        all_rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        total = len(all_rows)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "models": all_rows[start:end],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if page_size else 1,
        }

    @tool(
        description=(
            "Compute latency percentiles (p50, p75, p90, p95, p99) for a "
            "specific model from recorded latency samples."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "The model identifier, e.g. 'M0001'.",
                },
            },
            "required": ["model_id"],
        },
    )
    def get_latency_percentiles(self, model_id: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT latency_ms FROM latency_samples WHERE model_id = ?",
            (model_id,),
        )
        values = [r[0] for r in cur.fetchall()]
        conn.close()
        if not values:
            return {"error": f"No latency samples found for {model_id}"}
        arr = np.array(values)
        return {
            "model_id": model_id,
            "sample_count": len(values),
            "p50": round(float(np.percentile(arr, 50)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "p90": round(float(np.percentile(arr, 90)), 2),
            "p95": round(float(np.percentile(arr, 95)), 2),
            "p99": round(float(np.percentile(arr, 99)), 2),
        }

    @tool(
        description=(
            "Query SLA violation incidents. Supports filtering by model_id, "
            "severity, and/or status. Returns paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "Filter by model. Omit to include all models.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Filter by severity level.",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "resolved", "investigating"],
                    "description": "Filter by incident status.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def query_sla_incidents(
        self,
        model_id: str = None,
        severity: str = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20,
    ):
        page_size = min(int(page_size), 20)
        page = max(1, int(page))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if model_id:
            clauses.append("model_id = ?")
            params.append(model_id)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM sla_incidents{where} ORDER BY incident_id", params
        )
        all_rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        total = len(all_rows)
        start = (page - 1) * page_size
        return {
            "incidents": all_rows[start : start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if page_size else 1,
        }

    @tool(
        description=(
            "Retrieve the current routing rule for a specific model, including "
            "priority, max_prompt_length, latency_ceiling_ms, cost_weight, "
            "and active flag."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "The model identifier.",
                },
            },
            "required": ["model_id"],
        },
    )
    def get_routing_rule(self, model_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM routing_rules WHERE model_id = ?", (model_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No routing rule found for {model_id}"}
        return dict(row)

    @tool(
        description=(
            "Update the routing rule for a model. Only the provided fields are "
            "changed; others remain as-is. Returns the updated rule."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "The model identifier.",
                },
                "priority": {
                    "type": "integer",
                    "description": "New priority value (lower = higher priority).",
                },
                "active": {
                    "type": "integer",
                    "description": "1 for active, 0 for inactive.",
                },
                "max_prompt_length": {
                    "type": "integer",
                    "description": "New maximum prompt length in tokens.",
                },
            },
            "required": ["model_id"],
        },
    )
    def update_routing_rule(
        self,
        model_id: str,
        priority: int = None,
        active: int = None,
        max_prompt_length: int = None,
    ):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM routing_rules WHERE model_id = ?", (model_id,))
        row = cur.fetchone()
        if row is None:
            conn.close()
            return {"error": f"No routing rule found for {model_id}"}
        sets, params = [], []
        if priority is not None:
            sets.append("priority = ?")
            params.append(int(priority))
        if active is not None:
            sets.append("active = ?")
            params.append(int(active))
        if max_prompt_length is not None:
            sets.append("max_prompt_length = ?")
            params.append(int(max_prompt_length))
        if sets:
            params.append(model_id)
            cur.execute(
                f"UPDATE routing_rules SET {', '.join(sets)} WHERE model_id = ?",
                params,
            )
            conn.commit()
        cur.execute("SELECT * FROM routing_rules WHERE model_id = ?", (model_id,))
        updated = dict(cur.fetchone())
        conn.close()
        return updated

    # ------------------------------------------------------------------ #
    #                           EVALUATION                                 #
    # ------------------------------------------------------------------ #

    def _compute_ground_truth(self):
        """Compute the full ground truth using direct DB + workspace access."""
        conn = sqlite3.connect(self.db_path)

        # ---------- read configs ----------
        with open(os.path.join(self.workspace, "tier_sla_policy.yaml")) as f:
            tier_policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "routing_formula.json")) as f:
            routing_formula = json.load(f)
        cost_adj = {}
        with open(os.path.join(self.workspace, "cost_adjustment.csv")) as f:
            for row in csv.DictReader(f):
                cost_adj[row["provider"]] = float(row["adjustment_factor"])

        # ---------- workspace data ----------
        quality_scores = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "model_benchmark_*.yaml"))):
            with open(fp) as f:
                data = yaml.safe_load(f)
            if data:
                for mid, info in data.items():
                    quality_scores[mid] = info["quality_score"]

        satisfaction_lists: Dict[str, list] = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "latency_window_*.csv"))):
            df = pd.read_csv(fp)
            for _, r in df.iterrows():
                satisfaction_lists.setdefault(r["model_id"], []).append(
                    float(r["client_satisfaction_score"])
                )
        avg_satisfaction = {
            mid: round(float(np.mean(vals)), 4)
            for mid, vals in satisfaction_lists.items()
        }

        impact_by_incident: Dict[int, float] = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "incident_detail_*.md"))):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(
                r"## Incident INC-(\d+).*?Estimated Impact: \$([0-9,]+(?:\.\d+)?)",
                content,
                re.DOTALL,
            ):
                impact_by_incident[int(m.group(1))] = float(
                    m.group(2).replace(",", "")
                )

        client_prefs: Dict[str, set] = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "request_pattern_*.json"))):
            with open(fp) as f:
                patterns = json.load(f)
            for p in patterns:
                for mid in p["preferred_models"]:
                    client_prefs.setdefault(mid, set()).add(p["client_id"])

        # ---------- DB data ----------
        models_df = pd.read_sql("SELECT * FROM models", conn)
        active_mask = models_df["status"] != "inactive"
        active_models = models_df[active_mask].copy()

        latency_df = pd.read_sql("SELECT model_id, latency_ms FROM latency_samples", conn)
        p95_map = (
            latency_df.groupby("model_id")["latency_ms"]
            .quantile(0.95)
            .to_dict()
        )

        incidents_df = pd.read_sql("SELECT * FROM sla_incidents", conn)
        conn.close()

        # ---------- formula params ----------
        ef = routing_formula["cost_effectiveness_formula"]
        q_w = ef["quality_weight"]
        s_w = ef["satisfaction_weight"]
        p_w = ef["price_weight"]
        prompt_thresh = routing_formula["prompt_length_thresholds"]
        adj_cfg = routing_formula["action_priority_adjustments"]
        demote_inc = adj_cfg["demote_priority_increase"]
        promote_dec = adj_cfg["promote_priority_decrease"]
        deact_pri = adj_cfg["deactivate_priority"]

        # ---------- per-model decisions ----------
        decisions = []
        for _, mdl in active_models.iterrows():
            mid = mdl["model_id"]
            tier = mdl["tier"]
            p95 = round(p95_map.get(mid, 0.0), 2)
            threshold = tier_policy[tier]["max_p95_latency_ms"]
            sla_ok = p95 <= threshold

            q = quality_scores.get(mid, 0.50)
            s = avg_satisfaction.get(mid, 0.50)
            af = cost_adj.get(mdl["provider"], 1.00)
            ip = mdl["input_price_per_mtok"]
            op = mdl["output_price_per_mtok"]
            denom = (ip + op) / 2.0 * af * p_w
            ce = (q * q_w + s * s_w) / denom if denom != 0 else 0.0
            cost_score = round(ce, 4)

            m_incs = incidents_df[incidents_df["model_id"] == mid]
            open_incs = m_incs[m_incs["status"] == "open"]
            n_open = len(open_incs)
            n_crit_high_open = len(
                open_incs[open_incs["severity"].isin(["critical", "high"])]
            )

            orig = self._original_rules.get(mid, {})
            orig_pri = orig.get("priority", 50)
            orig_active = orig.get("active", 1)
            orig_mpl = orig.get("max_prompt_length", prompt_thresh.get(tier, 8000))

            cit = tier_policy[tier]["critical_incident_threshold"]
            moi = tier_policy[tier]["max_open_incidents"]

            if not sla_ok and n_crit_high_open >= cit:
                action = "deactivate"
                new_pri = deact_pri
                new_active = 0
            elif not sla_ok:
                action = "demote"
                new_pri = orig_pri + demote_inc
                new_active = orig_active
            elif n_open > moi:
                action = "flag_review"
                new_pri = orig_pri
                new_active = orig_active
            else:
                action = "maintain"
                new_pri = orig_pri
                new_active = orig_active

            # expected prompt length
            expected_mpl = prompt_thresh.get(tier, orig_mpl)

            # impact & clients for violation report
            inc_ids = m_incs["incident_id"].tolist()
            total_impact = round(
                sum(impact_by_incident.get(iid, 0.0) for iid in inc_ids), 2
            )
            affected_clients = len(client_prefs.get(mid, set()))

            decisions.append({
                "model_id": mid,
                "model_name": mdl["model_name"],
                "provider": mdl["provider"],
                "tier": tier,
                "p95_latency_ms": p95,
                "sla_compliant": sla_ok,
                "cost_score": cost_score,
                "open_incidents": n_open,
                "orig_priority": orig_pri,
                "new_priority": new_pri,
                "new_active": new_active,
                "action": action,
                "expected_mpl": expected_mpl,
                "orig_mpl": orig_mpl,
                "total_impact_dollars": total_impact,
                "affected_client_count": affected_clients,
                "n_crit_high_open": n_crit_high_open,
            })

        # ---------- promotions ----------
        for tier in ["economy", "standard", "premium", "enterprise"]:
            maintain_in_tier = [
                d for d in decisions if d["tier"] == tier and d["action"] == "maintain"
            ]
            if not maintain_in_tier:
                continue
            pct = tier_policy[tier]["promote_top_pct"]
            n_promote = max(1, len(maintain_in_tier) * pct // 100)
            n_promote = min(n_promote, len(maintain_in_tier))
            maintain_in_tier.sort(key=lambda x: x["cost_score"], reverse=True)
            for d in maintain_in_tier[:n_promote]:
                d["action"] = "promote"
                d["new_priority"] = max(1, d["orig_priority"] - promote_dec)

        # ---------- violation report ----------
        violators = [d for d in decisions if not d["sla_compliant"]]
        by_tier: Dict[str, int] = {}
        by_severity: Dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for v in violators:
            by_tier[v["tier"]] = by_tier.get(v["tier"], 0) + 1
            v_incs = incidents_df[
                (incidents_df["model_id"] == v["model_id"])
                & (incidents_df["status"] == "open")
            ]
            for _, inc in v_incs.iterrows():
                by_severity[inc["severity"]] = by_severity.get(inc["severity"], 0) + 1

        top_violators = sorted(
            violators, key=lambda x: x["total_impact_dollars"], reverse=True
        )
        top_violators_out = [
            {
                "model_id": v["model_id"],
                "model_name": v["model_name"],
                "open_incident_count": v["open_incidents"],
                "total_impact_dollars": v["total_impact_dollars"],
                "affected_client_count": v["affected_client_count"],
            }
            for v in top_violators
        ]
        n_active = len(decisions)
        n_compliant = sum(1 for d in decisions if d["sla_compliant"])
        compliance_rate = round(n_compliant / n_active * 100, 2) if n_active else 0.0

        violation_report = {
            "total_violations": len(violators),
            "by_tier": by_tier,
            "by_severity": by_severity,
            "top_violators": top_violators_out,
            "overall_sla_compliance_rate": f"{compliance_rate:.2f}%",
        }

        # ---------- summary stats ----------
        most_ce_per_tier = {}
        for tier in ["economy", "standard", "premium", "enterprise"]:
            tier_decs = [d for d in decisions if d["tier"] == tier]
            if tier_decs:
                best = max(tier_decs, key=lambda x: x["cost_score"])
                most_ce_per_tier[tier] = (best["model_id"], best["cost_score"])

        n_updates = sum(
            1
            for d in decisions
            if (
                d["action"] in ("deactivate", "demote", "promote")
                or d["expected_mpl"] != d["orig_mpl"]
            )
        )
        action_counts = {}
        for d in decisions:
            action_counts[d["action"]] = action_counts.get(d["action"], 0) + 1

        return {
            "decisions": decisions,
            "violation_report": violation_report,
            "most_ce_per_tier": most_ce_per_tier,
            "n_active": n_active,
            "n_violating": len(violators),
            "n_updates": n_updates,
            "action_counts": action_counts,
            "prompt_thresh": prompt_thresh,
        }

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
        gt = self._compute_ground_truth()
        decisions = gt["decisions"]
        vr_expected = gt["violation_report"]
        prompt_thresh = gt["prompt_thresh"]

        total_score = 0
        max_score = 100
        eval_criteria = {}

        # ===================== 1. SLA compliance (15 pts) =====================
        csv_path = os.path.join(self.workspace, "routing_decisions.csv")
        sla_score = 0
        sla_max = 15
        if os.path.exists(csv_path):
            try:
                agent_df = pd.read_csv(csv_path, dtype=str)
                gt_sla = {d["model_id"]: "yes" if d["sla_compliant"] else "no" for d in decisions}
                correct = 0
                for _, row in agent_df.iterrows():
                    mid = row.get("model_id", "")
                    agent_val = str(row.get("sla_compliant", "")).strip().lower()
                    if gt_sla.get(mid) == agent_val:
                        correct += 1
                if gt_sla:
                    sla_score = round(sla_max * correct / len(gt_sla), 1)
            except Exception:
                pass
        eval_criteria["sla_compliance_identification"] = {
            "passed": sla_score == sla_max,
            "score": sla_score,
            "max_score": sla_max,
            **({"reason": "routing_decisions.csv missing or incorrect sla_compliant values"} if sla_score < sla_max else {}),
        }
        total_score += sla_score

        # ===================== 2. Cost scores (15 pts) =====================
        cost_score_pts = 0
        cost_max = 15
        if os.path.exists(csv_path):
            try:
                agent_df = pd.read_csv(csv_path)
                gt_cs = {d["model_id"]: d["cost_score"] for d in decisions}
                correct = 0
                for _, row in agent_df.iterrows():
                    mid = str(row.get("model_id", ""))
                    try:
                        agent_cs = round(float(row.get("cost_score", 0)), 4)
                    except (ValueError, TypeError):
                        continue
                    expected = gt_cs.get(mid)
                    if expected is not None and abs(agent_cs - expected) < 0.02:
                        correct += 1
                if gt_cs:
                    cost_score_pts = round(cost_max * correct / len(gt_cs), 1)
            except Exception:
                pass
        eval_criteria["cost_effectiveness_scores"] = {
            "passed": cost_score_pts == cost_max,
            "score": cost_score_pts,
            "max_score": cost_max,
            **({"reason": "cost_score values incorrect or missing"} if cost_score_pts < cost_max else {}),
        }
        total_score += cost_score_pts

        # ===================== 3. Action determination (20 pts) =====================
        action_score = 0
        action_max = 20
        if os.path.exists(csv_path):
            try:
                agent_df = pd.read_csv(csv_path, dtype=str)
                gt_actions = {d["model_id"]: d["action"] for d in decisions}
                correct = 0
                for _, row in agent_df.iterrows():
                    mid = str(row.get("model_id", ""))
                    agent_act = str(row.get("action", "")).strip().lower()
                    if gt_actions.get(mid) == agent_act:
                        correct += 1
                if gt_actions:
                    action_score = round(action_max * correct / len(gt_actions), 1)
            except Exception:
                pass
        eval_criteria["action_determination"] = {
            "passed": action_score == action_max,
            "score": action_score,
            "max_score": action_max,
            **({"reason": "action values incorrect or missing"} if action_score < action_max else {}),
        }
        total_score += action_score

        # ===================== 4. Routing rule updates (20 pts) =====================
        rule_score = 0
        rule_max = 20
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM routing_rules")
        current_rules = {row["model_id"]: dict(row) for row in cur.fetchall()}
        conn.close()

        checks_total = 0
        checks_ok = 0
        for d in decisions:
            mid = d["model_id"]
            cr = current_rules.get(mid, {})
            # Check priority
            checks_total += 1
            if cr.get("priority") == d["new_priority"]:
                checks_ok += 1
            # Check active
            checks_total += 1
            if cr.get("active") == d["new_active"]:
                checks_ok += 1
            # Check max_prompt_length
            checks_total += 1
            if cr.get("max_prompt_length") == d["expected_mpl"]:
                checks_ok += 1
        if checks_total:
            rule_score = round(rule_max * checks_ok / checks_total, 1)

        eval_criteria["routing_rule_updates"] = {
            "passed": rule_score == rule_max,
            "score": rule_score,
            "max_score": rule_max,
            **({"reason": f"DB routing rules mismatch: {checks_ok}/{checks_total} fields correct"} if rule_score < rule_max else {}),
        }
        total_score += rule_score

        # ===================== 5. Violation report (15 pts) =====================
        vr_score = 0
        vr_max = 15
        vr_path = os.path.join(self.workspace, "violation_report.json")
        if os.path.exists(vr_path):
            try:
                with open(vr_path) as f:
                    agent_vr = json.load(f)
                sub_checks = 5
                sub_ok = 0
                # total_violations
                if agent_vr.get("total_violations") == vr_expected["total_violations"]:
                    sub_ok += 1
                # by_tier
                if agent_vr.get("by_tier") == vr_expected["by_tier"]:
                    sub_ok += 1
                # by_severity
                if agent_vr.get("by_severity") == vr_expected["by_severity"]:
                    sub_ok += 1
                # overall_sla_compliance_rate
                if str(agent_vr.get("overall_sla_compliance_rate", "")).strip() == vr_expected["overall_sla_compliance_rate"]:
                    sub_ok += 1
                # top_violators (check model_ids match in order)
                expected_ids = [v["model_id"] for v in vr_expected["top_violators"]]
                agent_ids = [v.get("model_id") for v in agent_vr.get("top_violators", [])]
                if agent_ids == expected_ids:
                    sub_ok += 1
                vr_score = round(vr_max * sub_ok / sub_checks, 1)
            except Exception:
                pass
        eval_criteria["violation_report"] = {
            "passed": vr_score == vr_max,
            "score": vr_score,
            "max_score": vr_max,
            **({"reason": "violation_report.json missing or has incorrect fields"} if vr_score < vr_max else {}),
        }
        total_score += vr_score

        # ===================== 6. Response summary (15 pts) =====================
        resp_score = 0
        resp_max = 15
        if action:
            sub_checks = 5
            sub_ok = 0
            resp = str(action)
            # total active models
            if str(gt["n_active"]) in resp:
                sub_ok += 1
            # number of violations
            if str(gt["n_violating"]) in resp:
                sub_ok += 1
            # most cost-effective per tier: check at least 2 tiers
            ce_found = 0
            for tier, (mid, score) in gt["most_ce_per_tier"].items():
                if mid in resp:
                    ce_found += 1
            if ce_found >= 2:
                sub_ok += 1
            # number of updates
            if str(gt["n_updates"]) in resp:
                sub_ok += 1
            # action counts: check deactivated/demoted counts
            ac = gt["action_counts"]
            counts_found = 0
            for act_name in ["deactivate", "demote", "promote", "flag_review"]:
                cnt = ac.get(act_name, 0)
                if cnt > 0 and str(cnt) in resp:
                    counts_found += 1
            if counts_found >= 2:
                sub_ok += 1
            resp_score = round(resp_max * sub_ok / sub_checks, 1)

        eval_criteria["response_summary"] = {
            "passed": resp_score == resp_max,
            "score": resp_score,
            "max_score": resp_max,
            **({"reason": "Response missing required summary statistics"} if resp_score < resp_max else {}),
        }
        total_score += resp_score

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # ------------------------------------------------------------------ #
    #                          VERIFICATION                                #
    # ------------------------------------------------------------------ #

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
        # ---- 1. Read config files ----
        with open(os.path.join(self.workspace, "tier_sla_policy.yaml")) as f:
            tier_policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "routing_formula.json")) as f:
            routing_formula = json.load(f)

        cost_adj = {}
        with open(os.path.join(self.workspace, "cost_adjustment.csv")) as f:
            for row in csv.DictReader(f):
                cost_adj[row["provider"]] = float(row["adjustment_factor"])

        # ---- 2. Read workspace data files ----
        quality_scores = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "model_benchmark_*.yaml"))):
            with open(fp) as f:
                data = yaml.safe_load(f)
            if data:
                for mid, info in data.items():
                    quality_scores[mid] = info["quality_score"]

        satisfaction_lists: Dict[str, list] = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "latency_window_*.csv"))):
            df = pd.read_csv(fp)
            for _, r in df.iterrows():
                satisfaction_lists.setdefault(r["model_id"], []).append(
                    float(r["client_satisfaction_score"])
                )
        avg_satisfaction = {
            mid: round(float(np.mean(vals)), 4)
            for mid, vals in satisfaction_lists.items()
        }

        impact_by_incident: Dict[int, float] = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "incident_detail_*.md"))):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(
                r"## Incident INC-(\d+).*?Estimated Impact: \$([0-9,]+(?:\.\d+)?)",
                content,
                re.DOTALL,
            ):
                impact_by_incident[int(m.group(1))] = float(
                    m.group(2).replace(",", "")
                )

        client_prefs: Dict[str, set] = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "request_pattern_*.json"))):
            with open(fp) as f:
                patterns = json.load(f)
            for p in patterns:
                for mid in p["preferred_models"]:
                    client_prefs.setdefault(mid, set()).add(p["client_id"])

        # ---- 3. Gather model data via tools ----
        all_models = []
        for tier in ["economy", "standard", "premium", "enterprise"]:
            page = 1
            while True:
                result = self.tools["list_models"](tier=tier, page=page, page_size=20)
                all_models.extend(result["models"])
                if page >= result["total_pages"]:
                    break
                page += 1

        active_models = [m for m in all_models if m["status"] != "inactive"]

        # ---- 4. Get latency percentiles for each active model ----
        latency_map = {}
        for m in active_models:
            lp = self.tools["get_latency_percentiles"](model_id=m["model_id"])
            if "error" not in lp:
                latency_map[m["model_id"]] = lp

        # ---- 5. Get ALL incidents (paginated) ----
        all_incidents = []
        page = 1
        while True:
            result = self.tools["query_sla_incidents"](page=page, page_size=20)
            all_incidents.extend(result["incidents"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Group by model
        model_incidents: Dict[str, list] = {}
        for inc in all_incidents:
            model_incidents.setdefault(inc["model_id"], []).append(inc)

        # ---- 6. Get routing rules for all active models ----
        routing_rules_map = {}
        for m in active_models:
            rr = self.tools["get_routing_rule"](model_id=m["model_id"])
            if "error" not in rr:
                routing_rules_map[m["model_id"]] = rr

        # ---- 7. Compute decisions ----
        ef = routing_formula["cost_effectiveness_formula"]
        q_w = ef["quality_weight"]
        s_w = ef["satisfaction_weight"]
        p_w = ef["price_weight"]
        prompt_thresh = routing_formula["prompt_length_thresholds"]
        adj_cfg = routing_formula["action_priority_adjustments"]
        demote_inc = adj_cfg["demote_priority_increase"]
        promote_dec = adj_cfg["promote_priority_decrease"]
        deact_pri = adj_cfg["deactivate_priority"]

        decisions = []
        for m in active_models:
            mid = m["model_id"]
            tier = m["tier"]
            lp = latency_map.get(mid, {})
            p95 = round(lp.get("p95", 0.0), 2)
            threshold = tier_policy[tier]["max_p95_latency_ms"]
            sla_ok = p95 <= threshold

            q = quality_scores.get(mid, 0.50)
            s = avg_satisfaction.get(mid, 0.50)
            af = cost_adj.get(m["provider"], 1.00)
            ip = m["input_price_per_mtok"]
            op = m["output_price_per_mtok"]
            denom = (ip + op) / 2.0 * af * p_w
            ce = (q * q_w + s * s_w) / denom if denom != 0 else 0.0
            cost_score = round(ce, 4)

            m_incs = model_incidents.get(mid, [])
            open_incs = [i for i in m_incs if i["status"] == "open"]
            n_open = len(open_incs)
            n_crit_high = len(
                [i for i in open_incs if i["severity"] in ("critical", "high")]
            )

            rr = routing_rules_map.get(mid, {})
            orig_pri = rr.get("priority", 50)
            orig_active = rr.get("active", 1)
            orig_mpl = rr.get("max_prompt_length", prompt_thresh.get(tier, 8000))

            cit = tier_policy[tier]["critical_incident_threshold"]
            moi = tier_policy[tier]["max_open_incidents"]

            if not sla_ok and n_crit_high >= cit:
                act = "deactivate"
                new_pri = deact_pri
                new_active = 0
            elif not sla_ok:
                act = "demote"
                new_pri = orig_pri + demote_inc
                new_active = orig_active
            elif n_open > moi:
                act = "flag_review"
                new_pri = orig_pri
                new_active = orig_active
            else:
                act = "maintain"
                new_pri = orig_pri
                new_active = orig_active

            expected_mpl = prompt_thresh.get(tier, orig_mpl)

            inc_ids = [i["incident_id"] for i in m_incs]
            total_impact = round(
                sum(impact_by_incident.get(iid, 0.0) for iid in inc_ids), 2
            )
            affected_clients = len(client_prefs.get(mid, set()))

            decisions.append({
                "model_id": mid,
                "model_name": m["model_name"],
                "tier": tier,
                "p95_latency_ms": p95,
                "sla_compliant": sla_ok,
                "cost_score": cost_score,
                "open_incidents": n_open,
                "orig_priority": orig_pri,
                "new_priority": new_pri,
                "new_active": new_active,
                "action": act,
                "expected_mpl": expected_mpl,
                "orig_mpl": orig_mpl,
                "total_impact_dollars": total_impact,
                "affected_client_count": affected_clients,
            })

        # ---- 8. Promotions ----
        for tier in ["economy", "standard", "premium", "enterprise"]:
            maintain = [d for d in decisions if d["tier"] == tier and d["action"] == "maintain"]
            if not maintain:
                continue
            pct = tier_policy[tier]["promote_top_pct"]
            n_promote = max(1, len(maintain) * pct // 100)
            n_promote = min(n_promote, len(maintain))
            maintain.sort(key=lambda x: x["cost_score"], reverse=True)
            for d in maintain[:n_promote]:
                d["action"] = "promote"
                d["new_priority"] = max(1, d["orig_priority"] - promote_dec)

        # ---- 9. Execute routing rule updates ----
        n_updates = 0
        for d in decisions:
            mid = d["model_id"]
            kwargs: Dict[str, Any] = {}
            if d["action"] in ("deactivate", "demote", "promote"):
                kwargs["priority"] = d["new_priority"]
            if d["action"] == "deactivate":
                kwargs["active"] = 0
            if d["expected_mpl"] != d["orig_mpl"]:
                kwargs["max_prompt_length"] = d["expected_mpl"]
            if kwargs:
                self.tools["update_routing_rule"](model_id=mid, **kwargs)
                n_updates += 1

        # ---- 10. Write routing_decisions.csv ----
        sorted_decisions = sorted(
            decisions, key=lambda d: (d["tier"], d["new_priority"], d["model_id"])
        )
        csv_path = os.path.join(self.workspace, "routing_decisions.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "model_id", "model_name", "tier", "p95_latency_ms",
                "sla_compliant", "cost_score", "open_incidents",
                "new_priority", "action",
            ])
            for d in sorted_decisions:
                writer.writerow([
                    d["model_id"],
                    d["model_name"],
                    d["tier"],
                    f"{d['p95_latency_ms']:.2f}",
                    "yes" if d["sla_compliant"] else "no",
                    f"{d['cost_score']:.4f}",
                    d["open_incidents"],
                    d["new_priority"],
                    d["action"],
                ])

        # ---- 11. Write violation_report.json ----
        violators = [d for d in decisions if not d["sla_compliant"]]
        by_tier: Dict[str, int] = {}
        by_severity: Dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for v in violators:
            by_tier[v["tier"]] = by_tier.get(v["tier"], 0) + 1
            v_incs = [i for i in model_incidents.get(v["model_id"], []) if i["status"] == "open"]
            for inc in v_incs:
                by_severity[inc["severity"]] = by_severity.get(inc["severity"], 0) + 1

        top_violators = sorted(
            violators, key=lambda x: x["total_impact_dollars"], reverse=True
        )
        top_violators_out = [
            {
                "model_id": v["model_id"],
                "model_name": v["model_name"],
                "open_incident_count": v["open_incidents"],
                "total_impact_dollars": v["total_impact_dollars"],
                "affected_client_count": v["affected_client_count"],
            }
            for v in top_violators
        ]
        n_active = len(decisions)
        n_compliant = sum(1 for d in decisions if d["sla_compliant"])
        compliance_rate = round(n_compliant / n_active * 100, 2) if n_active else 0.0

        vr_out = {
            "total_violations": len(violators),
            "by_tier": by_tier,
            "by_severity": by_severity,
            "top_violators": top_violators_out,
            "overall_sla_compliance_rate": f"{compliance_rate:.2f}%",
        }
        with open(os.path.join(self.workspace, "violation_report.json"), "w") as f:
            json.dump(vr_out, f, indent=2)

        # ---- 12. Build response text ----
        most_ce = {}
        for tier in ["economy", "standard", "premium", "enterprise"]:
            tier_decs = [d for d in decisions if d["tier"] == tier]
            if tier_decs:
                best = max(tier_decs, key=lambda x: x["cost_score"])
                most_ce[tier] = (best["model_id"], best["cost_score"])

        action_counts: Dict[str, int] = {}
        for d in decisions:
            action_counts[d["action"]] = action_counts.get(d["action"], 0) + 1

        ce_parts = ", ".join(
            f"{t}: {mid} ({score:.4f})" for t, (mid, score) in most_ce.items()
        )
        act_parts = ", ".join(
            f"{act.replace('_', ' ').title()}: {cnt}"
            for act, cnt in sorted(action_counts.items())
            if cnt > 0
        )
        n_violating = len(violators)
        response = (
            f"Analysis complete. "
            f"Total active models analyzed: {n_active}. "
            f"SLA-violating models: {n_violating}. "
            f"Most cost-effective by tier: {ce_parts}. "
            f"Routing rule updates performed: {n_updates}. "
            f"Action summary - {act_parts}."
        )

        return self.step(response)
