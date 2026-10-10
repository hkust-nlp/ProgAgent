"""Task environment for reinsurer quarterly profit commission validation."""

import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

import pandas as pd
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

    # ------------------------------------------------------------------ #
    #                           TOOL METHODS                              #
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "List all reinsurance treaties under review for the current quarter. "
            "Returns treaty identifiers, cedant names, and lines of business."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_treaties(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT treaty_id, cedant_name, line_of_business FROM treaties"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description=(
            "Get full details of a specific reinsurance treaty including "
            "inception/expiry dates, treaty type, and currency."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "The treaty identifier, e.g. TR-001",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_treaty_details(self, treaty_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM treaties WHERE treaty_id = ?", (treaty_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    @tool(
        description=(
            "Retrieve all ceded premium records for a specific treaty in the "
            "current quarter. Each record contains premium_id, month, "
            "written_premium, ceded_percentage, and ceded_premium."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "The treaty identifier",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_ceded_premiums(self, treaty_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM ceded_premiums WHERE treaty_id = ?", (treaty_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description=(
            "Retrieve all paid loss records for a specific treaty. Each record "
            "contains loss_id, claim_ref, incurred_date, paid_date, "
            "paid_amount, claim_status, and loss_category."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "The treaty identifier",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_paid_losses(self, treaty_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM paid_losses WHERE treaty_id = ?", (treaty_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @tool(
        description=(
            "Get the filed profit commission statement for a specific treaty. "
            "Returns reported figures including ceded premium, incurred losses, "
            "expense loading, carry-forward, loss ratio, commission rate, "
            "and commission amount."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "The treaty identifier",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_commission_statement(self, treaty_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM commission_statements WHERE treaty_id = ?",
            (treaty_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    @tool(
        description=(
            "Get the prior-year loss carry-forward record for a treaty. "
            "Returns opening_balance, adjustments, and closing_balance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "treaty_id": {
                    "type": "string",
                    "description": "The treaty identifier",
                },
            },
            "required": ["treaty_id"],
        },
    )
    def get_loss_carryforward(self, treaty_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM loss_carryforward WHERE treaty_id = ?",
            (treaty_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    # ------------------------------------------------------------------ #
    #                        GROUND TRUTH HELPER                          #
    # ------------------------------------------------------------------ #

    def _ground_truth(self) -> Dict[str, dict]:
        """Compute ground-truth commission for every treaty using DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        treaties = [dict(r) for r in conn.execute("SELECT * FROM treaties").fetchall()]

        with open(os.path.join(self.workspace, "sliding_scale_commission.yaml")) as f:
            sliding = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "expense_parameters.json")) as f:
            exp_params = json.load(f)

        truth: Dict[str, dict] = {}
        for t in treaties:
            tid = t["treaty_id"]
            lob = t["line_of_business"]

            total_cp = conn.execute(
                "SELECT COALESCE(SUM(ceded_premium),0) FROM ceded_premiums "
                "WHERE treaty_id=?", (tid,)
            ).fetchone()[0]

            total_paid = conn.execute(
                "SELECT COALESCE(SUM(paid_amount),0) FROM paid_losses "
                "WHERE treaty_id=?", (tid,)
            ).fetchone()[0]

            bord = os.path.join(self.workspace, f"bordereaux_{tid}.csv")
            total_lae = 0.0
            if os.path.exists(bord):
                bdf = pd.read_csv(bord)
                if not bdf.empty and "lae_amount" in bdf.columns:
                    total_lae = float(bdf["lae_amount"].sum())

            total_inc = total_paid + total_lae
            exp_pct = exp_params[tid]["total_expense_pct"]
            exp_load = total_cp * exp_pct

            cf_row = conn.execute(
                "SELECT closing_balance FROM loss_carryforward WHERE treaty_id=?",
                (tid,),
            ).fetchone()
            cf_bal = cf_row[0] if cf_row else 0.0

            lr = total_inc / total_cp if total_cp else 0.0
            rate = 0.0
            for b in sliding[lob]:
                if b["min_lr"] <= lr < b["max_lr"]:
                    rate = b["rate"]
                    break

            net = total_cp - total_inc - exp_load - cf_bal
            comm = round(net * rate, 2) if net > 0 else 0.0

            stmt = dict(conn.execute(
                "SELECT * FROM commission_statements WHERE treaty_id=?", (tid,)
            ).fetchone())
            rep_comm = stmt["reported_commission_amount"]
            var = round(rep_comm - comm, 2)
            status = "APPROVED" if abs(var) < 1.0 else "DISCREPANCY"

            truth[tid] = {
                "cedant_name": t["cedant_name"],
                "expected_status": status,
                "calculated_commission": comm,
                "reported_commission": rep_comm,
                "variance": var,
            }

        conn.close()
        return truth

    # ------------------------------------------------------------------ #
    #                           EVALUATION                                #
    # ------------------------------------------------------------------ #

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        truth = self._ground_truth()
        num_treaties = len(truth)

        eval_criteria: Dict[str, dict] = {}

        # ---- C1: report structure (10 pts) ----
        c1_max = 10
        c1_score = 0
        c1_reason = ""
        report_path = os.path.join(self.workspace, "validation_report.csv")
        required_cols = {
            "treaty_id", "cedant_name", "status",
            "reported_commission", "calculated_commission",
            "variance", "discrepancy_reason",
        }
        report_rows: Dict[str, Any] = {}

        if os.path.exists(report_path):
            try:
                rdf = pd.read_csv(report_path, dtype=str)
                rdf.columns = [c.strip() for c in rdf.columns]
                if required_cols.issubset(set(rdf.columns)):
                    c1_score = 10
                    for _, row in rdf.iterrows():
                        report_rows[row["treaty_id"].strip()] = row
                else:
                    missing = required_cols - set(rdf.columns)
                    c1_reason = f"Missing columns: {missing}"
            except Exception as e:
                c1_reason = f"CSV parse error: {e}"
        else:
            c1_reason = "validation_report.csv not found"

        eval_criteria["report_structure"] = {
            "passed": c1_score == c1_max,
            "score": c1_score,
            "max_score": c1_max,
        }
        if c1_reason:
            eval_criteria["report_structure"]["reason"] = c1_reason

        # ---- C2: treaty coverage (10 pts) ----
        c2_max = 10
        covered = sum(1 for tid in truth if tid in report_rows)
        c2_score = round(c2_max * covered / num_treaties) if num_treaties else 0
        eval_criteria["treaty_coverage"] = {
            "passed": c2_score == c2_max,
            "score": c2_score,
            "max_score": c2_max,
        }
        if c2_score < c2_max:
            eval_criteria["treaty_coverage"]["reason"] = (
                f"Only {covered}/{num_treaties} treaties in report"
            )

        # ---- C3: status accuracy (25 pts) ----
        c3_max = 25
        correct_status = 0
        for tid, gt in truth.items():
            if tid in report_rows:
                agent_status = report_rows[tid]["status"].strip().upper()
                if agent_status == gt["expected_status"]:
                    correct_status += 1
        c3_score = round(c3_max * correct_status / num_treaties) if num_treaties else 0
        eval_criteria["status_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
        }
        if c3_score < c3_max:
            eval_criteria["status_accuracy"]["reason"] = (
                f"{correct_status}/{num_treaties} statuses correct"
            )

        # ---- C4: commission calculation accuracy (25 pts) ----
        c4_max = 25
        correct_comm = 0
        for tid, gt in truth.items():
            if tid in report_rows:
                try:
                    calc = float(report_rows[tid]["calculated_commission"])
                    if abs(calc - gt["calculated_commission"]) < 1.0:
                        correct_comm += 1
                except (ValueError, KeyError):
                    pass
        c4_score = round(c4_max * correct_comm / num_treaties) if num_treaties else 0
        eval_criteria["commission_calculation"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
        }
        if c4_score < c4_max:
            eval_criteria["commission_calculation"]["reason"] = (
                f"{correct_comm}/{num_treaties} commissions within tolerance"
            )

        # ---- C5: variance accuracy (15 pts) ----
        c5_max = 15
        correct_var = 0
        for tid, gt in truth.items():
            if tid in report_rows:
                try:
                    v = float(report_rows[tid]["variance"])
                    if abs(v - gt["variance"]) < 1.0:
                        correct_var += 1
                except (ValueError, KeyError):
                    pass
        c5_score = round(c5_max * correct_var / num_treaties) if num_treaties else 0
        eval_criteria["variance_accuracy"] = {
            "passed": c5_score == c5_max,
            "score": c5_score,
            "max_score": c5_max,
        }
        if c5_score < c5_max:
            eval_criteria["variance_accuracy"]["reason"] = (
                f"{correct_var}/{num_treaties} variances within tolerance"
            )

        # ---- C6: summary response (15 pts) ----
        c6_max = 15
        c6_score = 0
        n_disc = sum(
            1 for g in truth.values() if g["expected_status"] == "DISCREPANCY"
        )
        n_appr = num_treaties - n_disc
        total_var = round(
            sum(g["variance"] for g in truth.values()
                if g["expected_status"] == "DISCREPANCY"),
            2,
        )

        # Check counts in response
        if re.search(r'\b' + str(n_disc) + r'\b', action):
            c6_score += 5
        if re.search(r'\b' + str(n_appr) + r'\b', action):
            c6_score += 5

        # Check total variance (allow sign-agnostic match)
        numbers = re.findall(r"-?[\d,]+\.?\d*", action.replace(",", ""))
        for ns in numbers:
            try:
                nv = float(ns)
                tol = max(1.0, abs(total_var) * 0.05 + 0.01)
                if (abs(nv - total_var) < tol
                        or abs(nv - abs(total_var)) < tol):
                    c6_score += 5
                    break
            except ValueError:
                pass

        eval_criteria["summary_response"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
        }
        if c6_score < c6_max:
            eval_criteria["summary_response"]["reason"] = (
                f"Expected {n_appr} approved, {n_disc} discrepancies, "
                f"total variance {total_var}"
            )

        # ---- aggregate ----
        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return (total_score / max_score if max_score else 0.0), {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------ #
    #                          VERIFICATION                               #
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
        # ---- read workspace config files ----
        with open(os.path.join(self.workspace,
                               "sliding_scale_commission.yaml")) as f:
            sliding = yaml.safe_load(f)
        with open(os.path.join(self.workspace,
                               "expense_parameters.json")) as f:
            exp_params = json.load(f)

        # ---- gather treaty list ----
        treaties = self.tools["list_treaties"]()
        tool_calls = 1  # list_treaties

        results: list[dict] = []

        for t_info in treaties:
            tid = t_info["treaty_id"]

            # treaty details (need line_of_business)
            details = self.tools["get_treaty_details"](treaty_id=tid)
            tool_calls += 1
            lob = details["line_of_business"]

            # commission statement (reported values)
            stmt = self.tools["get_commission_statement"](treaty_id=tid)
            tool_calls += 1

            # ceded premiums
            prems = self.tools["get_ceded_premiums"](treaty_id=tid)
            tool_calls += 1
            total_cp = sum(p["ceded_premium"] for p in prems)

            # paid losses
            losses = self.tools["get_paid_losses"](treaty_id=tid)
            tool_calls += 1
            total_paid = sum(l["paid_amount"] for l in losses)

            # LAE from bordereaux file
            bord_path = os.path.join(self.workspace, f"bordereaux_{tid}.csv")
            bdf = pd.read_csv(bord_path)
            total_lae = (float(bdf["lae_amount"].sum())
                         if not bdf.empty and "lae_amount" in bdf.columns
                         else 0.0)
            total_inc = total_paid + total_lae

            # expense loading
            ep = exp_params[tid]
            exp_load = total_cp * ep["total_expense_pct"]

            # loss carry-forward
            cf = self.tools["get_loss_carryforward"](treaty_id=tid)
            tool_calls += 1
            cf_bal = cf["closing_balance"]

            # loss ratio & sliding-scale rate
            lr = total_inc / total_cp if total_cp else 0.0
            rate = 0.0
            for b in sliding[lob]:
                if b["min_lr"] <= lr < b["max_lr"]:
                    rate = b["rate"]
                    break

            # net profit & commission
            net = total_cp - total_inc - exp_load - cf_bal
            calc_comm = round(net * rate, 2) if net > 0 else 0.0

            # compare
            rep_comm = stmt["reported_commission_amount"]
            var = round(rep_comm - calc_comm, 2)

            if abs(var) < 1.0:
                status = "APPROVED"
                reason = ""
            else:
                status = "DISCREPANCY"
                reasons: list[str] = []
                if abs(stmt["reported_incurred_losses"]
                       - round(total_inc, 2)) > 1.0:
                    reasons.append(
                        "Incurred losses mismatch (possible LAE omission)"
                    )
                if abs(stmt["reported_carryforward"]
                       - round(cf_bal, 2)) > 1.0:
                    reasons.append("Loss carry-forward mismatch")
                if abs(stmt["reported_commission_rate"] - rate) > 0.001:
                    reasons.append(
                        "Commission rate mismatch (wrong sliding-scale bracket)"
                    )
                if abs(stmt["reported_ceded_premium"]
                       - round(total_cp, 2)) > 1.0:
                    reasons.append("Ceded premium mismatch")
                if not reasons:
                    reasons.append(
                        "Commission amount variance exceeds tolerance"
                    )
                reason = "; ".join(reasons)

            results.append({
                "treaty_id": tid,
                "cedant_name": details["cedant_name"],
                "status": status,
                "reported_commission": rep_comm,
                "calculated_commission": calc_comm,
                "variance": var,
                "discrepancy_reason": reason,
            })

        # ---- write deliverable ----
        rdf = pd.DataFrame(results)
        rdf.to_csv(
            os.path.join(self.workspace, "validation_report.csv"), index=False
        )

        # ---- build action summary ----
        n_appr = sum(1 for r in results if r["status"] == "APPROVED")
        n_disc = sum(1 for r in results if r["status"] == "DISCREPANCY")
        total_var = round(
            sum(r["variance"] for r in results if r["status"] == "DISCREPANCY"),
            2,
        )

        action = (
            f"Validation complete. {n_appr} treaties approved, "
            f"{n_disc} discrepancies found. "
            f"Total variance: {total_var:.2f}. "
            f"Detailed findings saved as validation_report.csv."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made"
        return self.step(action)
