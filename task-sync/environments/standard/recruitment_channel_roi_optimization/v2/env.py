"""
Environment for Recruitment Channel ROI Optimization task.
"""

import sqlite3
import os
import json
import csv
import glob
import math
from typing import Tuple, Dict, List, Any
from collections import defaultdict


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

    # ─────────────────────────────────────────────
    # Tool methods
    # ─────────────────────────────────────────────

    @tool(
        description="Returns a list of all recruitment sources with their IDs, names, and channel types.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_recruitment_sources(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT source_id, name, type FROM sources ORDER BY source_id").fetchall()
        conn.close()
        return json.dumps([{"source_id": r[0], "name": r[1], "type": r[2]} for r in rows], ensure_ascii=False, default=str)

    @tool(
        description="Returns a list of all departments with their IDs and names.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_departments(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT dept_id, name FROM departments ORDER BY dept_id").fetchall()
        conn.close()
        return _envelope([{"dept_id": r[0], "name": r[1]} for r in rows])

    @tool(
        description=(
            "Returns hiring volume statistics for a given source and department: "
            "total candidates, number hired, and hire rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_id": {"type": "integer", "description": "The recruitment source ID."},
                "department": {"type": "string", "description": "Department name (e.g. 'Engineering')."},
            },
            "required": ["source_id", "department"],
        },
    )
    def get_hiring_volume(self, source_id: int, department: str):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """SELECT COUNT(*), SUM(CASE WHEN c.status='hired' THEN 1 ELSE 0 END)
               FROM candidates c JOIN departments d ON c.dept_id=d.dept_id
               WHERE c.source_id=? AND d.name=?""",
            (source_id, department),
        ).fetchone()
        conn.close()
        total, hired = row[0], row[1] or 0
        return json.dumps({"total_candidates": total, "hired": hired,
                "hire_rate": round(hired / total, 4) if total else 0.0}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns time-to-hire statistics (average and median days from application to hire) "
            "for a given source and department. Only includes hired candidates."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_id": {"type": "integer", "description": "The recruitment source ID."},
                "department": {"type": "string", "description": "Department name."},
            },
            "required": ["source_id", "department"],
        },
    )
    def get_time_to_hire(self, source_id: int, department: str):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT julianday(c.hired_date) - julianday(c.applied_date)
               FROM candidates c JOIN departments d ON c.dept_id=d.dept_id
               WHERE c.source_id=? AND d.name=? AND c.status='hired'""",
            (source_id, department),
        ).fetchall()
        conn.close()
        days = sorted(r[0] for r in rows if r[0] is not None)
        if not days:
            return json.dumps({"avg_days": None, "median_days": None, "count": 0}, ensure_ascii=False, default=str)
        n = len(days)
        median = days[n // 2] if n % 2 else (days[n // 2 - 1] + days[n // 2]) / 2
        return json.dumps({"avg_days": round(sum(days) / n, 2), "median_days": round(median, 2), "count": n}, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Returns first-year retention data for hired candidates from a given source and department: "
            "total hires with retention records, count retained at 12 months, and retention rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_id": {"type": "integer", "description": "The recruitment source ID."},
                "department": {"type": "string", "description": "Department name."},
            },
            "required": ["source_id", "department"],
        },
    )
    def get_retention_rate(self, source_id: int, department: str):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """SELECT COUNT(*), SUM(r.is_active_at_12m)
               FROM retention r JOIN candidates c ON r.candidate_id=c.candidate_id
               JOIN departments d ON c.dept_id=d.dept_id
               WHERE c.source_id=? AND d.name=?""",
            (source_id, department),
        ).fetchone()
        conn.close()
        total, retained = row[0] or 0, row[1] or 0
        return _envelope({"total_hired": total, "retained_12m": retained,
                "retention_rate": round(retained / total, 4) if total else 0.0})

    @tool(
        description=(
            "Returns average internal hiring cost for hired candidates from a given source "
            "and department. Covers recruiter time, interview panel time, and admin costs. "
            "Does NOT include external channel fees (see channel pricing configuration)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_id": {"type": "integer", "description": "The recruitment source ID."},
                "department": {"type": "string", "description": "Department name."},
            },
            "required": ["source_id", "department"],
        },
    )
    def get_internal_cost(self, source_id: int, department: str):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """SELECT AVG(hc.recruiter_hours), AVG(hc.interview_hours),
                      AVG(hc.admin_cost), AVG(hc.total_internal_cost)
               FROM hiring_costs hc JOIN candidates c ON hc.candidate_id=c.candidate_id
               JOIN departments d ON c.dept_id=d.dept_id
               WHERE c.source_id=? AND d.name=? AND c.status='hired'""",
            (source_id, department),
        ).fetchone()
        conn.close()
        if row[0] is None:
            return _envelope({"avg_recruiter_hours": 0, "avg_interview_hours": 0,
                    "avg_admin_cost": 0, "avg_internal_cost": 0})
        return _envelope({
            "avg_recruiter_hours": round(row[0], 2),
            "avg_interview_hours": round(row[1], 2),
            "avg_admin_cost": round(row[2], 2),
            "avg_internal_cost": round(row[3], 2),
        })

    @tool(
        description=(
            "Returns the number of hires from a specific recruitment source in a specific quarter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_id": {"type": "integer", "description": "The recruitment source ID."},
                "quarter": {"type": "string", "description": "Quarter string, e.g. '2025-Q4'."},
            },
            "required": ["source_id", "quarter"],
        },
    )
    def get_quarterly_hires(self, source_id: int, quarter: str):
        conn = sqlite3.connect(self.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE source_id=? AND quarter=? AND status='hired'",
            (source_id, quarter),
        ).fetchone()[0]
        conn.close()
        return json.dumps({"source_id": source_id, "quarter": quarter, "hires": count}, ensure_ascii=False, default=str)

    # ─────────────────────────────────────────────
    # Ground-truth computation (used by step)
    # ─────────────────────────────────────────────

    def _compute_ground_truth(self):
        import yaml

        conn = sqlite3.connect(self.db_path)
        sources = [{"source_id": r[0], "name": r[1], "type": r[2]}
                    for r in conn.execute("SELECT source_id, name, type FROM sources ORDER BY source_id")]
        departments = [{"dept_id": r[0], "name": r[1]}
                       for r in conn.execute("SELECT dept_id, name FROM departments ORDER BY dept_id")]

        with open(os.path.join(self.workspace, "channel_pricing.yaml")) as f:
            pricing = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "kpi_formula.json")) as f:
            kpi_cfg = json.load(f)
        with open(os.path.join(self.workspace, "quarterly_targets.csv")) as f:
            targets = list(csv.DictReader(f))
        total_budget = float(targets[0]["total_budget"])
        w = kpi_cfg["quality_of_hire_weights"]

        # ── Load workspace data keyed by (source_name, department) ──
        interview_by_pair = defaultdict(list)
        for fp in sorted(glob.glob(os.path.join(self.workspace, "interview_scores_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    key = (row["source_name"], row["department"])
                    avg3 = (float(row["technical_score"]) + float(row["behavioral_score"])
                            + float(row["cultural_fit_score"])) / 3
                    interview_by_pair[key].append(avg3)

        mgr_by_pair = defaultdict(list)
        for fp in sorted(glob.glob(os.path.join(self.workspace, "manager_reviews_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    mgr_by_pair[(rec["source_name"], rec["department"])].append(float(rec["manager_satisfaction"]))

        onb_by_pair = defaultdict(list)
        for fp in sorted(glob.glob(os.path.join(self.workspace, "onboarding_metrics_*.yaml"))):
            with open(fp) as f:
                for rec in yaml.safe_load(f):
                    onb_by_pair[(rec["source_name"], rec["department"])].append(float(rec["completion_pct"]))

        results = {}
        for src in sources:
            sid, sname, stype = src["source_id"], src["name"], src["type"]
            for dept in departments:
                did, dname = dept["dept_id"], dept["name"]
                key = (sname, dname)

                # Hiring volume
                row = conn.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN status='hired' THEN 1 ELSE 0 END) "
                    "FROM candidates WHERE source_id=? AND dept_id=?", (sid, did),
                ).fetchone()
                n_hired = row[1] or 0

                # Time-to-hire
                days = [r[0] for r in conn.execute(
                    "SELECT julianday(hired_date)-julianday(applied_date) "
                    "FROM candidates WHERE source_id=? AND dept_id=? AND status='hired'",
                    (sid, did),
                ) if r[0] is not None]
                avg_days = sum(days) / len(days) if days else 0

                # Retention
                rr = conn.execute(
                    "SELECT COUNT(*), SUM(r.is_active_at_12m) "
                    "FROM retention r JOIN candidates c ON r.candidate_id=c.candidate_id "
                    "WHERE c.source_id=? AND c.dept_id=?", (sid, did),
                ).fetchone()
                retention_rate = (rr[1] or 0) / rr[0] if rr[0] else 0

                # Internal cost (hired only)
                ic = conn.execute(
                    "SELECT AVG(hc.total_internal_cost) "
                    "FROM hiring_costs hc JOIN candidates c ON hc.candidate_id=c.candidate_id "
                    "WHERE c.source_id=? AND c.dept_id=? AND c.status='hired'",
                    (sid, did),
                ).fetchone()[0] or 0

                # External fee
                if stype == "job_board":
                    q4h = conn.execute(
                        "SELECT COUNT(*) FROM candidates WHERE source_id=? AND quarter='2025-Q4' AND status='hired'",
                        (sid,),
                    ).fetchone()[0]
                    phf = pricing["source_fees"]["job_board"]["per_hire_fee"]
                    qpf = pricing["source_fees"]["job_board"]["quarterly_posting_fee"]
                    ext = phf + (qpf / q4h if q4h else qpf)
                elif stype == "referral":
                    ext = pricing["source_fees"]["referral"]["referral_bonus"]
                else:
                    ext = pricing["source_fees"]["agency"]["placement_fee_pct"] * pricing["department_avg_salary"][dname]

                cph = ic + ext
                te = max(0, 1 - avg_days / 60)

                iv = interview_by_pair.get(key, [])
                iq = (sum(iv) / len(iv) / 5) if iv else 0
                mv = mgr_by_pair.get(key, [])
                ms = (sum(mv) / len(mv) / 5) if mv else 0
                ov = onb_by_pair.get(key, [])
                ob = (sum(ov) / len(ov) / 100) if ov else 0

                qs = (w["retention_rate"] * retention_rate
                      + w["time_to_hire_efficiency"] * te
                      + w["interview_quality"] * iq
                      + w["manager_satisfaction"] * ms
                      + w["onboarding_success"] * ob)

                es = qs / cph * 10000 if cph > 0 else 0

                results[key] = {
                    "n_hired": n_hired, "avg_days": round(avg_days, 2),
                    "retention_rate": round(retention_rate, 4),
                    "total_cost_per_hire": round(cph, 2),
                    "quality_score": round(qs, 4), "efficiency_score": round(es, 4),
                }

        conn.close()

        # Budget allocation
        snames = [s["name"] for s in sources]
        dnames = [d["name"] for d in departments]
        allocation = self._allocate_budget(results, snames, dnames, total_budget)
        return results, allocation, total_budget

    @staticmethod
    def _allocate_budget(results, snames, dnames, total_budget):
        raw_w = {k: r["efficiency_score"] * r["n_hired"] for k, r in results.items()}
        tw = sum(raw_w.values())
        raw_pct = {k: v / tw if tw else 0 for k, v in raw_w.items()}

        src_pct = {sn: sum(raw_pct.get((sn, dn), 0) for dn in dnames) for sn in snames}
        adj = dict(src_pct)
        MIN_P, MAX_P = 0.08, 0.35
        for _ in range(20):
            clamped, free, excess = {}, {}, 0.0
            for sn in snames:
                p = adj[sn]
                if p < MIN_P:
                    clamped[sn] = MIN_P; excess -= (MIN_P - p)
                elif p > MAX_P:
                    clamped[sn] = MAX_P; excess += (p - MAX_P)
                else:
                    free[sn] = p
            if not clamped or abs(excess) < 1e-10:
                break
            ft = sum(free.values())
            for sn in free:
                adj[sn] = free[sn] + excess * (free[sn] / ft) if ft else free[sn]
            for sn in clamped:
                adj[sn] = clamped[sn]

        ta = sum(adj.values())
        if ta:
            adj = {k: v / ta for k, v in adj.items()}

        alloc = {}
        for sn in snames:
            dw = {dn: raw_w.get((sn, dn), 0) for dn in dnames}
            dt = sum(dw.values())
            for dn in dnames:
                df = dw[dn] / dt if dt else 1 / len(dnames)
                ab = round(adj[sn] * df * total_budget)
                cph = results[(sn, dn)]["total_cost_per_hire"]
                alloc[(sn, dn)] = {
                    "allocated_budget": ab,
                    "expected_hires": round(ab / cph, 1) if cph else 0,
                    "cost_per_hire_estimate": round(cph, 2),
                }
        return alloc

    # ─────────────────────────────────────────────
    # step
    # ─────────────────────────────────────────────

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
        gt_results, gt_alloc, total_budget = self._compute_ground_truth()
        ec = {}
        ts, ms = 0, 0

        # ── C1: budget_allocation.csv structure (10 pts) ──
        bp = os.path.join(self.workspace, "budget_allocation.csv")
        bd = []
        c1 = 0
        req_cols = {"source", "department", "allocated_budget", "expected_hires", "cost_per_hire_estimate"}
        if os.path.exists(bp):
            try:
                with open(bp) as f:
                    rdr = csv.DictReader(f); bd = list(rdr)
                if req_cols.issubset(set(rdr.fieldnames or [])):
                    c1 = 10
            except Exception:
                pass
        ec["budget_file_structure"] = {"passed": c1 == 10, "score": c1, "max_score": 10,
                                       "reason": "" if c1 else f"Missing or wrong columns; need {req_cols}"}
        ts += c1; ms += 10

        # ── C2: budget amounts accuracy (25 pts) ──
        c2 = 0; c2r = "No data"
        if bd:
            ok, ep = 0, len(gt_alloc)
            for row in bd:
                k = (row.get("source", "").strip(), row.get("department", "").strip())
                if k in gt_alloc:
                    try:
                        ab = float(row["allocated_budget"]); gt_b = gt_alloc[k]["allocated_budget"]
                        if (gt_b and abs(ab - gt_b) / gt_b <= 0.05) or (not gt_b and ab == 0):
                            ok += 1
                    except (ValueError, KeyError):
                        pass
            c2 = round(25 * ok / ep) if ep else 0
            c2r = f"{ok}/{ep} within 5%"
        ec["budget_amounts_accuracy"] = {"passed": c2 >= 20, "score": c2, "max_score": 25, "reason": c2r}
        ts += c2; ms += 25

        # ── C3: total budget constraint (15 pts) ──
        c3 = 0; c3r = "No data"
        if bd:
            try:
                tot = sum(float(r["allocated_budget"]) for r in bd)
                if abs(tot - total_budget) / total_budget <= 0.02:
                    c3 = 15; c3r = f"${tot:.0f} within 2% of ${total_budget:.0f}"
                else:
                    c3r = f"${tot:.0f} deviates >2% from ${total_budget:.0f}"
            except (ValueError, KeyError):
                c3r = "Parse error"
        ec["budget_total_constraint"] = {"passed": c3 == 15, "score": c3, "max_score": 15, "reason": c3r}
        ts += c3; ms += 15

        # ── C4: quality_kpis.csv structure (10 pts) ──
        kp = os.path.join(self.workspace, "quality_kpis.csv")
        kd = []
        c4 = 0
        kpi_cols = {"source", "department", "avg_time_to_hire_days", "retention_rate", "quality_score"}
        if os.path.exists(kp):
            try:
                with open(kp) as f:
                    rdr = csv.DictReader(f); kd = list(rdr)
                if kpi_cols.issubset(set(rdr.fieldnames or [])):
                    c4 = 10
            except Exception:
                pass
        ec["kpi_file_structure"] = {"passed": c4 == 10, "score": c4, "max_score": 10,
                                    "reason": "" if c4 else f"Missing or wrong columns; need {kpi_cols}"}
        ts += c4; ms += 10

        # ── C5: KPI values accuracy (25 pts) ──
        c5 = 0; c5r = "No data"
        if kd:
            qok = rok = tok = 0
            ep = len(gt_results)
            for row in kd:
                k = (row.get("source", "").strip(), row.get("department", "").strip())
                if k not in gt_results:
                    continue
                gt = gt_results[k]
                try:
                    if abs(float(row["quality_score"]) - gt["quality_score"]) <= 0.05:
                        qok += 1
                except (ValueError, KeyError):
                    pass
                try:
                    if abs(float(row["retention_rate"]) - gt["retention_rate"]) <= 0.05:
                        rok += 1
                except (ValueError, KeyError):
                    pass
                try:
                    a = float(row["avg_time_to_hire_days"])
                    if gt["avg_days"] and abs(a - gt["avg_days"]) / gt["avg_days"] <= 0.05:
                        tok += 1
                except (ValueError, KeyError):
                    pass
            c5 = round(25 * (0.5 * qok / ep + 0.25 * rok / ep + 0.25 * tok / ep)) if ep else 0
            c5r = f"quality:{qok}/{ep} retention:{rok}/{ep} time:{tok}/{ep}"
        ec["kpi_values_accuracy"] = {"passed": c5 >= 20, "score": c5, "max_score": 25, "reason": c5r}
        ts += c5; ms += 25

        # ── C6: response summary (15 pts) ──
        al = (action or "").lower()
        checks = [
            sum(1 for s in ["linkedin", "indeed", "glassdoor", "referral", "apex"] if s in al) >= 3,
            any(t in al for t in ["budget", "allocat"]),
            any(t in al for t in ["quality", "kpi", "retention"]),
            any(t in al for t in ["recommend", "suggest", "should", "highest", "best"]),
        ]
        c6 = round(15 * sum(checks) / 4)
        missing = []
        labels = ["source names", "budget discussion", "quality discussion", "recommendations"]
        for lbl, ok in zip(labels, checks):
            if not ok:
                missing.append(lbl)
        ec["response_summary"] = {"passed": c6 == 15, "score": c6, "max_score": 15,
                                  "reason": f"Missing: {', '.join(missing)}" if missing else ""}
        ts += c6; ms += 15

        return ts / ms if ms else 0.0, {"eval_criteria": ec, "total_score": ts, "max_score": ms}

    # ─────────────────────────────────────────────
    # verify
    # ─────────────────────────────────────────────

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
        import pandas as pd

        tc = 0  # tool-call counter

        # 1. Discover sources & departments
        sources = json.loads(self.tools["list_recruitment_sources"]()); tc += 1
        departments = json.loads(self.tools["list_departments"]()["content"][0]["text"]); tc += 1
        snames = [s["name"] for s in sources]
        stypes = {s["name"]: s["type"] for s in sources}
        sids = {s["name"]: s["source_id"] for s in sources}
        dnames = [d["name"] for d in departments]

        # 2. Read workspace configs
        with open(os.path.join(self.workspace, "channel_pricing.yaml")) as f:
            pricing = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "kpi_formula.json")) as f:
            kpi_cfg = json.load(f)
        with open(os.path.join(self.workspace, "quarterly_targets.csv")) as f:
            targets = list(csv.DictReader(f))
        total_budget = float(targets[0]["total_budget"])
        w = kpi_cfg["quality_of_hire_weights"]

        # 3. Read workspace data files (grouped by source, department)
        interview_by_pair = defaultdict(list)
        for fp in sorted(glob.glob(os.path.join(self.workspace, "interview_scores_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    k = (row["source_name"], row["department"])
                    interview_by_pair[k].append(
                        (float(row["technical_score"]) + float(row["behavioral_score"])
                         + float(row["cultural_fit_score"])) / 3
                    )

        mgr_by_pair = defaultdict(list)
        for fp in sorted(glob.glob(os.path.join(self.workspace, "manager_reviews_*.json"))):
            with open(fp) as f:
                for rec in json.load(f):
                    mgr_by_pair[(rec["source_name"], rec["department"])].append(float(rec["manager_satisfaction"]))

        onb_by_pair = defaultdict(list)
        for fp in sorted(glob.glob(os.path.join(self.workspace, "onboarding_metrics_*.yaml"))):
            with open(fp) as f:
                for rec in yaml.safe_load(f):
                    onb_by_pair[(rec["source_name"], rec["department"])].append(float(rec["completion_pct"]))

        # 4. Get Q4 hires for each source (needed for job-board posting-fee allocation)
        q4_hires = {}
        for sn in snames:
            r = json.loads(self.tools["get_quarterly_hires"](source_id=sids[sn], quarter="2025-Q4")); tc += 1
            q4_hires[sn] = r["hires"]

        # 5. Query per-(source, department) metrics via tools
        results = {}
        for sn in snames:
            sid = sids[sn]
            stype = stypes[sn]
            for dn in dnames:
                vol = json.loads(self.tools["get_hiring_volume"](source_id=sid, department=dn)); tc += 1
                tth = json.loads(self.tools["get_time_to_hire"](source_id=sid, department=dn)); tc += 1
                ret = json.loads(self.tools["get_retention_rate"](source_id=sid, department=dn)["content"][0]["text"]); tc += 1
                cst = json.loads(self.tools["get_internal_cost"](source_id=sid, department=dn)["content"][0]["text"]); tc += 1

                n_hired = vol["hired"]
                avg_days = tth["avg_days"] if tth["avg_days"] is not None else 0
                retention_rate = ret["retention_rate"]
                avg_ic = cst["avg_internal_cost"]

                # External fee
                if stype == "job_board":
                    phf = pricing["source_fees"]["job_board"]["per_hire_fee"]
                    qpf = pricing["source_fees"]["job_board"]["quarterly_posting_fee"]
                    ext = phf + (qpf / q4_hires[sn] if q4_hires[sn] else qpf)
                elif stype == "referral":
                    ext = pricing["source_fees"]["referral"]["referral_bonus"]
                else:
                    ext = pricing["source_fees"]["agency"]["placement_fee_pct"] * pricing["department_avg_salary"][dn]

                cph = avg_ic + ext
                te = max(0, 1 - avg_days / 60)

                iv = interview_by_pair.get((sn, dn), [])
                iq = (sum(iv) / len(iv) / 5) if iv else 0
                mv = mgr_by_pair.get((sn, dn), [])
                ms_val = (sum(mv) / len(mv) / 5) if mv else 0
                ov = onb_by_pair.get((sn, dn), [])
                ob = (sum(ov) / len(ov) / 100) if ov else 0

                qs = (w["retention_rate"] * retention_rate
                      + w["time_to_hire_efficiency"] * te
                      + w["interview_quality"] * iq
                      + w["manager_satisfaction"] * ms_val
                      + w["onboarding_success"] * ob)

                es = qs / cph * 10000 if cph > 0 else 0

                results[(sn, dn)] = {
                    "n_hired": n_hired, "avg_days": round(avg_days, 2),
                    "retention_rate": round(retention_rate, 4),
                    "total_cost_per_hire": round(cph, 2),
                    "quality_score": round(qs, 4), "efficiency_score": round(es, 4),
                }

        # 6. Budget allocation
        alloc = self._allocate_budget(results, snames, dnames, total_budget)

        # 7. Write deliverables
        budget_rows = []
        for sn in snames:
            for dn in dnames:
                a = alloc[(sn, dn)]
                budget_rows.append({
                    "source": sn, "department": dn,
                    "allocated_budget": a["allocated_budget"],
                    "expected_hires": a["expected_hires"],
                    "cost_per_hire_estimate": a["cost_per_hire_estimate"],
                })
        pd.DataFrame(budget_rows).to_csv(
            os.path.join(self.workspace, "budget_allocation.csv"), index=False,
        )

        kpi_rows = []
        for sn in snames:
            for dn in dnames:
                r = results[(sn, dn)]
                kpi_rows.append({
                    "source": sn, "department": dn,
                    "avg_time_to_hire_days": r["avg_days"],
                    "retention_rate": r["retention_rate"],
                    "quality_score": r["quality_score"],
                })
        pd.DataFrame(kpi_rows).to_csv(
            os.path.join(self.workspace, "quality_kpis.csv"), index=False,
        )

        # 8. Build response
        src_q = {}
        src_b = {}
        for sn in snames:
            scores = [results[(sn, dn)]["quality_score"] for dn in dnames]
            src_q[sn] = sum(scores) / len(scores)
            src_b[sn] = sum(alloc[(sn, dn)]["allocated_budget"] for dn in dnames)
        best = max(src_q, key=src_q.get)
        worst = min(src_q, key=src_q.get)

        action = (
            f"Quarterly Budget Allocation Plan for Q1 2026\n\n"
            f"After analyzing recruitment data across all sources — LinkedIn, Indeed, Glassdoor, "
            f"Employee Referrals, and Apex Staffing — and computing quality-of-hire KPIs "
            f"incorporating retention rates, time-to-hire efficiency, interview quality, "
            f"manager satisfaction, and onboarding success, the following budget allocation "
            f"has been produced.\n\n"
            f"The total budget of ${total_budget:,.0f} is allocated based on efficiency-weighted "
            f"scoring per source-department pair, subject to minimum (8%) and maximum (35%) "
            f"per-source constraints.\n\n"
            f"Key findings:\n"
            f"- {best} shows the highest overall quality-of-hire score ({src_q[best]:.4f} avg) "
            f"and is recommended for increased investment.\n"
            f"- {worst} has the lowest quality scores and should be evaluated for improvements.\n\n"
            f"Budget by source:\n"
        )
        for sn in snames:
            action += f"- {sn}: ${src_b[sn]:,.0f}\n"
        action += (
            "\nDetailed allocation is in budget_allocation.csv; "
            "quality KPIs are in quality_kpis.csv."
        )

        assert tc >= 15, f"Only {tc} tool calls, need >=15"
        return self.step(action)
