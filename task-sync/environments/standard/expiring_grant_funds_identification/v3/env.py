import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


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
    # TOOL METHODS
    # ================================================================

    @tool(
        description="List grants with pagination and optional filtering. Returns grant summaries including grant_id, title, project_director, department, sponsor, end_date, and status. Use page and page_size to paginate through results.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page. Maximum 20. Defaults to 20.",
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["active", "closed", "all"],
                    "description": "Filter by grant status. Defaults to 'all'.",
                },
                "department_filter": {
                    "type": "string",
                    "description": "Filter by department name (exact match). Leave empty for all departments.",
                },
            },
            "required": [],
        },
    )
    def list_grants(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: str = "all",
        department_filter: str = "",
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        offset = (page - 1) * page_size

        query = "SELECT grant_id, title, project_director, department, sponsor, end_date, status FROM grants WHERE 1=1"
        params = []
        if status_filter and status_filter != "all":
            query += " AND status = ?"
            params.append(status_filter)
        if department_filter:
            query += " AND department = ?"
            params.append(department_filter)

        count_query = query.replace(
            "SELECT grant_id, title, project_director, department, sponsor, end_date, status",
            "SELECT COUNT(*)",
        )
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        query += " ORDER BY grant_id LIMIT ? OFFSET ?"
        params.extend([page_size, offset])
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        return _envelope({
            "grants": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
        })

    @tool(
        description="Get full details for a specific grant by its grant_id, including original_budget, start_date, grant_type, and all other fields.",
        parameters={
            "type": "object",
            "properties": {
                "grant_id": {
                    "type": "string",
                    "description": "The unique grant identifier (e.g., 'GRT-0001').",
                },
            },
            "required": ["grant_id"],
        },
    )
    def get_grant_details(self, grant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM grants WHERE grant_id = ?", (grant_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.dumps(dict(row), ensure_ascii=False, default=str)
        return json.dumps({"error": f"Grant {grant_id} not found."}, ensure_ascii=False, default=str)

    @tool(
        description="Retrieve all expenditure transactions for a specific grant. Returns transaction details including amount, expense_category, transaction_date, and fiscal_year.",
        parameters={
            "type": "object",
            "properties": {
                "grant_id": {
                    "type": "string",
                    "description": "The grant identifier to look up expenditures for.",
                },
            },
            "required": ["grant_id"],
        },
    )
    def get_expenditures(self, grant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT exp_id, grant_id, transaction_date, amount, expense_category, description, fiscal_year "
            "FROM expenditures WHERE grant_id = ? ORDER BY transaction_date",
            (grant_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return _envelope({"expenditures": rows, "count": len(rows)})

    @tool(
        description="Retrieve all award modification notices for a specific grant. Returns modification type (supplement, reduction, no_cost_extension, rebudget), amount_change, effective_date, and new_end_date if applicable.",
        parameters={
            "type": "object",
            "properties": {
                "grant_id": {
                    "type": "string",
                    "description": "The grant identifier to look up modifications for.",
                },
            },
            "required": ["grant_id"],
        },
    )
    def get_award_modifications(self, grant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT mod_id, grant_id, mod_type, amount_change, effective_date, new_end_date, description "
            "FROM award_modifications WHERE grant_id = ? ORDER BY effective_date",
            (grant_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"modifications": rows, "count": len(rows)}, ensure_ascii=False, default=str)

    @tool(
        description="Retrieve all sponsor payment records for a specific grant. Returns payment amounts, dates, and methods.",
        parameters={
            "type": "object",
            "properties": {
                "grant_id": {
                    "type": "string",
                    "description": "The grant identifier to look up payments for.",
                },
            },
            "required": ["grant_id"],
        },
    )
    def get_sponsor_payments(self, grant_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT payment_id, grant_id, payment_date, amount, payment_method, invoice_number "
            "FROM sponsor_payments WHERE grant_id = ? ORDER BY payment_date",
            (grant_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return json.dumps({"payments": rows, "count": len(rows)}, ensure_ascii=False, default=str)

    @tool(
        description="Look up the institutional indirect cost rate for a given department, fiscal year, and cost base type. Returns the negotiated rate percentage.",
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "The department name (e.g., 'Biology', 'Computer Science').",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "The fiscal year (e.g., 2025).",
                },
                "base_type": {
                    "type": "string",
                    "enum": ["MTDC", "TDC"],
                    "description": "The cost base type: MTDC (Modified Total Direct Costs) or TDC (Total Direct Costs).",
                },
            },
            "required": ["department", "fiscal_year", "base_type"],
        },
    )
    def get_indirect_cost_rate(
        self, department: str, fiscal_year: int, base_type: str
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT rate_id, department, fiscal_year, rate_pct, base_type "
            "FROM indirect_cost_rates WHERE department = ? AND fiscal_year = ? AND base_type = ?",
            (department, int(fiscal_year), base_type),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return _envelope(dict(row))
        return _envelope({
            "error": f"No IDC rate found for department='{department}', fiscal_year={fiscal_year}, base_type='{base_type}'."
        })

    # ================================================================
    # EVALUATION
    # ================================================================

    def _compute_ground_truth(self) -> List[Dict[str, Any]]:
        """Compute the expected report rows from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Read config files
        import yaml as _yaml
        try:
            with open(os.path.join(self.workspace, "reporting_config.yaml")) as f:
                config = _yaml.safe_load(f)
        except Exception:
            config = self._parse_yaml_fallback(
                os.path.join(self.workspace, "reporting_config.yaml")
            )

        try:
            with open(os.path.join(self.workspace, "idc_policy.yaml")) as f:
                idc_policy = _yaml.safe_load(f)
        except Exception:
            idc_policy = self._parse_yaml_fallback(
                os.path.join(self.workspace, "idc_policy.yaml")
            )

        with open(os.path.join(self.workspace, "priority_tiers.json")) as f:
            tiers_config = json.load(f)

        reference_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        window_days = config["window_days"]
        excluded_cats = idc_policy["excluded_categories"]
        idc_base_type = idc_policy["base_type"]
        fy_start_month = idc_policy.get("fiscal_year_start_month", 1)

        # Determine fiscal year for reference date
        if fy_start_month == 1:
            ref_fy = reference_date.year
        else:
            if reference_date.month >= fy_start_month:
                ref_fy = reference_date.year + 1
            else:
                ref_fy = reference_date.year

        # Get all active grants
        cursor.execute("SELECT * FROM grants WHERE status = 'active'")
        all_active = [dict(r) for r in cursor.fetchall()]

        # For each, compute effective end date (considering NCEs)
        candidates = []
        for g in all_active:
            grant_id = g["grant_id"]
            orig_end = datetime.strptime(g["end_date"], "%Y-%m-%d")

            cursor.execute(
                "SELECT new_end_date FROM award_modifications "
                "WHERE grant_id = ? AND mod_type = 'no_cost_extension' AND new_end_date != ''",
                (grant_id,),
            )
            nce_dates = [
                datetime.strptime(r["new_end_date"], "%Y-%m-%d")
                for r in cursor.fetchall()
            ]
            effective_end = max([orig_end] + nce_dates)

            days_to_exp = (effective_end - reference_date).days
            if 0 <= days_to_exp <= window_days:
                g["effective_end_date"] = effective_end.strftime("%Y-%m-%d")
                g["days_to_expiration"] = days_to_exp
                candidates.append(g)

        # Read grant memos to find carryover-approved grants
        carryover_ids = set()
        memo_dir = os.path.join(self.workspace, "grant_memos")
        if os.path.isdir(memo_dir):
            for fname in sorted(os.listdir(memo_dir)):
                fpath = os.path.join(memo_dir, fname)
                with open(fpath) as f:
                    content = f.read()
                current_gid = None
                for line in content.split("\n"):
                    if line.startswith("--- Grant:"):
                        current_gid = line.split("--- Grant:")[1].strip().rstrip(" ---")
                        if current_gid.endswith("---"):
                            current_gid = current_gid[:-3].strip()
                    if current_gid and "carryover" in line.lower() and "approved" in line.lower():
                        carryover_ids.add(current_gid)

        # Filter out carryover grants
        qualifying = [g for g in candidates if g["grant_id"] not in carryover_ids]

        # Read pending obligations
        obligations_by_grant = {}
        oblig_dir = os.path.join(self.workspace, "pending_obligations")
        if os.path.isdir(oblig_dir):
            for fname in sorted(os.listdir(oblig_dir)):
                fpath = os.path.join(oblig_dir, fname)
                with open(fpath, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        gid = row["grant_id"]
                        amt = float(row["amount"])
                        obligations_by_grant[gid] = obligations_by_grant.get(gid, 0.0) + amt

        # Read director contacts
        director_emails = {}
        contacts_dir = os.path.join(self.workspace, "director_contacts")
        if os.path.isdir(contacts_dir):
            for fname in sorted(os.listdir(contacts_dir)):
                fpath = os.path.join(contacts_dir, fname)
                with open(fpath) as f:
                    data = json.load(f)
                for name, info in data.items():
                    director_emails[name] = info.get("email", "")

        # Compute balances for qualifying grants
        report_rows = []
        for g in qualifying:
            grant_id = g["grant_id"]
            dept = g["department"]

            # Total awarded = original budget + sum of supplement/reduction modifications
            cursor.execute(
                "SELECT COALESCE(SUM(amount_change), 0) FROM award_modifications "
                "WHERE grant_id = ? AND mod_type IN ('supplement', 'reduction')",
                (grant_id,),
            )
            mod_sum = cursor.fetchone()[0]
            total_awarded = g["original_budget"] + mod_sum

            # Expenditures
            cursor.execute(
                "SELECT amount, expense_category FROM expenditures WHERE grant_id = ?",
                (grant_id,),
            )
            exp_rows = cursor.fetchall()
            total_direct = sum(r["amount"] for r in exp_rows)
            excluded_total = sum(
                r["amount"] for r in exp_rows if r["expense_category"] in excluded_cats
            )
            idc_base = total_direct - excluded_total

            # IDC rate
            cursor.execute(
                "SELECT rate_pct FROM indirect_cost_rates "
                "WHERE department = ? AND fiscal_year = ? AND base_type = ?",
                (dept, ref_fy, idc_base_type),
            )
            rate_row = cursor.fetchone()
            idc_rate = rate_row["rate_pct"] / 100.0 if rate_row else 0.0
            idc_charges = idc_base * idc_rate

            pending_oblig = obligations_by_grant.get(grant_id, 0.0)
            total_spent = total_direct + idc_charges + pending_oblig
            remaining_balance = total_awarded - total_spent
            remaining_pct = (
                (remaining_balance / total_awarded * 100.0) if total_awarded > 0 else 0.0
            )
            days_to_exp = g["days_to_expiration"]

            # Priority tier assignment (first match). Grants whose remaining
            # balance percentage falls below every tier's threshold are
            # already fully exhausted and are not at risk of forfeiting
            # unspent funds, so they are excluded from the report.
            priority_tier = None
            for tier in tiers_config["tiers"]:
                if (
                    days_to_exp <= tier["max_days_to_expiration"]
                    and remaining_pct >= tier["min_remaining_pct"]
                ):
                    priority_tier = tier["name"]
                    break
            if priority_tier is None:
                continue

            report_rows.append(
                {
                    "grant_id": grant_id,
                    "title": g["title"],
                    "project_director": g["project_director"],
                    "director_email": director_emails.get(g["project_director"], ""),
                    "department": dept,
                    "sponsor": g["sponsor"],
                    "total_awarded": round(total_awarded, 2),
                    "total_spent": round(total_direct, 2),
                    "idc_charges": round(idc_charges, 2),
                    "pending_obligations": round(pending_oblig, 2),
                    "remaining_balance": round(remaining_balance, 2),
                    "remaining_pct": round(remaining_pct, 2),
                    "days_to_expiration": days_to_exp,
                    "priority_tier": priority_tier,
                }
            )

        # Sort by tier order then days_to_expiration ascending
        tier_order = {t: i for i, t in enumerate(tiers_config["sort_order"])}
        report_rows.sort(
            key=lambda r: (tier_order.get(r["priority_tier"], 999), r["days_to_expiration"])
        )

        conn.close()
        return report_rows

    def _parse_yaml_fallback(self, filepath: str) -> dict:
        """Minimal YAML parser for simple key-value and list structures."""
        result = {}
        with open(filepath) as f:
            lines = f.readlines()

        current_key = None
        current_list = None

        for line in lines:
            stripped = line.rstrip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(line.lstrip())

            if indent == 0 and ":" in stripped:
                if current_key and current_list is not None:
                    result[current_key] = current_list
                    current_list = None

                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")

                if val == "":
                    current_key = key
                    current_list = []
                else:
                    current_key = None
                    if val.lower() == "true":
                        result[key] = True
                    elif val.lower() == "false":
                        result[key] = False
                    else:
                        try:
                            result[key] = int(val)
                        except ValueError:
                            try:
                                result[key] = float(val)
                            except ValueError:
                                result[key] = val
            elif stripped.lstrip().startswith("- ") and current_list is not None:
                item = stripped.lstrip()[2:].strip().strip('"').strip("'")
                current_list.append(item)

        if current_key and current_list is not None:
            result[current_key] = current_list

        return result

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
        eval_criteria = {}
        ground_truth = self._compute_ground_truth()
        gt_ids = {r["grant_id"] for r in ground_truth}

        # --- Criterion 1: Report file exists (5 pts) ---
        report_path = os.path.join(self.workspace, "use_it_or_lose_it_report.csv")
        file_exists = os.path.isfile(report_path)
        eval_criteria["report_file_exists"] = {
            "passed": file_exists,
            "score": 5 if file_exists else 0,
            "max_score": 5,
            "reason": "" if file_exists else "use_it_or_lose_it_report.csv not found in workspace.",
        }

        if not file_exists:
            total = sum(c["score"] for c in eval_criteria.values())
            max_total = sum(c["max_score"] for c in eval_criteria.values()) + 95
            return total / max_total, {
                "eval_criteria": eval_criteria,
                "total_score": total,
                "max_score": max_total,
            }

        # Read agent's report
        try:
            with open(report_path, newline="") as f:
                reader = csv.DictReader(f)
                agent_rows = list(reader)
                agent_columns = reader.fieldnames or []
        except Exception as e:
            eval_criteria["report_parse"] = {
                "passed": False,
                "score": 0,
                "max_score": 95,
                "reason": f"Failed to parse report CSV: {e}",
            }
            return 5 / 100, {
                "eval_criteria": eval_criteria,
                "total_score": 5,
                "max_score": 100,
            }

        # --- Criterion 2: Correct columns (10 pts) ---
        expected_cols = [
            "grant_id", "title", "project_director", "director_email",
            "department", "sponsor", "total_awarded", "total_spent",
            "idc_charges", "pending_obligations", "remaining_balance",
            "remaining_pct", "days_to_expiration", "priority_tier",
        ]
        cols_match = agent_columns == expected_cols
        if not cols_match:
            cols_present = all(c in agent_columns for c in expected_cols)
            col_score = 5 if cols_present else 0
        else:
            col_score = 10
        eval_criteria["correct_columns"] = {
            "passed": cols_match,
            "score": col_score,
            "max_score": 10,
            "reason": "" if cols_match else f"Expected columns {expected_cols}, got {agent_columns}.",
        }

        # --- Criterion 3: Correct grant set (20 pts) ---
        agent_ids = {r.get("grant_id", "") for r in agent_rows}
        correct_ids = gt_ids
        missing = correct_ids - agent_ids
        extra = agent_ids - correct_ids
        if not missing and not extra:
            grant_set_score = 20
            grant_set_pass = True
        else:
            overlap = len(correct_ids & agent_ids)
            total_possible = len(correct_ids)
            grant_set_score = max(0, int(20 * overlap / total_possible)) if total_possible > 0 else 0
            grant_set_pass = False
        eval_criteria["correct_grant_set"] = {
            "passed": grant_set_pass,
            "score": grant_set_score,
            "max_score": 20,
            "reason": ""
            if grant_set_pass
            else f"Missing {len(missing)} grants, {len(extra)} extra grants. Missing: {sorted(missing)[:5]}, Extra: {sorted(extra)[:5]}.",
        }

        # Build lookup maps
        gt_map = {r["grant_id"]: r for r in ground_truth}
        agent_map = {r.get("grant_id", ""): r for r in agent_rows}
        common_ids = correct_ids & agent_ids

        # --- Criterion 4: Correct remaining balance (20 pts) ---
        if common_ids:
            balance_correct = 0
            balance_total = len(common_ids)
            for gid in common_ids:
                gt_bal = gt_map[gid]["remaining_balance"]
                try:
                    agent_bal = float(agent_map[gid].get("remaining_balance", 0))
                except (ValueError, TypeError):
                    agent_bal = -999999
                if abs(gt_bal - agent_bal) < max(1.0, abs(gt_bal) * 0.005):
                    balance_correct += 1

            balance_pct = balance_correct / balance_total
            balance_score = int(20 * balance_pct)
            balance_pass = balance_pct >= 0.95
        else:
            balance_score = 0
            balance_pass = False
            balance_correct = 0
            balance_total = 0
        eval_criteria["correct_remaining_balance"] = {
            "passed": balance_pass,
            "score": balance_score,
            "max_score": 20,
            "reason": ""
            if balance_pass
            else f"{balance_correct}/{balance_total} balances within tolerance.",
        }

        # --- Criterion 5: Correct IDC charges (10 pts) ---
        if common_ids:
            idc_correct = 0
            idc_total = len(common_ids)
            for gid in common_ids:
                gt_idc = gt_map[gid]["idc_charges"]
                try:
                    agent_idc = float(agent_map[gid].get("idc_charges", 0))
                except (ValueError, TypeError):
                    agent_idc = -999999
                if abs(gt_idc - agent_idc) < max(1.0, abs(gt_idc) * 0.005):
                    idc_correct += 1

            idc_pct = idc_correct / idc_total
            idc_score = int(10 * idc_pct)
            idc_pass = idc_pct >= 0.95
        else:
            idc_score = 0
            idc_pass = False
            idc_correct = 0
            idc_total = 0
        eval_criteria["correct_idc_charges"] = {
            "passed": idc_pass,
            "score": idc_score,
            "max_score": 10,
            "reason": ""
            if idc_pass
            else f"{idc_correct}/{idc_total} IDC charges within tolerance.",
        }

        # --- Criterion 6: Correct priority tier (15 pts) ---
        if common_ids:
            tier_correct = 0
            tier_total = len(common_ids)
            for gid in common_ids:
                gt_tier = gt_map[gid]["priority_tier"]
                agent_tier = agent_map[gid].get("priority_tier", "").strip().lower()
                if gt_tier.lower() == agent_tier:
                    tier_correct += 1

            tier_pct = tier_correct / tier_total
            tier_score = int(15 * tier_pct)
            tier_pass = tier_pct >= 0.95
        else:
            tier_score = 0
            tier_pass = False
            tier_correct = 0
            tier_total = 0
        eval_criteria["correct_priority_tier"] = {
            "passed": tier_pass,
            "score": tier_score,
            "max_score": 15,
            "reason": ""
            if tier_pass
            else f"{tier_correct}/{tier_total} tiers correct.",
        }

        # --- Criterion 7: Correct sorting (10 pts) ---
        agent_id_order = [r.get("grant_id", "") for r in agent_rows]
        gt_id_order = [r["grant_id"] for r in ground_truth]
        sort_pass = agent_id_order == gt_id_order
        eval_criteria["correct_sorting"] = {
            "passed": sort_pass,
            "score": 10 if sort_pass else 0,
            "max_score": 10,
            "reason": ""
            if sort_pass
            else "Report rows not in expected order (priority_tier, then days_to_expiration ascending).",
        }

        # --- Criterion 8: Correct director emails (10 pts) ---
        if common_ids:
            email_correct = 0
            email_total = len(common_ids)
            for gid in common_ids:
                gt_email = gt_map[gid]["director_email"]
                agent_email = agent_map[gid].get("director_email", "").strip()
                if gt_email == agent_email:
                    email_correct += 1

            email_pct = email_correct / email_total
            email_score = int(10 * email_pct)
            email_pass = email_pct >= 0.95
        else:
            email_score = 0
            email_pass = False
            email_correct = 0
            email_total = 0
        eval_criteria["correct_director_emails"] = {
            "passed": email_pass,
            "score": email_score,
            "max_score": 10,
            "reason": ""
            if email_pass
            else f"{email_correct}/{email_total} emails correct.",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())
        reward = total_score / max_score if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

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
        tool_call_count = 0

        # Step 1: Read workspace config files
        try:
            import yaml as _yaml
            with open(os.path.join(self.workspace, "reporting_config.yaml")) as f:
                config = _yaml.safe_load(f)
        except Exception:
            config = self._parse_yaml_fallback(
                os.path.join(self.workspace, "reporting_config.yaml")
            )

        try:
            import yaml as _yaml
            with open(os.path.join(self.workspace, "idc_policy.yaml")) as f:
                idc_policy = _yaml.safe_load(f)
        except Exception:
            idc_policy = self._parse_yaml_fallback(
                os.path.join(self.workspace, "idc_policy.yaml")
            )

        with open(os.path.join(self.workspace, "priority_tiers.json")) as f:
            tiers_config = json.load(f)

        reference_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        window_days = config["window_days"]
        excluded_cats = idc_policy["excluded_categories"]
        idc_base_type = idc_policy["base_type"]
        fy_start_month = idc_policy.get("fiscal_year_start_month", 1)

        if fy_start_month == 1:
            ref_fy = reference_date.year
        else:
            ref_fy = reference_date.year + 1 if reference_date.month >= fy_start_month else reference_date.year

        # Step 2: List all active grants (paginated)
        all_grants = []
        page = 1
        while True:
            result = json.loads(self.tools["list_grants"](page=page, page_size=20, status_filter="active")["content"][0]["text"])
            tool_call_count += 1
            all_grants.extend(result["grants"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: Filter to grants with end_date in the 90-day window
        in_window_grants = []
        for g in all_grants:
            end_dt = datetime.strptime(g["end_date"], "%Y-%m-%d")
            days = (end_dt - reference_date).days
            if 0 <= days <= window_days:
                in_window_grants.append(g)

        # Step 4: Check award modifications for NCEs that push effective end date out
        qualifying_after_nce = []
        for g in in_window_grants:
            mods_result = json.loads(self.tools["get_award_modifications"](grant_id=g["grant_id"]))
            tool_call_count += 1
            nce_dates = []
            for m in mods_result["modifications"]:
                if m["mod_type"] == "no_cost_extension" and m["new_end_date"]:
                    nce_dates.append(datetime.strptime(m["new_end_date"], "%Y-%m-%d"))

            orig_end = datetime.strptime(g["end_date"], "%Y-%m-%d")
            effective_end = max([orig_end] + nce_dates)
            eff_days = (effective_end - reference_date).days
            if 0 <= eff_days <= window_days:
                g["effective_end_date"] = effective_end.strftime("%Y-%m-%d")
                g["days_to_expiration"] = eff_days
                qualifying_after_nce.append(g)

        # Step 5: Read grant memos to find carryover-approved grants
        carryover_ids = set()
        memo_dir = os.path.join(self.workspace, "grant_memos")
        if os.path.isdir(memo_dir):
            for fname in sorted(os.listdir(memo_dir)):
                fpath = os.path.join(memo_dir, fname)
                with open(fpath) as f:
                    content = f.read()
                current_gid = None
                for line in content.split("\n"):
                    if line.startswith("--- Grant:"):
                        current_gid = line.split("--- Grant:")[1].strip().rstrip(" ---")
                        if current_gid.endswith("---"):
                            current_gid = current_gid[:-3].strip()
                    if current_gid and "carryover" in line.lower() and "approved" in line.lower():
                        carryover_ids.add(current_gid)

        qualifying = [g for g in qualifying_after_nce if g["grant_id"] not in carryover_ids]

        # Step 6: Read pending obligations
        obligations_by_grant = {}
        oblig_dir = os.path.join(self.workspace, "pending_obligations")
        if os.path.isdir(oblig_dir):
            for fname in sorted(os.listdir(oblig_dir)):
                fpath = os.path.join(oblig_dir, fname)
                with open(fpath, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        gid = row["grant_id"]
                        amt = float(row["amount"])
                        obligations_by_grant[gid] = obligations_by_grant.get(gid, 0.0) + amt

        # Step 7: Read director contacts
        director_emails = {}
        contacts_dir = os.path.join(self.workspace, "director_contacts")
        if os.path.isdir(contacts_dir):
            for fname in sorted(os.listdir(contacts_dir)):
                fpath = os.path.join(contacts_dir, fname)
                with open(fpath) as f:
                    data = json.load(f)
                for name, info in data.items():
                    director_emails[name] = info.get("email", "")

        # Step 8: Get full details + expenditures + IDC rate for each qualifying grant
        idc_rate_cache = {}
        report_rows = []
        for g in qualifying:
            grant_id = g["grant_id"]

            details = json.loads(self.tools["get_grant_details"](grant_id=grant_id))
            tool_call_count += 1

            exp_result = json.loads(self.tools["get_expenditures"](grant_id=grant_id)["content"][0]["text"])
            tool_call_count += 1

            # Get modifications for budget adjustments (we already have them from NCE check
            # but let's reuse the earlier call's data - however for correctness, recalculate)
            mods_result = json.loads(self.tools["get_award_modifications"](grant_id=grant_id))
            tool_call_count += 1

            dept = details["department"]

            # IDC rate (cached per department)
            if dept not in idc_rate_cache:
                rate_result = json.loads(self.tools["get_indirect_cost_rate"](
                    department=dept, fiscal_year=ref_fy, base_type=idc_base_type
                )["content"][0]["text"])
                tool_call_count += 1
                idc_rate_cache[dept] = rate_result.get("rate_pct", 0.0) / 100.0

            idc_rate = idc_rate_cache[dept]

            # Total awarded
            mod_sum = sum(
                m["amount_change"]
                for m in mods_result["modifications"]
                if m["mod_type"] in ("supplement", "reduction")
            )
            total_awarded = details["original_budget"] + mod_sum

            # Expenditures
            total_direct = sum(e["amount"] for e in exp_result["expenditures"])
            excluded_total = sum(
                e["amount"]
                for e in exp_result["expenditures"]
                if e["expense_category"] in excluded_cats
            )
            idc_base = total_direct - excluded_total
            idc_charges = idc_base * idc_rate

            pending_oblig = obligations_by_grant.get(grant_id, 0.0)
            total_spent_with_idc = total_direct + idc_charges + pending_oblig
            remaining_balance = total_awarded - total_spent_with_idc
            remaining_pct = (
                (remaining_balance / total_awarded * 100.0) if total_awarded > 0 else 0.0
            )

            days_to_exp = g["days_to_expiration"]

            # Priority tier
            priority_tier = None
            for tier in tiers_config["tiers"]:
                if (
                    days_to_exp <= tier["max_days_to_expiration"]
                    and remaining_pct >= tier["min_remaining_pct"]
                ):
                    priority_tier = tier["name"]
                    break
            if priority_tier is None:
                continue

            report_rows.append(
                {
                    "grant_id": grant_id,
                    "title": details["title"],
                    "project_director": details["project_director"],
                    "director_email": director_emails.get(details["project_director"], ""),
                    "department": dept,
                    "sponsor": details["sponsor"],
                    "total_awarded": round(total_awarded, 2),
                    "total_spent": round(total_direct, 2),
                    "idc_charges": round(idc_charges, 2),
                    "pending_obligations": round(pending_oblig, 2),
                    "remaining_balance": round(remaining_balance, 2),
                    "remaining_pct": round(remaining_pct, 2),
                    "days_to_expiration": days_to_exp,
                    "priority_tier": priority_tier,
                }
            )

        # Sort by tier order then days_to_expiration ascending
        tier_order = {t: i for i, t in enumerate(tiers_config["sort_order"])}
        report_rows.sort(
            key=lambda r: (tier_order.get(r["priority_tier"], 999), r["days_to_expiration"])
        )

        # Write output CSV
        output_path = os.path.join(self.workspace, "use_it_or_lose_it_report.csv")
        fieldnames = [
            "grant_id", "title", "project_director", "director_email",
            "department", "sponsor", "total_awarded", "total_spent",
            "idc_charges", "pending_obligations", "remaining_balance",
            "remaining_pct", "days_to_expiration", "priority_tier",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_rows:
                writer.writerow(row)

        # Build action string
        action_lines = [
            "Use-It-or-Lose-It Grant Funds Report",
            f"Reference Date: {config['reference_date']}",
            f"Window: {window_days} days",
            f"Total qualifying grants: {len(report_rows)}",
            "",
            "Priority Summary:",
        ]
        tier_counts = {}
        for r in report_rows:
            tier_counts[r["priority_tier"]] = tier_counts.get(r["priority_tier"], 0) + 1
        for t in tiers_config["sort_order"]:
            if t in tier_counts:
                action_lines.append(f"  {t}: {tier_counts[t]} grants")

        total_remaining = sum(r["remaining_balance"] for r in report_rows)
        action_lines.append(f"\nTotal remaining balance across all qualifying grants: ${total_remaining:,.2f}")
        action_lines.append(f"\nReport saved as use_it_or_lose_it_report.csv with {len(report_rows)} entries.")
        action_lines.append(
            f"\nTool calls used: {tool_call_count}"
        )

        action = "\n".join(action_lines)
        return self.step(action)
