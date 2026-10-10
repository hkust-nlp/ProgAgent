import sqlite3
import os
import json
import csv
import math
import yaml
from typing import Tuple, Dict, List, Any


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def _classify_variance(variance_pct, classifications):
    """Classify a variance percentage using the threshold list."""
    for cls in classifications:
        lo = cls["min_pct"] if cls["min_pct"] is not None else float("-inf")
        hi = cls["max_pct"] if cls["max_pct"] is not None else float("inf")
        if lo <= variance_pct < hi:
            return cls["label"]
    return "Unknown"


def _parse_indirect_costs_txt(filepath):
    """Parse an indirect_costs TXT file into a list of (project_id, amount) tuples."""
    results = []
    with open(filepath, "r") as f:
        content = f.read()
    for block in content.split("---\n"):
        block = block.strip()
        if not block:
            continue
        pid = None
        amount = None
        for line in block.split("\n"):
            if line.startswith("Project: "):
                pid = line[len("Project: "):].strip()
            elif line.startswith("Amount: "):
                amount = float(line[len("Amount: "):].strip())
        if pid is not None and amount is not None:
            results.append((pid, amount))
    return results


def _read_workspace_data(workspace):
    """Read all workspace config/data files and return consolidated dicts."""
    # --- Fixed files ---
    with open(os.path.join(workspace, "overhead_config.yaml"), "r") as f:
        overhead_cfg = yaml.safe_load(f)
    overhead_multipliers = overhead_cfg["overhead_multipliers"]

    with open(os.path.join(workspace, "variance_thresholds.json"), "r") as f:
        thresholds = json.load(f)
    classifications = thresholds["classifications"]

    # --- Scaling files ---
    retention_pcts = {}
    architect_premiums = {}
    change_orders = {}     # pid -> list of dicts
    indirect_costs = {}    # pid -> list of float amounts

    for fname in sorted(os.listdir(workspace)):
        fpath = os.path.join(workspace, fname)

        if fname.startswith("project_financials_") and fname.endswith(".csv"):
            with open(fpath, newline="") as f:
                for row in csv.DictReader(f):
                    retention_pcts[row["project_id"]] = float(row["retention_pct"])

        elif fname.startswith("architect_premiums_") and fname.endswith(".json"):
            with open(fpath) as f:
                data = json.load(f)
            for aid, info in data.items():
                architect_premiums[aid] = info["role_multiplier"]

        elif fname.startswith("change_orders_") and fname.endswith(".yaml"):
            with open(fpath) as f:
                data = yaml.safe_load(f) or {}
            for pid, orders in data.items():
                change_orders.setdefault(pid, []).extend(orders)

        elif fname.startswith("indirect_costs_") and fname.endswith(".txt"):
            for pid, amount in _parse_indirect_costs_txt(fpath):
                indirect_costs.setdefault(pid, []).append(amount)

    return {
        "overhead_multipliers": overhead_multipliers,
        "classifications": classifications,
        "retention_pcts": retention_pcts,
        "architect_premiums": architect_premiums,
        "change_orders": change_orders,
        "indirect_costs": indirect_costs,
    }


def _compute_ground_truth(db_path, workspace):
    """Compute the full ground-truth report from DB + workspace."""
    ws = _read_workspace_data(workspace)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    projects = conn.execute("SELECT * FROM projects ORDER BY project_id").fetchall()
    ground = {}

    for p in projects:
        pid = p["project_id"]
        ptype = p["project_type"]

        # Budget
        rows = conn.execute(
            "SELECT allocated_amount FROM budget_allocations WHERE project_id=?", (pid,)
        ).fetchall()
        total_budget = sum(r["allocated_amount"] for r in rows)
        co_total = sum(co["approved_amount"] for co in ws["change_orders"].get(pid, []))
        adjusted_budget = total_budget + co_total

        # Labor
        ts_rows = conn.execute(
            "SELECT architect_id, hours_worked FROM timesheets WHERE project_id=?", (pid,)
        ).fetchall()
        arch_rates = {}
        for t in ts_rows:
            aid = t["architect_id"]
            if aid not in arch_rates:
                a = conn.execute(
                    "SELECT hourly_rate FROM architects WHERE architect_id=?", (aid,)
                ).fetchone()
                arch_rates[aid] = a["hourly_rate"]

        labor = sum(
            t["hours_worked"] * arch_rates[t["architect_id"]]
            * ws["architect_premiums"].get(t["architect_id"], 1.0)
            for t in ts_rows
        )
        labor *= ws["overhead_multipliers"].get(ptype, 1.0)

        # Vendor
        vc_rows = conn.execute(
            "SELECT amount FROM vendor_costs WHERE project_id=?", (pid,)
        ).fetchall()
        vendor_raw = sum(r["amount"] for r in vc_rows)
        ret = ws["retention_pcts"].get(pid, 0.0)
        actual_vendor = vendor_raw * (1 - ret / 100)

        # Indirect
        actual_indirect = sum(ws["indirect_costs"].get(pid, []))

        total_actual = labor + actual_vendor + actual_indirect

        # Invoices
        inv_rows = conn.execute(
            "SELECT amount_billed FROM invoices WHERE project_id=?", (pid,)
        ).fetchall()
        total_billed = sum(r["amount_billed"] for r in inv_rows)

        variance_amount = total_actual - adjusted_budget
        variance_pct = (variance_amount / adjusted_budget * 100) if adjusted_budget != 0 else 0.0
        classification = _classify_variance(variance_pct, ws["classifications"])

        ground[pid] = {
            "project_name": p["project_name"],
            "client_name": p["client_name"],
            "project_type": ptype,
            "total_budget": round(total_budget, 2),
            "adjusted_budget": round(adjusted_budget, 2),
            "actual_labor_cost": round(labor, 2),
            "actual_vendor_cost": round(actual_vendor, 2),
            "actual_indirect_cost": round(actual_indirect, 2),
            "total_actual_cost": round(total_actual, 2),
            "total_billed": round(total_billed, 2),
            "variance_amount": round(variance_amount, 2),
            "variance_pct": round(variance_pct, 2),
            "classification": classification,
        }

    conn.close()
    return ground


def _values_close(a, b, rel_tol=0.01, abs_tol=1.0):
    """Check if two numerical values are close enough."""
    if abs(b) < abs_tol:
        return abs(a - b) < abs_tol
    return abs(a - b) / abs(b) < rel_tol


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

    # ================================================================
    # Tool methods
    # ================================================================

    @tool(
        description="List projects with pagination. Returns a page of project summaries.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of projects per page (default 20, max 50).",
                },
            },
            "required": ["page"],
        },
    )
    def list_projects(self, page: int, page_size: int = 20):
        page_size = min(page_size, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) as cnt FROM projects").fetchone()["cnt"]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT project_id, project_name, client_name, project_type, status "
            "FROM projects ORDER BY project_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "projects": [dict(r) for r in rows],
            "total_count": total,
            "page": page,
            "total_pages": total_pages,
        }

    @tool(
        description="Get full details for a single project by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project identifier, e.g. PRJ-0001.",
                },
            },
            "required": ["project_id"],
        },
    )
    def get_project_details(self, project_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Project {project_id} not found."}
        return dict(row)

    @tool(
        description="Get timesheet entries for a project with pagination.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project identifier.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Entries per page (default 50, max 100).",
                },
            },
            "required": ["project_id"],
        },
    )
    def get_timesheet_entries(self, project_id: str, page: int = 1, page_size: int = 50):
        page_size = min(page_size, 100)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM timesheets WHERE project_id=?", (project_id,)
        ).fetchone()["cnt"]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT entry_id, architect_id, hours_worked, work_date, task_category "
            "FROM timesheets WHERE project_id=? ORDER BY entry_id LIMIT ? OFFSET ?",
            (project_id, page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "entries": [dict(r) for r in rows],
            "total_count": total,
            "page": page,
            "total_pages": total_pages,
        }

    @tool(
        description="Get all budget allocation line items for a project.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project identifier.",
                },
            },
            "required": ["project_id"],
        },
    )
    def get_budget_allocations(self, project_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT budget_category, allocated_amount, fiscal_year "
            "FROM budget_allocations WHERE project_id=? ORDER BY budget_category",
            (project_id,),
        ).fetchall()
        conn.close()
        return {"allocations": [dict(r) for r in rows]}

    @tool(
        description="Get all client billing invoices for a project.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project identifier.",
                },
            },
            "required": ["project_id"],
        },
    )
    def get_project_invoices(self, project_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT invoice_number, invoice_date, amount_billed, payment_status "
            "FROM invoices WHERE project_id=? ORDER BY invoice_date",
            (project_id,),
        ).fetchall()
        conn.close()
        return {"invoices": [dict(r) for r in rows]}

    @tool(
        description="Get vendor/subcontractor cost entries for a project with pagination.",
        parameters={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "The project identifier.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed, default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Entries per page (default 50, max 100).",
                },
            },
            "required": ["project_id"],
        },
    )
    def get_vendor_costs(self, project_id: str, page: int = 1, page_size: int = 50):
        page_size = min(page_size, 100)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM vendor_costs WHERE project_id=?", (project_id,)
        ).fetchone()["cnt"]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT vendor_name, cost_category, amount, invoice_date "
            "FROM vendor_costs WHERE project_id=? ORDER BY cost_id LIMIT ? OFFSET ?",
            (project_id, page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "costs": [dict(r) for r in rows],
            "total_count": total,
            "page": page,
            "total_pages": total_pages,
        }

    @tool(
        description="Get details for a single architect by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "architect_id": {
                    "type": "string",
                    "description": "The architect identifier, e.g. ARC-0001.",
                },
            },
            "required": ["architect_id"],
        },
    )
    def get_architect_info(self, architect_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM architects WHERE architect_id=?", (architect_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Architect {architect_id} not found."}
        return dict(row)

    # ================================================================
    # Evaluation
    # ================================================================

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
        ground = _compute_ground_truth(self.db_path, self.workspace)
        expected_pids = set(ground.keys())

        eval_criteria = {}

        # ---- Read agent's report ----
        expected_cols = [
            "project_id", "project_name", "client_name", "project_type",
            "total_budget", "adjusted_budget", "actual_labor_cost",
            "actual_vendor_cost", "actual_indirect_cost", "total_actual_cost",
            "total_billed", "variance_amount", "variance_pct", "classification",
        ]
        report_path = os.path.join(self.workspace, "variance_report.csv")
        agent_rows = {}
        agent_ordered_pids = []
        report_valid = False

        if os.path.exists(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames and set(expected_cols).issubset(set(reader.fieldnames)):
                        report_valid = True
                        for row in reader:
                            pid = row["project_id"]
                            agent_rows[pid] = row
                            agent_ordered_pids.append(pid)
            except Exception:
                pass

        # ---- Criterion 1: Report structure (10 pts) ----
        if report_valid:
            eval_criteria["report_structure"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            reason = "File missing" if not os.path.exists(report_path) else "Missing required columns"
            eval_criteria["report_structure"] = {
                "passed": False, "score": 0, "max_score": 10, "reason": reason,
            }

        # ---- Criterion 2: Project coverage (10 pts) ----
        agent_pids = set(agent_rows.keys())
        missing = expected_pids - agent_pids
        extra = agent_pids - expected_pids
        if not missing and not extra:
            eval_criteria["project_coverage"] = {
                "passed": True, "score": 10, "max_score": 10,
            }
        else:
            frac = max(0, len(expected_pids) - len(missing) - len(extra)) / len(expected_pids)
            eval_criteria["project_coverage"] = {
                "passed": False, "score": round(10 * frac, 2), "max_score": 10,
                "reason": f"Missing {len(missing)}, extra {len(extra)}",
            }

        # ---- Helper: per-project numeric accuracy ----
        def _field_accuracy(field_name, max_pts):
            if not agent_rows:
                return {"passed": False, "score": 0, "max_score": max_pts, "reason": "No report data"}
            correct = 0
            checked = 0
            for pid in expected_pids:
                if pid not in agent_rows:
                    continue
                checked += 1
                try:
                    agent_val = float(agent_rows[pid][field_name])
                except (KeyError, ValueError, TypeError):
                    continue
                gt_val = ground[pid][field_name]
                if _values_close(agent_val, gt_val):
                    correct += 1
            frac = correct / len(expected_pids) if expected_pids else 0
            passed = frac >= 0.95
            return {
                "passed": passed,
                "score": round(max_pts * frac, 2),
                "max_score": max_pts,
                **({"reason": f"{correct}/{len(expected_pids)} correct"} if not passed else {}),
            }

        # ---- Criterion 3: Adjusted budget (15 pts) ----
        eval_criteria["adjusted_budget_accuracy"] = _field_accuracy("adjusted_budget", 15)

        # ---- Criterion 4: Actual cost components (20 pts) ----
        # Split across labor (8), vendor (6), indirect (6)
        labor_res = _field_accuracy("actual_labor_cost", 8)
        vendor_res = _field_accuracy("actual_vendor_cost", 6)
        indirect_res = _field_accuracy("actual_indirect_cost", 6)
        combined_score = labor_res["score"] + vendor_res["score"] + indirect_res["score"]
        eval_criteria["actual_costs_accuracy"] = {
            "passed": combined_score >= 18,
            "score": round(combined_score, 2),
            "max_score": 20,
            **({} if combined_score >= 18 else {
                "reason": f"labor={labor_res['score']}/8, vendor={vendor_res['score']}/6, indirect={indirect_res['score']}/6"
            }),
        }

        # ---- Criterion 5: Variance & classification (20 pts) ----
        var_res = _field_accuracy("variance_pct", 10)
        # Classification exact match
        if not agent_rows:
            cls_res = {"passed": False, "score": 0, "max_score": 10, "reason": "No report data"}
        else:
            cls_correct = 0
            for pid in expected_pids:
                if pid in agent_rows and agent_rows[pid].get("classification") == ground[pid]["classification"]:
                    cls_correct += 1
            cls_frac = cls_correct / len(expected_pids) if expected_pids else 0
            cls_res = {
                "passed": cls_frac >= 0.95,
                "score": round(10 * cls_frac, 2),
                "max_score": 10,
                **({"reason": f"{cls_correct}/{len(expected_pids)} correct"} if cls_frac < 0.95 else {}),
            }
        comb = var_res["score"] + cls_res["score"]
        eval_criteria["variance_classification"] = {
            "passed": comb >= 18,
            "score": round(comb, 2),
            "max_score": 20,
            **({} if comb >= 18 else {
                "reason": f"variance_pct={var_res['score']}/10, class={cls_res['score']}/10"
            }),
        }

        # ---- Criterion 6: Sort order (10 pts) ----
        if len(agent_ordered_pids) >= 2:
            # Check that variance_pct is descending
            prev = None
            sorted_ok = True
            for pid in agent_ordered_pids:
                if pid not in agent_rows:
                    continue
                try:
                    v = float(agent_rows[pid]["variance_pct"])
                except (KeyError, ValueError):
                    sorted_ok = False
                    break
                if prev is not None and v > prev + 0.01:
                    sorted_ok = False
                    break
                prev = v
            eval_criteria["sort_order"] = {
                "passed": sorted_ok, "score": 10 if sorted_ok else 0, "max_score": 10,
                **({"reason": "Not sorted by variance_pct descending"} if not sorted_ok else {}),
            }
        else:
            eval_criteria["sort_order"] = {
                "passed": False, "score": 0, "max_score": 10, "reason": "Insufficient rows",
            }

        # ---- Criterion 7: Action summary (15 pts) ----
        # Check action contains: total count, classification counts, top-3
        action_score = 0
        action_max = 15

        # 7a: total project count in action (3 pts)
        if str(len(expected_pids)) in action:
            action_score += 3

        # 7b: classification counts (6 pts, 1.2 per category)
        from collections import Counter
        gt_counts = Counter(g["classification"] for g in ground.values())
        cat_hits = 0
        for label, cnt in gt_counts.items():
            if label in action and str(cnt) in action:
                cat_hits += 1
        action_score += round(min(6, 1.2 * cat_hits), 2)

        # 7c: top-3 projects by variance_pct (6 pts)
        sorted_gt = sorted(ground.items(), key=lambda kv: kv[1]["variance_pct"], reverse=True)
        top3_pids = [kv[0] for kv in sorted_gt[:3]]
        t3_hits = sum(1 for pid in top3_pids if pid in action)
        action_score += t3_hits * 2

        eval_criteria["action_summary"] = {
            "passed": action_score >= 12,
            "score": round(action_score, 2),
            "max_score": action_max,
            **({"reason": f"Scored {action_score}/{action_max}"} if action_score < 12 else {}),
        }

        # ---- Aggregate ----
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score if max_score > 0 else 0.0, {
            "eval_criteria": eval_criteria,
            "total_score": round(total_score, 2),
            "max_score": max_score,
        }

    # ================================================================
    # Self-verification
    # ================================================================

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
        # ----- Step 1: Read workspace configuration -----
        ws = _read_workspace_data(self.workspace)
        overhead_multipliers = ws["overhead_multipliers"]
        classifications = ws["classifications"]
        retention_pcts = ws["retention_pcts"]
        architect_premiums = ws["architect_premiums"]
        change_orders = ws["change_orders"]
        indirect_costs = ws["indirect_costs"]  # pid -> [amounts]

        # ----- Step 2: List all projects via tools -----
        all_projects = []
        page = 1
        while True:
            res = self.tools["list_projects"](page=page, page_size=50)
            all_projects.extend(res["projects"])
            if page >= res["total_pages"]:
                break
            page += 1

        # ----- Step 3: For each project compute costs -----
        architect_cache = {}
        report_rows = []

        for proj in all_projects:
            pid = proj["project_id"]
            ptype = proj["project_type"]

            # Budget allocations
            budget_res = self.tools["get_budget_allocations"](project_id=pid)
            total_budget = sum(b["allocated_amount"] for b in budget_res["allocations"])

            co_total = sum(co["approved_amount"] for co in change_orders.get(pid, []))
            adjusted_budget = total_budget + co_total

            # Timesheets
            ts_entries = []
            ts_page = 1
            while True:
                ts_res = self.tools["get_timesheet_entries"](project_id=pid, page=ts_page, page_size=100)
                ts_entries.extend(ts_res["entries"])
                if ts_page >= ts_res["total_pages"]:
                    break
                ts_page += 1

            # Labor cost
            labor = 0.0
            for t in ts_entries:
                aid = t["architect_id"]
                if aid not in architect_cache:
                    architect_cache[aid] = self.tools["get_architect_info"](architect_id=aid)
                rate = architect_cache[aid]["hourly_rate"]
                premium = architect_premiums.get(aid, 1.0)
                labor += t["hours_worked"] * rate * premium
            labor *= overhead_multipliers.get(ptype, 1.0)

            # Vendor costs
            vc_entries = []
            vc_page = 1
            while True:
                vc_res = self.tools["get_vendor_costs"](project_id=pid, page=vc_page, page_size=100)
                vc_entries.extend(vc_res["costs"])
                if vc_page >= vc_res["total_pages"]:
                    break
                vc_page += 1

            ret_pct = retention_pcts.get(pid, 0.0)
            vendor_raw = sum(v["amount"] for v in vc_entries)
            actual_vendor = vendor_raw * (1 - ret_pct / 100)

            # Indirect costs
            actual_indirect = sum(indirect_costs.get(pid, []))

            total_actual = labor + actual_vendor + actual_indirect

            # Invoices
            inv_res = self.tools["get_project_invoices"](project_id=pid)
            total_billed = sum(inv["amount_billed"] for inv in inv_res["invoices"])

            # Variance
            variance_amount = total_actual - adjusted_budget
            variance_pct = (variance_amount / adjusted_budget * 100) if adjusted_budget != 0 else 0.0
            classification = _classify_variance(variance_pct, classifications)

            report_rows.append({
                "project_id": pid,
                "project_name": proj["project_name"],
                "client_name": proj["client_name"],
                "project_type": ptype,
                "total_budget": round(total_budget, 2),
                "adjusted_budget": round(adjusted_budget, 2),
                "actual_labor_cost": round(labor, 2),
                "actual_vendor_cost": round(actual_vendor, 2),
                "actual_indirect_cost": round(actual_indirect, 2),
                "total_actual_cost": round(total_actual, 2),
                "total_billed": round(total_billed, 2),
                "variance_amount": round(variance_amount, 2),
                "variance_pct": round(variance_pct, 2),
                "classification": classification,
            })

        # Sort by variance_pct descending
        report_rows.sort(key=lambda r: r["variance_pct"], reverse=True)

        # ----- Step 4: Write variance_report.csv -----
        fieldnames = [
            "project_id", "project_name", "client_name", "project_type",
            "total_budget", "adjusted_budget", "actual_labor_cost",
            "actual_vendor_cost", "actual_indirect_cost", "total_actual_cost",
            "total_billed", "variance_amount", "variance_pct", "classification",
        ]
        with open(os.path.join(self.workspace, "variance_report.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_rows:
                writer.writerow(row)

        # ----- Step 5: Build action text -----
        from collections import Counter
        class_counts = Counter(r["classification"] for r in report_rows)

        top3 = report_rows[:3]

        lines = [
            f"Variance analysis complete for {len(report_rows)} projects.",
            "",
            "Classification summary:",
        ]
        for label in ["Significant Overrun", "Moderate Overrun", "Minor Overrun",
                       "Within Tolerance", "Within Budget"]:
            lines.append(f"  {label}: {class_counts.get(label, 0)}")

        lines.append("")
        lines.append("Top 3 projects by variance percentage:")
        for r in top3:
            lines.append(
                f"  {r['project_id']} ({r['project_name']}): "
                f"variance {r['variance_pct']:.2f}%, amount ${r['variance_amount']:.2f}"
            )

        action = "\n".join(lines)
        return self.step(action)
