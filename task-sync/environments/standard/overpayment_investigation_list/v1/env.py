"""Benefit overpayment detection — task environment."""
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
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "Returns a paginated list of benefit recipients with an active "
            "account status. Each entry contains recipient id, name, benefit "
            "type, monthly benefit amount, and region."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of recipients per page (max 20, default 20).",
                },
            },
            "required": ["page"],
        },
    )
    def list_active_recipients(self, page: int, page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) FROM recipients WHERE account_status='active'"
        ).fetchone()[0]
        total_pages = max(1, -(-total // page_size))  # ceil div
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT id, name, benefit_type, monthly_benefit_amount, region "
            "FROM recipients WHERE account_status='active' "
            "ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_recipients": total,
            "total_pages": total_pages,
            "recipients": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Returns full details for a single recipient by their ID, "
            "including benefit type, monthly benefit amount, enrollment date, "
            "account status, SSN last 4, date of birth, and region."
        ),
        parameters={
            "type": "object",
            "properties": {
                "recipient_id": {
                    "type": "integer",
                    "description": "The recipient's unique ID.",
                },
            },
            "required": ["recipient_id"],
        },
    )
    def get_recipient_details(self, recipient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM recipients WHERE id=?", (recipient_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Recipient {recipient_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Returns all employment status updates for a given recipient, "
            "ordered by effective date descending. Each record contains "
            "employer name, employment status, reported monthly salary, "
            "effective date, and the source payroll hub."
        ),
        parameters={
            "type": "object",
            "properties": {
                "recipient_id": {
                    "type": "integer",
                    "description": "The recipient's unique ID.",
                },
            },
            "required": ["recipient_id"],
        },
    )
    def get_employment_updates(self, recipient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT employer_name, employment_status, reported_monthly_salary, "
            "effective_date, source_hub "
            "FROM employment_updates WHERE recipient_id=? "
            "ORDER BY effective_date DESC",
            (recipient_id,),
        ).fetchall()
        conn.close()
        return {"recipient_id": recipient_id, "updates": [dict(r) for r in rows]}

    @tool(
        description=(
            "Returns all bank transaction alerts for a given recipient, "
            "ordered by alert date descending. Each record contains "
            "alert date, deposit amount, source description, and account type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "recipient_id": {
                    "type": "integer",
                    "description": "The recipient's unique ID.",
                },
            },
            "required": ["recipient_id"],
        },
    )
    def get_bank_alerts(self, recipient_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT alert_date, deposit_amount, source_description, account_type "
            "FROM bank_transaction_alerts WHERE recipient_id=? "
            "ORDER BY alert_date DESC",
            (recipient_id,),
        ).fetchall()
        conn.close()
        return {"recipient_id": recipient_id, "alerts": [dict(r) for r in rows]}

    @tool(
        description=(
            "Returns benefit payment records for a given recipient, optionally "
            "filtered to a period range (YYYY-MM format). Each record contains "
            "payment date, amount, period month, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "recipient_id": {
                    "type": "integer",
                    "description": "The recipient's unique ID.",
                },
                "period_start": {
                    "type": "string",
                    "description": "Start of period filter in YYYY-MM format (inclusive). Optional.",
                },
                "period_end": {
                    "type": "string",
                    "description": "End of period filter in YYYY-MM format (inclusive). Optional.",
                },
            },
            "required": ["recipient_id"],
        },
    )
    def get_benefit_payments(
        self,
        recipient_id: int,
        period_start: str = None,
        period_end: str = None,
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = (
            "SELECT payment_date, amount, period_month, status "
            "FROM benefit_payments WHERE recipient_id=?"
        )
        params: list = [recipient_id]
        if period_start:
            query += " AND period_month >= ?"
            params.append(period_start)
        if period_end:
            query += " AND period_month <= ?"
            params.append(period_end)
        query += " ORDER BY period_month"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return {"recipient_id": recipient_id, "payments": [dict(r) for r in rows]}

    # ------------------------------------------------------------------
    # Ground-truth computation (used by both step and verify-helper)
    # ------------------------------------------------------------------
    def _compute_ground_truth(self) -> list[dict]:
        """Compute the expected investigation list from DB + workspace."""
        # --- load configs from workspace ---
        with open(os.path.join(self.workspace, "investigation_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "benefit_eligibility.json")) as f:
            eligibility = json.load(f)

        review_start = rules["review_period"]["start"]
        review_end = rules["review_period"]["end"]
        sy, sm = map(int, review_start.split("-"))
        ey, em = map(int, review_end.split("-"))
        num_review_months = (ey - sy) * 12 + (em - sm) + 1

        threshold_pct = rules["income_discrepancy_threshold_pct"]
        deposit_threshold = rules["large_deposit_threshold"]
        weights = rules["priority_weights"]
        sev_levels = rules["severity_levels"]

        # --- load self-reports from workspace ---
        sr_by_rid: dict[int, list[dict]] = {}
        for fp in sorted(
            glob.glob(os.path.join(self.workspace, "self_reports_batch_*.csv"))
        ):
            with open(fp, newline="") as f:
                for row in csv.DictReader(f):
                    rid = int(row["recipient_id"])
                    sr_by_rid.setdefault(rid, []).append(row)

        # --- query DB directly ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        active_recipients = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM recipients WHERE account_status='active' ORDER BY id"
            ).fetchall()
        ]

        flagged: list[dict] = []

        for rec in active_recipients:
            rid = rec["id"]

            # employment updates (most recent by effective_date <= review_end)
            emp_rows = conn.execute(
                "SELECT employment_status, reported_monthly_salary, effective_date "
                "FROM employment_updates WHERE recipient_id=? "
                "AND effective_date <= ? ORDER BY effective_date DESC",
                (rid, review_end + "-31"),
            ).fetchall()

            # bank alerts in review period
            bank_rows = conn.execute(
                "SELECT deposit_amount, alert_date FROM bank_transaction_alerts "
                "WHERE recipient_id=? AND alert_date >= ? AND alert_date <= ?",
                (rid, review_start + "-01", review_end + "-31"),
            ).fetchall()

            # benefit payments in review period
            pay_rows = conn.execute(
                "SELECT amount FROM benefit_payments "
                "WHERE recipient_id=? AND period_month >= ? AND period_month <= ?",
                (rid, review_start, review_end),
            ).fetchall()

            # self-reports
            sr_list = sr_by_rid.get(rid, [])
            sr_in_period = [
                s
                for s in sr_list
                if review_start <= s["report_month"] <= review_end
            ]

            # --- compute derived values ---
            # most recent employment
            actual_salary = 0.0
            actual_emp_status = None
            if emp_rows:
                latest = emp_rows[0]
                actual_emp_status = latest["employment_status"]
                if actual_emp_status in ("employed", "part_time"):
                    actual_salary = latest["reported_monthly_salary"]

            total_deposits = sum(r["deposit_amount"] for r in bank_rows)
            avg_monthly_deposits = total_deposits / num_review_months if num_review_months else 0

            detected_monthly_income = max(actual_salary, avg_monthly_deposits)

            total_benefits = sum(r["amount"] for r in pay_rows)

            total_declared = sum(
                float(s["declared_monthly_income"]) for s in sr_in_period
            )
            # most recent declared employment status
            declared_emp = None
            if sr_in_period:
                latest_sr = max(sr_in_period, key=lambda s: s["report_month"])
                declared_emp = latest_sr["declared_employment_status"]

            # --- flags ---
            flags: list[str] = []
            bt = rec["benefit_type"]
            elig = eligibility.get(bt, {})

            # EMPLOYMENT_MISMATCH
            if (
                elig.get("requires_unemployed", False)
                and actual_emp_status in ("employed", "part_time")
                and declared_emp in ("unemployed", "not_working")
            ):
                flags.append("EMPLOYMENT_MISMATCH")

            # INCOME_OVER_LIMIT
            max_income = elig.get("max_monthly_income", float("inf"))
            if detected_monthly_income > max_income:
                flags.append("INCOME_OVER_LIMIT")

            # UNDECLARED_DEPOSITS
            if (
                total_deposits > deposit_threshold
                and total_deposits > total_declared * (1 + threshold_pct / 100)
            ):
                flags.append("UNDECLARED_DEPOSITS")

            if not flags:
                continue

            # --- discrepancy amount ---
            disc_emp = total_benefits if "EMPLOYMENT_MISMATCH" in flags else 0.0
            disc_inc = (
                min(
                    (detected_monthly_income - max_income) * num_review_months,
                    total_benefits,
                )
                if "INCOME_OVER_LIMIT" in flags
                else 0.0
            )
            disc_dep = (
                max(0.0, total_deposits - total_declared)
                if "UNDECLARED_DEPOSITS" in flags
                else 0.0
            )
            discrepancy_amount = round(max(disc_emp, disc_inc, disc_dep), 2)

            # priority score
            priority_score = 0
            if "EMPLOYMENT_MISMATCH" in flags:
                priority_score += weights["employment_mismatch"]
            if "INCOME_OVER_LIMIT" in flags:
                priority_score += weights["income_over_limit"]
            if "UNDECLARED_DEPOSITS" in flags:
                priority_score += weights["undeclared_deposits"]

            # severity
            severity = "low"
            for label in ["critical", "high", "medium", "low"]:
                if priority_score >= sev_levels[label]:
                    severity = label
                    break

            flagged.append(
                {
                    "recipient_id": rid,
                    "recipient_name": rec["name"],
                    "benefit_type": bt,
                    "monthly_benefit": round(rec["monthly_benefit_amount"], 2),
                    "total_benefits_in_period": round(total_benefits, 2),
                    "discrepancy_amount": discrepancy_amount,
                    "priority_score": priority_score,
                    "severity": severity,
                    "flags": "|".join(flags),
                }
            )

        conn.close()

        # sort: priority_score desc, discrepancy_amount desc
        flagged.sort(
            key=lambda x: (-x["priority_score"], -x["discrepancy_amount"])
        )
        return flagged

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------
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
        expected = self._compute_ground_truth()
        criteria: dict = {}

        # ---- 1. File structure (10 pts) ----
        report_path = os.path.join(self.workspace, "investigation_report.csv")
        expected_cols = [
            "recipient_id",
            "recipient_name",
            "benefit_type",
            "monthly_benefit",
            "total_benefits_in_period",
            "discrepancy_amount",
            "priority_score",
            "severity",
            "flags",
        ]
        if not os.path.isfile(report_path):
            criteria["file_structure"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "investigation_report.csv not found",
            }
            # can't evaluate further
            total = sum(c["score"] for c in criteria.values())
            mx = 100
            return total / mx, {
                "eval_criteria": criteria,
                "total_score": total,
                "max_score": mx,
            }

        # read agent file
        with open(report_path, newline="") as f:
            reader = csv.DictReader(f)
            agent_cols = list(reader.fieldnames or [])
            agent_rows = list(reader)

        cols_ok = agent_cols == expected_cols
        criteria["file_structure"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 3,
            "max_score": 10,
            "reason": "" if cols_ok else f"Column mismatch: got {agent_cols}",
        }

        # ---- 2. Recipient identification (25 pts) ----
        expected_ids = set(r["recipient_id"] for r in expected)
        agent_ids = set()
        agent_by_id: dict[int, dict] = {}
        for row in agent_rows:
            try:
                rid = int(row.get("recipient_id", -1))
            except (ValueError, TypeError):
                continue
            agent_ids.add(rid)
            agent_by_id[rid] = row

        if expected_ids:
            tp = len(expected_ids & agent_ids)
            precision = tp / len(agent_ids) if agent_ids else 0
            recall = tp / len(expected_ids)
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall)
                else 0
            )
        else:
            f1 = 1.0 if not agent_ids else 0.0

        id_score = round(f1 * 25)
        criteria["recipient_identification"] = {
            "passed": f1 == 1.0,
            "score": id_score,
            "max_score": 25,
            "reason": (
                ""
                if f1 == 1.0
                else f"F1={f1:.3f} (expected {len(expected_ids)} IDs, got {len(agent_ids)}, "
                     f"TP={tp})"
            ),
        }

        # build expected lookup
        expected_by_id = {r["recipient_id"]: r for r in expected}

        # ---- 3. Flag accuracy (20 pts) ----
        correct_flags = 0
        total_flag_checks = 0
        for rid in expected_ids & agent_ids:
            exp_flags = set(expected_by_id[rid]["flags"].split("|"))
            try:
                agt_flags = set(agent_by_id[rid].get("flags", "").split("|"))
            except Exception:
                agt_flags = set()
            total_flag_checks += 1
            if exp_flags == agt_flags:
                correct_flags += 1

        flag_ratio = correct_flags / total_flag_checks if total_flag_checks else 0
        flag_score = round(flag_ratio * 20)
        criteria["flag_accuracy"] = {
            "passed": flag_ratio == 1.0,
            "score": flag_score,
            "max_score": 20,
            "reason": (
                ""
                if flag_ratio == 1.0
                else f"{correct_flags}/{total_flag_checks} recipients with exact flag match"
            ),
        }

        # ---- 4. Discrepancy amounts (20 pts) ----
        disc_correct = 0
        disc_total = 0
        for rid in expected_ids & agent_ids:
            exp_disc = expected_by_id[rid]["discrepancy_amount"]
            try:
                agt_disc = round(float(agent_by_id[rid].get("discrepancy_amount", 0)), 2)
            except (ValueError, TypeError):
                agt_disc = -1
            disc_total += 1
            if abs(agt_disc - exp_disc) <= max(0.01, exp_disc * 0.02):
                disc_correct += 1

        disc_ratio = disc_correct / disc_total if disc_total else 0
        disc_score = round(disc_ratio * 20)
        criteria["discrepancy_amounts"] = {
            "passed": disc_ratio == 1.0,
            "score": disc_score,
            "max_score": 20,
            "reason": (
                ""
                if disc_ratio == 1.0
                else f"{disc_correct}/{disc_total} amounts within 2% tolerance"
            ),
        }

        # ---- 5. Priority scores & severity (15 pts) ----
        ps_correct = 0
        ps_total = 0
        for rid in expected_ids & agent_ids:
            exp = expected_by_id[rid]
            agt = agent_by_id[rid]
            try:
                ps_ok = int(agt.get("priority_score", -1)) == exp["priority_score"]
            except (ValueError, TypeError):
                ps_ok = False
            sev_ok = agt.get("severity", "").strip().lower() == exp["severity"]
            ps_total += 1
            if ps_ok and sev_ok:
                ps_correct += 1

        ps_ratio = ps_correct / ps_total if ps_total else 0
        ps_score = round(ps_ratio * 15)
        criteria["priority_severity"] = {
            "passed": ps_ratio == 1.0,
            "score": ps_score,
            "max_score": 15,
            "reason": (
                ""
                if ps_ratio == 1.0
                else f"{ps_correct}/{ps_total} with correct priority+severity"
            ),
        }

        # ---- 6. Sort order & response summary (10 pts) ----
        sort_pts = 0
        # check sort order of agent rows
        agent_order_ok = True
        for i in range(len(agent_rows) - 1):
            try:
                ps_a = int(agent_rows[i].get("priority_score", 0))
                ps_b = int(agent_rows[i + 1].get("priority_score", 0))
                da_a = float(agent_rows[i].get("discrepancy_amount", 0))
                da_b = float(agent_rows[i + 1].get("discrepancy_amount", 0))
            except (ValueError, TypeError):
                agent_order_ok = False
                break
            if ps_a < ps_b or (ps_a == ps_b and da_a < da_b):
                agent_order_ok = False
                break
        if agent_order_ok:
            sort_pts += 5

        # response check: total count mentioned
        resp_pts = 0
        if str(len(expected)) in action:
            resp_pts += 5

        criteria["sort_and_summary"] = {
            "passed": sort_pts == 5 and resp_pts == 5,
            "score": sort_pts + resp_pts,
            "max_score": 10,
            "reason": (
                ""
                if (sort_pts + resp_pts) == 10
                else f"sort={'OK' if agent_order_ok else 'WRONG'}, "
                     f"count_in_response={'yes' if resp_pts else 'no (expected '+str(len(expected))+')'}"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------
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
        import math as _math

        # --- 1. Read workspace configs ---
        with open(os.path.join(self.workspace, "investigation_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "benefit_eligibility.json")) as f:
            eligibility = json.load(f)

        review_start = rules["review_period"]["start"]
        review_end = rules["review_period"]["end"]
        sy, sm = map(int, review_start.split("-"))
        ey, em = map(int, review_end.split("-"))
        num_review_months = (ey - sy) * 12 + (em - sm) + 1

        threshold_pct = rules["income_discrepancy_threshold_pct"]
        deposit_threshold = rules["large_deposit_threshold"]
        weights = rules["priority_weights"]
        sev_levels = rules["severity_levels"]

        # --- 2. Read all self-report batch CSVs ---
        sr_by_rid: dict[int, list[dict]] = {}
        for fp in sorted(
            glob.glob(os.path.join(self.workspace, "self_reports_batch_*.csv"))
        ):
            with open(fp, newline="") as f:
                for row in csv.DictReader(f):
                    rid = int(row["recipient_id"])
                    sr_by_rid.setdefault(rid, []).append(row)

        # --- 3. Paginate through all active recipients ---
        all_recipients: list[dict] = []
        page = 1
        while True:
            result = self.tools["list_active_recipients"](page=page, page_size=20)
            all_recipients.extend(result["recipients"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- 4. For each recipient, gather data via tools & compute flags ---
        flagged: list[dict] = []
        tool_call_count = 0

        for rec in all_recipients:
            rid = rec["id"]

            emp_data = self.tools["get_employment_updates"](recipient_id=rid)
            tool_call_count += 1

            bank_data = self.tools["get_bank_alerts"](recipient_id=rid)
            tool_call_count += 1

            pay_data = self.tools["get_benefit_payments"](
                recipient_id=rid,
                period_start=review_start,
                period_end=review_end,
            )
            tool_call_count += 1

            # --- derived values ---
            emp_updates = emp_data.get("updates", [])
            # most recent employment update <= review_end
            relevant_emp = [
                u for u in emp_updates if u["effective_date"] <= review_end + "-31"
            ]
            actual_salary = 0.0
            actual_emp_status = None
            if relevant_emp:
                latest = relevant_emp[0]  # already sorted desc by effective_date
                actual_emp_status = latest["employment_status"]
                if actual_emp_status in ("employed", "part_time"):
                    actual_salary = latest["reported_monthly_salary"]

            bank_alerts = bank_data.get("alerts", [])
            alerts_in_period = [
                a
                for a in bank_alerts
                if review_start + "-01" <= a["alert_date"] <= review_end + "-31"
            ]
            total_deposits = sum(a["deposit_amount"] for a in alerts_in_period)
            avg_monthly_deposits = (
                total_deposits / num_review_months if num_review_months else 0
            )

            detected_monthly_income = max(actual_salary, avg_monthly_deposits)

            payments = pay_data.get("payments", [])
            total_benefits = sum(p["amount"] for p in payments)

            sr_list = sr_by_rid.get(rid, [])
            sr_in_period = [
                s for s in sr_list if review_start <= s["report_month"] <= review_end
            ]
            total_declared = sum(
                float(s["declared_monthly_income"]) for s in sr_in_period
            )
            declared_emp = None
            if sr_in_period:
                latest_sr = max(sr_in_period, key=lambda s: s["report_month"])
                declared_emp = latest_sr["declared_employment_status"]

            # --- flags ---
            flags: list[str] = []
            bt = rec["benefit_type"]
            elig = eligibility.get(bt, {})

            if (
                elig.get("requires_unemployed", False)
                and actual_emp_status in ("employed", "part_time")
                and declared_emp in ("unemployed", "not_working")
            ):
                flags.append("EMPLOYMENT_MISMATCH")

            max_income = elig.get("max_monthly_income", float("inf"))
            if detected_monthly_income > max_income:
                flags.append("INCOME_OVER_LIMIT")

            if (
                total_deposits > deposit_threshold
                and total_deposits > total_declared * (1 + threshold_pct / 100)
            ):
                flags.append("UNDECLARED_DEPOSITS")

            if not flags:
                continue

            # --- discrepancy ---
            disc_emp = total_benefits if "EMPLOYMENT_MISMATCH" in flags else 0.0
            disc_inc = (
                min(
                    (detected_monthly_income - max_income) * num_review_months,
                    total_benefits,
                )
                if "INCOME_OVER_LIMIT" in flags
                else 0.0
            )
            disc_dep = (
                max(0.0, total_deposits - total_declared)
                if "UNDECLARED_DEPOSITS" in flags
                else 0.0
            )
            discrepancy_amount = round(max(disc_emp, disc_inc, disc_dep), 2)

            priority_score = 0
            if "EMPLOYMENT_MISMATCH" in flags:
                priority_score += weights["employment_mismatch"]
            if "INCOME_OVER_LIMIT" in flags:
                priority_score += weights["income_over_limit"]
            if "UNDECLARED_DEPOSITS" in flags:
                priority_score += weights["undeclared_deposits"]

            severity = "low"
            for label in ["critical", "high", "medium", "low"]:
                if priority_score >= sev_levels[label]:
                    severity = label
                    break

            flagged.append(
                {
                    "recipient_id": rid,
                    "recipient_name": rec["name"],
                    "benefit_type": bt,
                    "monthly_benefit": round(rec["monthly_benefit_amount"], 2),
                    "total_benefits_in_period": round(total_benefits, 2),
                    "discrepancy_amount": discrepancy_amount,
                    "priority_score": priority_score,
                    "severity": severity,
                    "flags": "|".join(flags),
                }
            )

        # sort
        flagged.sort(
            key=lambda x: (-x["priority_score"], -x["discrepancy_amount"])
        )

        # --- 5. Write investigation_report.csv ---
        cols = [
            "recipient_id",
            "recipient_name",
            "benefit_type",
            "monthly_benefit",
            "total_benefits_in_period",
            "discrepancy_amount",
            "priority_score",
            "severity",
            "flags",
        ]
        report_path = os.path.join(self.workspace, "investigation_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for row in flagged:
                writer.writerow(
                    {
                        "recipient_id": row["recipient_id"],
                        "recipient_name": row["recipient_name"],
                        "benefit_type": row["benefit_type"],
                        "monthly_benefit": f"{row['monthly_benefit']:.2f}",
                        "total_benefits_in_period": f"{row['total_benefits_in_period']:.2f}",
                        "discrepancy_amount": f"{row['discrepancy_amount']:.2f}",
                        "priority_score": row["priority_score"],
                        "severity": row["severity"],
                        "flags": row["flags"],
                    }
                )

        # --- 6. Construct action string ---
        action_parts = [
            f"Total flagged recipients: {len(flagged)}",
            "Top 3 cases by priority score:",
        ]
        for case in flagged[:3]:
            action_parts.append(
                f"  Recipient ID {case['recipient_id']}, "
                f"{case['recipient_name']}, "
                f"discrepancy amount: ${case['discrepancy_amount']:.2f}"
            )

        action = "\n".join(action_parts)

        # Sanity: tool call count
        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls — need at least 15"
        )

        return self.step(action)
