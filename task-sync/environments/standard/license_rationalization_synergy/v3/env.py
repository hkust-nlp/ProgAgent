"""
Environment for the Software License Rationalization task.
Provides tools for querying software contracts, employees, and usage data,
plus step/verify for evaluation.
"""

import sqlite3
import os
import csv
import json
import math
import re
from typing import Tuple, Dict, List, Any

import yaml


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


PAGE_SIZE = 15


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

    # ── Tools ────────────────────────────────────────────────────────────

    @tool(
        description=(
            "List software contracts for a given company. Returns a paginated "
            "list of contract summaries (id, software_name, vendor, category). "
            "Use page parameter to iterate through results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name to filter contracts, e.g. 'Apex Digital' or 'Nexus Technologies'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page returns up to 15 results.",
                    "default": 1,
                },
            },
            "required": ["company"],
        },
    )
    def list_contracts(self, company: str, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, software_name, vendor, category FROM software_contracts "
            "WHERE company = ? ORDER BY id",
            (company,),
        )
        all_rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        page_rows = all_rows[start:end]
        return {
            "contracts": page_rows,
            "page": page,
            "total": total,
            "has_more": end < total,
        }

    @tool(
        description=(
            "Get full details of a software contract by its ID, including "
            "pricing, seat count, and contract dates."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "integer",
                    "description": "The contract ID.",
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_contract_details(self, contract_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM software_contracts WHERE id = ?", (contract_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Contract {contract_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Get aggregate usage summary for a contract: total assigned users, "
            "number of users active in the last 30 days, and average sessions per user."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "integer",
                    "description": "The contract ID.",
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_usage_summary(self, contract_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS total_assigned, "
            "SUM(CASE WHEN sessions_30d > 0 THEN 1 ELSE 0 END) AS active_users_30d, "
            "COALESCE(AVG(CASE WHEN sessions_30d > 0 THEN sessions_30d END), 0) AS avg_sessions "
            "FROM access_logs WHERE contract_id = ?",
            (contract_id,),
        )
        row = cur.fetchone()
        conn.close()
        return {
            "contract_id": contract_id,
            "total_assigned": row[0] or 0,
            "active_users_30d": row[1] or 0,
            "avg_sessions_per_active_user": round(row[2] or 0, 1),
        }

    @tool(
        description=(
            "List employees assigned to a specific contract. Returns paginated "
            "results with employee_id, name, department, and company."
        ),
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "integer",
                    "description": "The contract ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page returns up to 15 results.",
                    "default": 1,
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_assigned_users(self, contract_id: int, page: int = 1) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT e.id AS employee_id, e.name, d.name AS department, e.company "
            "FROM license_assignments la "
            "JOIN employees e ON la.employee_id = e.id "
            "JOIN departments d ON e.department_id = d.id "
            "WHERE la.contract_id = ? ORDER BY e.id",
            (contract_id,),
        )
        all_rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        total = len(all_rows)
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        page_rows = all_rows[start:end]
        return {
            "users": page_rows,
            "page": page,
            "total": total,
            "has_more": end < total,
        }

    @tool(
        description=(
            "Search for contracts by software name substring. Returns matching "
            "contracts across both companies."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to search for in software names (case-insensitive).",
                },
            },
            "required": ["query"],
        },
    )
    def search_contracts(self, query: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, software_name, vendor, category, company "
            "FROM software_contracts WHERE LOWER(software_name) LIKE ? ORDER BY id",
            (f"%{query.lower()}%",),
        )
        results = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"results": results, "count": len(results)}

    @tool(
        description=(
            "List departments for a given company with basic info."
        ),
        parameters={
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name.",
                },
            },
            "required": ["company"],
        },
    )
    def list_departments(self, company: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, location, cost_center FROM departments "
            "WHERE company = ? ORDER BY id",
            (company,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"departments": rows, "company": company, "count": len(rows)}

    # ── Evaluation ───────────────────────────────────────────────────────

    def _compute_ground_truth(self):
        """Compute the expected rationalization plan from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all contracts
        contracts = [
            dict(r)
            for r in conn.execute("SELECT * FROM software_contracts ORDER BY id").fetchall()
        ]
        contract_by_id = {c["id"]: c for c in contracts}

        # Load all access logs
        access_rows = [
            dict(r) for r in conn.execute("SELECT * FROM access_logs").fetchall()
        ]

        # Load all employees
        emp_rows = [
            dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()
        ]
        emp_by_id = {e["id"]: e for e in emp_rows}
        conn.close()

        # Load workspace config
        with open(os.path.join(self.workspace, "software_equivalence.yaml")) as f:
            equiv_cfg = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "rationalization_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "vendor_discounts.json")) as f:
            vendor_discounts = json.load(f)

        min_sessions = rules["underutilization_threshold"]["min_sessions_30d"]
        eligible_types = set(rules["eligible_employment_types"])

        # Read employment_type from roster files
        emp_type_map = {}  # employee_id -> employment_type
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("employee_roster_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("|") and not line.startswith("| employee_id") and not line.startswith("|---"):
                            parts = [p.strip() for p in line.split("|") if p.strip()]
                            if len(parts) >= 5:
                                try:
                                    eid = int(parts[0])
                                    etype = parts[4]
                                    emp_type_map[eid] = etype
                                except (ValueError, IndexError):
                                    continue

        # Build contracts by company
        by_company = {}
        for c in contracts:
            by_company.setdefault(c["company"], {})[c["software_name"]] = c

        companies = sorted(by_company.keys())
        company_a = companies[0]  # Apex Digital
        company_b = companies[1]  # Nexus Technologies

        # Find overlaps
        overlaps = []

        # Direct overlaps
        for name_a, c_a in by_company[company_a].items():
            if name_a in by_company[company_b]:
                c_b = by_company[company_b][name_a]
                overlaps.append({
                    "type": "direct",
                    "contract_a": c_a,
                    "contract_b": c_b,
                    "overlap_group": name_a,
                })

        # Equivalent overlaps
        for eq in equiv_cfg["equivalences"]:
            s1, s2 = eq["software_1"], eq["software_2"]
            c1_company, c2_company = eq["company_1"], eq["company_2"]
            c_a_name = s1 if c1_company == company_a else s2
            c_b_name = s2 if c1_company == company_a else s1
            if c_a_name in by_company[company_a] and c_b_name in by_company[company_b]:
                c_a = by_company[company_a][c_a_name]
                c_b = by_company[company_b][c_b_name]
                # Skip if already captured as direct
                if c_a["software_name"] == c_b["software_name"]:
                    continue
                group = f"{c_a['software_name']} / {c_b['software_name']}"
                overlaps.append({
                    "type": "equivalent",
                    "contract_a": c_a,
                    "contract_b": c_b,
                    "overlap_group": group,
                })

        # Build access index: (employee_id, contract_id) -> sessions_30d
        access_idx = {}
        for al in access_rows:
            access_idx[(al["employee_id"], al["contract_id"])] = al["sessions_30d"]

        # For each overlap, compute savings
        plan_rows = []
        for ov in overlaps:
            c_a = ov["contract_a"]
            c_b = ov["contract_b"]

            def _count_eligible(contract):
                """Count full-time, utilized users for a contract."""
                count = 0
                for al in access_rows:
                    if al["contract_id"] != contract["id"]:
                        continue
                    if al["sessions_30d"] < min_sessions:
                        continue
                    eid = al["employee_id"]
                    etype = emp_type_map.get(eid, emp_by_id.get(eid, {}).get("employment_type", ""))
                    if etype in eligible_types:
                        count += 1
                return count

            utilized_a = _count_eligible(c_a)
            utilized_b = _count_eligible(c_b)
            total_seats = utilized_a + utilized_b

            # Decide which to retain
            if c_a["price_per_seat"] < c_b["price_per_seat"]:
                retained, eliminated = c_a, c_b
            elif c_b["price_per_seat"] < c_a["price_per_seat"]:
                retained, eliminated = c_b, c_a
            else:
                # tie-break: more total_seats
                if c_a["total_seats"] > c_b["total_seats"]:
                    retained, eliminated = c_a, c_b
                elif c_b["total_seats"] > c_a["total_seats"]:
                    retained, eliminated = c_b, c_a
                else:
                    # second tie-break: alphabetical
                    if c_a["software_name"] <= c_b["software_name"]:
                        retained, eliminated = c_a, c_b
                    else:
                        retained, eliminated = c_b, c_a

            # Volume discount
            disc_pct = 0
            vendor = retained["vendor"]
            if vendor in vendor_discounts:
                for tier in vendor_discounts[vendor]:
                    if tier["min_seats"] <= total_seats <= tier["max_seats"]:
                        disc_pct = tier["discount_pct"]
                        break

            discounted_price = retained["price_per_seat"] * (1 - disc_pct / 100)
            current_cost = round(c_a["annual_cost"] + c_b["annual_cost"], 2)
            projected_cost = round(total_seats * discounted_price, 2)
            savings = round(current_cost - projected_cost, 2)

            plan_rows.append({
                "overlap_group": ov["overlap_group"],
                "software_a": c_a["software_name"],
                "company_a": c_a["company"],
                "software_b": c_b["software_name"],
                "company_b": c_b["company"],
                "retained_software": retained["software_name"],
                "retained_vendor": retained["vendor"],
                "eliminated_software": eliminated["software_name"],
                "current_annual_cost": current_cost,
                "projected_annual_cost": projected_cost,
                "annual_savings": savings,
            })

        plan_rows.sort(key=lambda r: r["annual_savings"], reverse=True)
        total_savings = round(sum(r["annual_savings"] for r in plan_rows), 2)

        return {
            "plan_rows": plan_rows,
            "total_savings": total_savings,
            "overlap_groups": set(r["overlap_group"] for r in plan_rows),
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
        gt_plan = gt["plan_rows"]
        gt_total = gt["total_savings"]
        gt_groups = gt["overlap_groups"]

        criteria = {}
        total_score = 0
        max_score = 100

        # ── Criterion 1: Plan file structure (10 pts) ────────────────────
        plan_path = os.path.join(self.workspace, "rationalization_plan.csv")
        required_cols = {
            "overlap_group", "software_a", "company_a", "software_b", "company_b",
            "retained_software", "retained_vendor", "eliminated_software",
            "current_annual_cost", "projected_annual_cost", "annual_savings",
        }
        agent_plan_rows = []
        if os.path.exists(plan_path):
            try:
                with open(plan_path, newline="") as f:
                    reader = csv.DictReader(f)
                    actual_cols = set(c.strip().lower() for c in (reader.fieldnames or []))
                    for row in reader:
                        agent_plan_rows.append(
                            {k.strip().lower(): v.strip() for k, v in row.items()}
                        )
                cols_ok = required_cols.issubset(actual_cols)
            except Exception:
                cols_ok = False
        else:
            cols_ok = False

        c1_score = 10 if cols_ok else 0
        criteria["plan_file_structure"] = {
            "passed": cols_ok,
            "score": c1_score,
            "max_score": 10,
        }
        if not cols_ok:
            criteria["plan_file_structure"]["reason"] = (
                "rationalization_plan.csv missing or has incorrect columns."
            )
        total_score += c1_score

        # ── Criterion 2: Overlap groups identified (20 pts) ──────────────
        agent_groups = set()
        for row in agent_plan_rows:
            g = row.get("overlap_group", "")
            if g:
                agent_groups.add(g)

        correct_found = agent_groups & gt_groups
        if len(gt_groups) > 0:
            recall = len(correct_found) / len(gt_groups)
        else:
            recall = 1.0
        c2_score = round(20 * recall)
        criteria["overlap_identification"] = {
            "passed": recall == 1.0,
            "score": c2_score,
            "max_score": 20,
        }
        if recall < 1.0:
            missing = gt_groups - agent_groups
            criteria["overlap_identification"]["reason"] = (
                f"Missing overlap groups: {missing}"
            )
        total_score += c2_score

        # ── Criterion 3: No false positives (10 pts) ────────────────────
        false_pos = agent_groups - gt_groups
        c3_score = 10 if len(false_pos) == 0 else max(0, 10 - 2 * len(false_pos))
        criteria["no_false_positives"] = {
            "passed": len(false_pos) == 0,
            "score": c3_score,
            "max_score": 10,
        }
        if false_pos:
            criteria["no_false_positives"]["reason"] = (
                f"False positive groups: {false_pos}"
            )
        total_score += c3_score

        # ── Criterion 4: Correct retained contract (15 pts) ─────────────
        gt_retained = {r["overlap_group"]: r["retained_software"] for r in gt_plan}
        agent_retained = {}
        for row in agent_plan_rows:
            g = row.get("overlap_group", "")
            agent_retained[g] = row.get("retained_software", "")

        retained_correct = 0
        retained_total = 0
        for g in gt_groups:
            if g in agent_retained:
                retained_total += 1
                if agent_retained[g] == gt_retained[g]:
                    retained_correct += 1

        if retained_total > 0:
            ret_ratio = retained_correct / len(gt_groups)
        else:
            ret_ratio = 0.0
        c4_score = round(15 * ret_ratio)
        criteria["retained_contract_correct"] = {
            "passed": ret_ratio == 1.0,
            "score": c4_score,
            "max_score": 15,
        }
        if ret_ratio < 1.0:
            criteria["retained_contract_correct"]["reason"] = (
                f"{retained_correct}/{len(gt_groups)} retained selections correct."
            )
        total_score += c4_score

        # ── Criterion 5: Cost calculations (20 pts) ─────────────────────
        gt_cost_map = {r["overlap_group"]: r for r in gt_plan}
        cost_correct = 0
        cost_checked = 0
        for row in agent_plan_rows:
            g = row.get("overlap_group", "")
            if g not in gt_cost_map:
                continue
            cost_checked += 1
            try:
                a_current = float(row.get("current_annual_cost", 0))
                a_projected = float(row.get("projected_annual_cost", 0))
                a_savings = float(row.get("annual_savings", 0))
                gt_r = gt_cost_map[g]
                if (
                    abs(a_current - gt_r["current_annual_cost"]) < 0.02
                    and abs(a_projected - gt_r["projected_annual_cost"]) < 0.02
                    and abs(a_savings - gt_r["annual_savings"]) < 0.02
                ):
                    cost_correct += 1
            except (ValueError, TypeError):
                pass

        if len(gt_groups) > 0:
            cost_ratio = cost_correct / len(gt_groups)
        else:
            cost_ratio = 1.0
        c5_score = round(20 * cost_ratio)
        criteria["cost_calculations"] = {
            "passed": cost_ratio == 1.0,
            "score": c5_score,
            "max_score": 20,
        }
        if cost_ratio < 1.0:
            criteria["cost_calculations"]["reason"] = (
                f"{cost_correct}/{len(gt_groups)} cost calculations correct."
            )
        total_score += c5_score

        # ── Criterion 6: Savings summary JSON (10 pts) ──────────────────
        summary_path = os.path.join(self.workspace, "savings_summary.json")
        c6_ok = False
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                s_total = summary.get("total_annual_savings", None)
                if s_total is not None and abs(float(s_total) - gt_total) < 0.02:
                    c6_ok = True
            except Exception:
                pass
        c6_score = 10 if c6_ok else 0
        criteria["savings_summary_json"] = {
            "passed": c6_ok,
            "score": c6_score,
            "max_score": 10,
        }
        if not c6_ok:
            criteria["savings_summary_json"]["reason"] = (
                "savings_summary.json missing or total_annual_savings incorrect."
            )
        total_score += c6_score

        # ── Criterion 7: Total savings in response (15 pts) ─────────────
        c7_ok = False
        # Look for the total savings number in the action string
        gt_str = f"{gt_total:.2f}"
        # Also accept without decimals if integer
        gt_str_int = str(int(gt_total)) if gt_total == int(gt_total) else None
        # Try to find the number in various formats
        # Remove commas from action for comparison
        action_clean = action.replace(",", "")
        if gt_str in action_clean:
            c7_ok = True
        elif gt_str_int and gt_str_int in action_clean:
            c7_ok = True
        else:
            # Try matching with $ prefix
            for pattern in [rf"\$\s*{re.escape(gt_str)}", rf"\$\s*{re.escape(f'{gt_total:,.2f}')}"]:
                if re.search(pattern, action):
                    c7_ok = True
                    break

        c7_score = 15 if c7_ok else 0
        criteria["total_savings_in_response"] = {
            "passed": c7_ok,
            "score": c7_score,
            "max_score": 15,
        }
        if not c7_ok:
            criteria["total_savings_in_response"]["reason"] = (
                f"Expected total savings of {gt_total:.2f} not found in response."
            )
        total_score += c7_score

        reward = total_score / max_score
        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

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
        import csv as _csv
        import json as _json

        # ── 1. Read workspace config files ───────────────────────────────
        with open(os.path.join(self.workspace, "software_equivalence.yaml")) as f:
            equiv_cfg = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "rationalization_rules.yaml")) as f:
            rules = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "vendor_discounts.json")) as f:
            vendor_discounts = _json.load(f)

        min_sessions = rules["underutilization_threshold"]["min_sessions_30d"]
        eligible_types = set(rules["eligible_employment_types"])

        # ── 2. Read employee roster files (employment_type) ──────────────
        emp_type_map = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("employee_roster_") and fname.endswith(".md"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("|") and not line.startswith("| employee_id") and not line.startswith("|---"):
                            parts = [p.strip() for p in line.split("|") if p.strip()]
                            if len(parts) >= 5:
                                try:
                                    eid = int(parts[0])
                                    etype = parts[4]
                                    emp_type_map[eid] = etype
                                except (ValueError, IndexError):
                                    continue

        # ── 3. Read access log files (per-user sessions) ─────────────────
        # access_logs: keyed by (employee_id, contract_id) -> sessions_30d
        access_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("access_log_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname), newline="") as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        key = (int(row["employee_id"]), int(row["contract_id"]))
                        access_data[key] = int(row["sessions_30d"])

        # ── 4. List all contracts via tools ──────────────────────────────
        companies = ["Apex Digital", "Nexus Technologies"]
        contracts_by_company = {}
        for company in companies:
            all_contracts = []
            page = 1
            while True:
                result = self.tools["list_contracts"](company=company, page=page)
                all_contracts.extend(result["contracts"])
                if not result["has_more"]:
                    break
                page += 1
            contracts_by_company[company] = {
                c["software_name"]: c for c in all_contracts
            }

        # ── 5. Identify overlap groups ───────────────────────────────────
        names_a = contracts_by_company[companies[0]]
        names_b = contracts_by_company[companies[1]]

        overlaps = []

        # Direct overlaps
        for name in sorted(names_a.keys()):
            if name in names_b:
                overlaps.append({
                    "type": "direct",
                    "summary_a": names_a[name],
                    "summary_b": names_b[name],
                    "overlap_group": name,
                })

        # Equivalent overlaps
        for eq in equiv_cfg["equivalences"]:
            s1, s2 = eq["software_1"], eq["software_2"]
            c1_co, c2_co = eq["company_1"], eq["company_2"]
            a_name = s1 if c1_co == companies[0] else s2
            b_name = s2 if c1_co == companies[0] else s1
            if a_name in names_a and b_name in names_b:
                if a_name == b_name:
                    continue  # already captured as direct
                group = f"{a_name} / {b_name}"
                overlaps.append({
                    "type": "equivalent",
                    "summary_a": names_a[a_name],
                    "summary_b": names_b[b_name],
                    "overlap_group": group,
                })

        # ── 6. For each overlap, get details and compute savings ─────────
        plan_rows = []
        for ov in overlaps:
            # Get contract details via tools
            details_a = self.tools["get_contract_details"](
                contract_id=ov["summary_a"]["id"]
            )
            details_b = self.tools["get_contract_details"](
                contract_id=ov["summary_b"]["id"]
            )

            # Get usage summaries via tools
            usage_a = self.tools["get_usage_summary"](
                contract_id=ov["summary_a"]["id"]
            )
            usage_b = self.tools["get_usage_summary"](
                contract_id=ov["summary_b"]["id"]
            )

            # Count full-time, utilized users from workspace data
            def _count_eligible_from_workspace(contract_id):
                count = 0
                for (eid, cid), sessions in access_data.items():
                    if cid == contract_id and sessions >= min_sessions:
                        if emp_type_map.get(eid, "") in eligible_types:
                            count += 1
                return count

            utilized_a = _count_eligible_from_workspace(details_a["id"])
            utilized_b = _count_eligible_from_workspace(details_b["id"])
            total_seats = utilized_a + utilized_b

            # Retention decision
            if details_a["price_per_seat"] < details_b["price_per_seat"]:
                retained, eliminated = details_a, details_b
            elif details_b["price_per_seat"] < details_a["price_per_seat"]:
                retained, eliminated = details_b, details_a
            else:
                if details_a["total_seats"] > details_b["total_seats"]:
                    retained, eliminated = details_a, details_b
                elif details_b["total_seats"] > details_a["total_seats"]:
                    retained, eliminated = details_b, details_a
                else:
                    if details_a["software_name"] <= details_b["software_name"]:
                        retained, eliminated = details_a, details_b
                    else:
                        retained, eliminated = details_b, details_a

            # Volume discount
            disc_pct = 0
            vendor = retained["vendor"]
            if vendor in vendor_discounts:
                for tier in vendor_discounts[vendor]:
                    if tier["min_seats"] <= total_seats <= tier["max_seats"]:
                        disc_pct = tier["discount_pct"]
                        break

            discounted_price = retained["price_per_seat"] * (1 - disc_pct / 100)
            current_cost = round(details_a["annual_cost"] + details_b["annual_cost"], 2)
            projected_cost = round(total_seats * discounted_price, 2)
            savings = round(current_cost - projected_cost, 2)

            plan_rows.append({
                "overlap_group": ov["overlap_group"],
                "software_a": details_a["software_name"],
                "company_a": details_a["company"],
                "software_b": details_b["software_name"],
                "company_b": details_b["company"],
                "retained_software": retained["software_name"],
                "retained_vendor": retained["vendor"],
                "eliminated_software": eliminated["software_name"],
                "current_annual_cost": current_cost,
                "projected_annual_cost": projected_cost,
                "annual_savings": savings,
            })

        # Sort by annual_savings descending
        plan_rows.sort(key=lambda r: r["annual_savings"], reverse=True)
        total_savings = round(sum(r["annual_savings"] for r in plan_rows), 2)

        # ── 7. Write deliverables ────────────────────────────────────────
        fieldnames = [
            "overlap_group", "software_a", "company_a", "software_b", "company_b",
            "retained_software", "retained_vendor", "eliminated_software",
            "current_annual_cost", "projected_annual_cost", "annual_savings",
        ]
        plan_path = os.path.join(self.workspace, "rationalization_plan.csv")
        with open(plan_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in plan_rows:
                writer.writerow(row)

        summary = {
            "total_annual_savings": total_savings,
            "num_overlap_groups": len(plan_rows),
            "groups": [
                {"overlap_group": r["overlap_group"], "annual_savings": r["annual_savings"]}
                for r in plan_rows
            ],
        }
        summary_path = os.path.join(self.workspace, "savings_summary.json")
        with open(summary_path, "w") as f:
            _json.dump(summary, f, indent=2)

        # ── 8. Construct action string ───────────────────────────────────
        action = (
            f"The license rationalization analysis identified {len(plan_rows)} "
            f"overlapping software subscription groups between Apex Digital and "
            f"Nexus Technologies. After consolidating underutilized and non-full-time "
            f"licenses and applying volume discounts, the total projected annual "
            f"savings from license rationalization is ${total_savings:,.2f}. "
            f"The detailed plan has been saved to rationalization_plan.csv and "
            f"the summary to savings_summary.json."
        )

        return self.step(action)
