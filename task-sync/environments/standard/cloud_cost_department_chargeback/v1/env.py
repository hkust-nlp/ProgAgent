"""
Task environment for multi-cloud infrastructure spend reconciliation.
Provides tools for querying billing, tags, RI utilisation, and cost-centre data,
plus step/verify for evaluation.
"""
import sqlite3
import os
import json
import glob
import re
import math
from typing import Tuple, Dict, List, Any

import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Tool decorator
# ─────────────────────────────────────────────────────────────────────────────

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# Task_Env
# ─────────────────────────────────────────────────────────────────────────────

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

    # ═════════════════════════════════════════════════════════════════════════
    #  TOOLS
    # ═════════════════════════════════════════════════════════════════════════

    @tool(
        description="List all cloud providers present in the billing system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_cloud_providers(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT cloud_provider FROM billing_records ORDER BY cloud_provider")
        result = [r[0] for r in cur.fetchall()]
        conn.close()
        return {"cloud_providers": result}

    @tool(
        description="List all departments tracked in the cost-centre system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_departments(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT department FROM cost_centres ORDER BY department")
        result = [r[0] for r in cur.fetchall()]
        conn.close()
        return {"departments": result}

    @tool(
        description=(
            "Query billing records with optional filters.  Returns paginated results "
            "including resource_id, account_id, cloud_provider, service_type, region, "
            "date, and base_cost."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cloud_provider": {
                    "type": "string",
                    "description": "Filter by cloud provider (e.g. AWS, Azure, GCP)",
                },
                "account_id": {
                    "type": "string",
                    "description": "Filter by account ID",
                },
                "start_date": {
                    "type": "string",
                    "description": "Inclusive start date YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive end date YYYY-MM-DD",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed (default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (default 200)",
                },
            },
            "required": [],
        },
    )
    def query_billing(
        self,
        cloud_provider=None,
        account_id=None,
        start_date=None,
        end_date=None,
        page=1,
        page_size=200,
    ) -> dict:
        page = int(page) if page else 1
        page_size = int(page_size) if page_size else 200
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        where, params = ["1=1"], []
        if cloud_provider:
            where.append("cloud_provider = ?"); params.append(cloud_provider)
        if account_id:
            where.append("account_id = ?"); params.append(account_id)
        if start_date:
            where.append("date >= ?"); params.append(start_date)
        if end_date:
            where.append("date <= ?"); params.append(end_date)
        clause = " AND ".join(where)
        cur.execute(f"SELECT COUNT(*) FROM billing_records WHERE {clause}", params)
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT resource_id, account_id, cloud_provider, service_type, "
            f"region, date, base_cost FROM billing_records WHERE {clause} "
            f"ORDER BY date, resource_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        cols = ["resource_id", "account_id", "cloud_provider",
                "service_type", "region", "date", "base_cost"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return {
            "records": rows,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": max(1, math.ceil(total / page_size)),
        }

    @tool(
        description=(
            "Query resource-tag compliance records with optional filters.  "
            "Returns paginated results including resource_id, cloud_provider, "
            "account_id, department_tag, project_tag, environment_tag, owner_tag, "
            "and is_compliant."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cloud_provider": {
                    "type": "string",
                    "description": "Filter by cloud provider",
                },
                "is_compliant": {
                    "type": "boolean",
                    "description": "Filter by compliance status (true/false)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed (default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (default 100)",
                },
            },
            "required": [],
        },
    )
    def query_resource_tags(
        self, cloud_provider=None, is_compliant=None, page=1, page_size=100,
    ) -> dict:
        page = int(page) if page else 1
        page_size = int(page_size) if page_size else 100
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        where, params = ["1=1"], []
        if cloud_provider:
            where.append("cloud_provider = ?"); params.append(cloud_provider)
        if is_compliant is not None:
            where.append("is_compliant = ?")
            params.append(1 if is_compliant else 0)
        clause = " AND ".join(where)
        cur.execute(f"SELECT COUNT(*) FROM resource_tags WHERE {clause}", params)
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT resource_id, cloud_provider, account_id, department_tag, "
            f"project_tag, environment_tag, owner_tag, is_compliant "
            f"FROM resource_tags WHERE {clause} ORDER BY resource_id "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        cols = ["resource_id", "cloud_provider", "account_id", "department_tag",
                "project_tag", "environment_tag", "owner_tag", "is_compliant"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for row in rows:
            row["is_compliant"] = bool(row["is_compliant"])
        conn.close()
        return {
            "records": rows,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": max(1, math.ceil(total / page_size)),
        }

    @tool(
        description=(
            "Query reserved-instance utilisation records with optional filters.  "
            "Returns paginated results including ri_id, resource_id, cloud_provider, "
            "instance_type, region, date, hours_reserved, hours_used, utilisation_pct, "
            "ri_hourly_rate, and on_demand_rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cloud_provider": {
                    "type": "string",
                    "description": "Filter by cloud provider",
                },
                "ri_id": {
                    "type": "string",
                    "description": "Filter by reserved-instance ID",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed (default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (default 100)",
                },
            },
            "required": [],
        },
    )
    def query_ri_utilisation(
        self, cloud_provider=None, ri_id=None, page=1, page_size=100,
    ) -> dict:
        page = int(page) if page else 1
        page_size = int(page_size) if page_size else 100
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        where, params = ["1=1"], []
        if cloud_provider:
            where.append("cloud_provider = ?"); params.append(cloud_provider)
        if ri_id:
            where.append("ri_id = ?"); params.append(ri_id)
        clause = " AND ".join(where)
        cur.execute(f"SELECT COUNT(*) FROM ri_utilisation WHERE {clause}", params)
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT ri_id, resource_id, cloud_provider, instance_type, region, "
            f"date, hours_reserved, hours_used, utilisation_pct, ri_hourly_rate, "
            f"on_demand_rate FROM ri_utilisation WHERE {clause} "
            f"ORDER BY date, ri_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        cols = ["ri_id", "resource_id", "cloud_provider", "instance_type",
                "region", "date", "hours_reserved", "hours_used",
                "utilisation_pct", "ri_hourly_rate", "on_demand_rate"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return {
            "records": rows,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": max(1, math.ceil(total / page_size)),
        }

    @tool(
        description=(
            "Retrieve cost-centre budget records for a department, optionally "
            "filtered by budget period.  Returns cost_centre_id, department, "
            "sub_department, budget_period, budget_amount, carry_over, and manager."
        ),
        parameters={
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": "Department name (required)",
                },
                "budget_period": {
                    "type": "string",
                    "description": "Budget period e.g. 2025-01 (optional)",
                },
            },
            "required": ["department"],
        },
    )
    def get_cost_centre_budget(self, department: str, budget_period=None) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        where = ["department = ?"]
        params: list = [department]
        if budget_period:
            where.append("budget_period = ?"); params.append(budget_period)
        clause = " AND ".join(where)
        cur.execute(
            f"SELECT cost_centre_id, department, sub_department, budget_period, "
            f"budget_amount, carry_over, manager FROM cost_centres "
            f"WHERE {clause} ORDER BY sub_department, budget_period",
            params,
        )
        cols = ["cost_centre_id", "department", "sub_department",
                "budget_period", "budget_amount", "carry_over", "manager"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return {"records": rows, "total_records": len(rows)}

    # ═════════════════════════════════════════════════════════════════════════
    #  INTERNAL HELPERS
    # ═════════════════════════════════════════════════════════════════════════

    def _parse_yaml(self, path: str) -> dict:
        """Minimal YAML parser for the flat two-level structure we generate."""
        with open(path) as f:
            lines = f.readlines()
        result: Dict[str, dict] = {}
        section = None
        for raw in lines:
            stripped = raw.rstrip()
            if not stripped:
                continue
            if not raw[0].isspace() and stripped.endswith(":"):
                section = stripped[:-1]
                result[section] = {}
            elif section and ":" in stripped:
                key, val = stripped.strip().split(":", 1)
                key = key.strip()
                val = val.strip()
                try:
                    val = int(val)
                except ValueError:
                    try:
                        val = float(val)
                    except ValueError:
                        pass
                result[section][key] = val
        return result

    def _parse_budget_rules(self) -> dict:
        with open(os.path.join(self.workspace, "budget_rules.txt")) as f:
            text = f.read()
        threshold = 10.0
        period = "2025-01"
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("Over-budget threshold:"):
                threshold = float(line.split(":")[1].strip())
            if line.startswith("Billing period for current assessment:"):
                period = line.split(":", 1)[1].strip()
        return {"over_budget_threshold_pct": threshold, "billing_period": period}

    def _load_adjustments(self) -> pd.DataFrame:
        adj_files = sorted(glob.glob(os.path.join(self.workspace, "billing_adjustments_day_*.csv")))
        if not adj_files:
            return pd.DataFrame(columns=["resource_id", "date", "negotiated_discount_pct",
                                         "volume_credit", "support_tier_surcharge_pct"])
        return pd.concat([pd.read_csv(f) for f in adj_files], ignore_index=True)

    def _compute_ground_truth(self) -> dict:
        """Compute all ground-truth values from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        billing_df = pd.read_sql("SELECT * FROM billing_records", conn)
        tags_df = pd.read_sql("SELECT * FROM resource_tags", conn)
        ri_df = pd.read_sql("SELECT * FROM ri_utilisation", conn)
        cc_df = pd.read_sql("SELECT * FROM cost_centres", conn)
        conn.close()

        # Workspace files
        with open(os.path.join(self.workspace, "account_directory.json")) as f:
            acct_dir = json.load(f)
        with open(os.path.join(self.workspace, "department_headcount.json")) as f:
            headcount = json.load(f)
        shared_df = pd.read_csv(os.path.join(self.workspace, "shared_services_costs.csv"))
        total_shared_cost = float(shared_df["monthly_cost"].sum())

        policy = self._parse_yaml(os.path.join(self.workspace, "chargeback_policy.yaml"))
        nc_surcharge_pct = float(policy["tag_compliance"]["non_compliant_surcharge_pct"])
        ri_threshold = float(policy["ri_utilisation"]["underutilisation_threshold_pct"])
        ri_penalty_pct = float(policy["ri_utilisation"]["penalty_pct"])

        budget_rules = self._parse_budget_rules()
        over_budget_threshold = budget_rules["over_budget_threshold_pct"]
        billing_period = budget_rules["billing_period"]

        adj_df = self._load_adjustments()

        # Map billing → department via account directory
        billing_df["department"] = billing_df["account_id"].map(
            lambda aid: acct_dir.get(aid, {}).get("department", "Unknown")
        )

        # Join billing with adjustments
        merged = billing_df.merge(adj_df, on=["resource_id", "date"], how="left")
        for col in ["negotiated_discount_pct", "volume_credit", "support_tier_surcharge_pct"]:
            merged[col] = merged[col].fillna(0.0)

        merged["discount_amount"] = merged["base_cost"] * merged["negotiated_discount_pct"] / 100.0
        merged["surcharge_amount"] = merged["base_cost"] * merged["support_tier_surcharge_pct"] / 100.0
        merged["adjusted_cost"] = (
            merged["base_cost"]
            - merged["discount_amount"]
            + merged["surcharge_amount"]
            - merged["volume_credit"]
        )

        # ── Showback ────────────────────────────────────────────────────────
        showback = (
            merged.groupby(["department", "cloud_provider"])
            .agg(
                base_cost_total=("base_cost", "sum"),
                discount_total=("discount_amount", "sum"),
                surcharge_total=("surcharge_amount", "sum"),
                credit_total=("volume_credit", "sum"),
                adjusted_cost_total=("adjusted_cost", "sum"),
            )
            .reset_index()
        )
        for c in ["base_cost_total", "discount_total", "surcharge_total",
                   "credit_total", "adjusted_cost_total"]:
            showback[c] = showback[c].round(2)
        showback = showback.sort_values(["department", "cloud_provider"]).reset_index(drop=True)

        # ── Tag-compliance surcharge ────────────────────────────────────────
        nc_resources = set(tags_df.loc[tags_df["is_compliant"] == 0, "resource_id"])
        merged["is_nc"] = merged["resource_id"].isin(nc_resources)
        nc_cost_by_dept = merged.loc[merged["is_nc"]].groupby("department")["adjusted_cost"].sum()

        # ── RI penalty ──────────────────────────────────────────────────────
        res_to_acct = dict(zip(tags_df["resource_id"], tags_df["account_id"]))
        ri_df = ri_df.copy()
        ri_df["account_id"] = ri_df["resource_id"].map(res_to_acct)
        ri_df["department"] = ri_df["account_id"].map(
            lambda aid: acct_dir.get(str(aid), {}).get("department", "Unknown") if aid else "Unknown"
        )
        ri_under = ri_df[ri_df["utilisation_pct"] < ri_threshold].copy()
        ri_under["wasted_cost"] = ri_under["ri_hourly_rate"] * (
            ri_under["hours_reserved"] - ri_under["hours_used"]
        )
        ri_under["penalty"] = ri_under["wasted_cost"] * ri_penalty_pct / 100.0
        ri_penalty_by_dept = ri_under.groupby("department")["penalty"].sum()

        # ── Shared-services allocation ──────────────────────────────────────
        total_hc = sum(headcount.values())
        shared_alloc = {
            dept: round(total_shared_cost * hc / total_hc, 2)
            for dept, hc in headcount.items()
        }

        # ── Chargeback ─────────────────────────────────────────────────────
        showback_dept = merged.groupby("department")["adjusted_cost"].sum()
        all_depts = sorted(headcount.keys())
        cb_rows = []
        for dept in all_depts:
            sb = round(float(showback_dept.get(dept, 0)), 2)
            nc_sur = round(float(nc_cost_by_dept.get(dept, 0)) * nc_surcharge_pct / 100.0, 2)
            ri_pen = round(float(ri_penalty_by_dept.get(dept, 0)), 2)
            sh = shared_alloc.get(dept, 0.0)
            total_cb = round(sb + nc_sur + ri_pen + sh, 2)
            cb_rows.append({
                "department": dept,
                "showback_total": sb,
                "tag_compliance_surcharge": nc_sur,
                "ri_underutilisation_penalty": ri_pen,
                "shared_services_allocation": sh,
                "total_chargeback": total_cb,
            })
        chargeback_df = pd.DataFrame(cb_rows)

        # ── RI savings ─────────────────────────────────────────────────────
        ri_df["ri_cost"] = ri_df["ri_hourly_rate"] * ri_df["hours_reserved"]
        ri_df["od_equiv"] = ri_df["on_demand_rate"] * ri_df["hours_used"]
        ri_df["savings"] = ri_df["od_equiv"] - ri_df["ri_cost"]
        ri_savings = (
            ri_df.groupby(["department", "cloud_provider"])
            .agg(
                total_ri_cost=("ri_cost", "sum"),
                on_demand_equivalent=("od_equiv", "sum"),
                ri_savings=("savings", "sum"),
                avg_utilisation_pct=("utilisation_pct", "mean"),
            )
            .reset_index()
        )
        for c in ["total_ri_cost", "on_demand_equivalent", "ri_savings", "avg_utilisation_pct"]:
            ri_savings[c] = ri_savings[c].round(2)
        ri_savings = ri_savings.sort_values(["department", "cloud_provider"]).reset_index(drop=True)

        # ── Budget variance ────────────────────────────────────────────────
        period_cc = cc_df[cc_df["budget_period"] == billing_period]
        budget_agg = (
            period_cc.groupby("department")
            .agg(total_budget=("budget_amount", "sum"),
                 total_carry=("carry_over", "sum"))
            .reset_index()
        )
        budget_agg["effective_budget"] = (budget_agg["total_budget"] + budget_agg["total_carry"]).round(2)
        cb_map = dict(zip(chargeback_df["department"], chargeback_df["total_chargeback"]))
        var_rows = []
        for _, row in budget_agg.sort_values("department").iterrows():
            dept = row["department"]
            eff = row["effective_budget"]
            actual = cb_map.get(dept, 0.0)
            var = round(actual - eff, 2)
            var_pct = round((actual - eff) / eff * 100, 2) if eff != 0 else 0.0
            var_rows.append({
                "department": dept,
                "effective_budget": eff,
                "total_chargeback": actual,
                "variance": var,
                "variance_pct": var_pct,
            })
        variance_df = pd.DataFrame(var_rows)

        over_budget = sorted(
            variance_df.loc[variance_df["variance_pct"] > over_budget_threshold, "department"].tolist()
        )
        total_adjusted = round(float(merged["adjusted_cost"].sum()), 2)
        top_dept = chargeback_df.loc[chargeback_df["total_chargeback"].idxmax(), "department"]

        return {
            "showback": showback,
            "chargeback": chargeback_df,
            "ri_savings": ri_savings,
            "variance": variance_df,
            "total_adjusted_spend": total_adjusted,
            "top_department": top_dept,
            "over_budget_departments": over_budget,
        }

    # ═════════════════════════════════════════════════════════════════════════
    #  STEP  (evaluation)
    # ═════════════════════════════════════════════════════════════════════════

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
        gt = self._compute_ground_truth()
        criteria: Dict[str, dict] = {}

        # -- helper: compare a CSV deliverable against ground-truth DataFrame --
        def _check_csv(filename: str, gt_df: pd.DataFrame, max_score: int,
                       float_cols: list, sort_cols: list) -> dict:
            path = os.path.join(self.workspace, filename)
            if not os.path.exists(path):
                return {"passed": False, "score": 0, "max_score": max_score,
                        "reason": f"{filename} not found"}
            try:
                agent_df = pd.read_csv(path)
            except Exception as e:
                return {"passed": False, "score": 0, "max_score": max_score,
                        "reason": f"Cannot read {filename}: {e}"}
            expected_cols = list(gt_df.columns)
            agent_cols = list(agent_df.columns)
            if agent_cols != expected_cols:
                return {"passed": False, "score": 0, "max_score": max_score,
                        "reason": f"Column mismatch: expected {expected_cols}, got {agent_cols}"}
            gt_s = gt_df.sort_values(sort_cols).reset_index(drop=True)
            ag_s = agent_df.sort_values(sort_cols).reset_index(drop=True)
            if len(ag_s) != len(gt_s):
                return {"passed": False, "score": max_score // 4, "max_score": max_score,
                        "reason": f"Row count: expected {len(gt_s)}, got {len(ag_s)}"}
            correct = 0
            for idx in range(len(gt_s)):
                ok = True
                for col in expected_cols:
                    gv = gt_s.at[idx, col]
                    av = ag_s.at[idx, col]
                    if col in float_cols:
                        try:
                            if abs(float(gv) - float(av)) > 0.015:
                                ok = False; break
                        except (ValueError, TypeError):
                            ok = False; break
                    else:
                        if str(gv).strip() != str(av).strip():
                            ok = False; break
                if ok:
                    correct += 1
            score = round(max_score * correct / len(gt_s))
            return {"passed": score == max_score, "score": score, "max_score": max_score}

        # 1. showback_report.csv (20 pts)
        criteria["showback_report"] = _check_csv(
            "showback_report.csv", gt["showback"], 20,
            ["base_cost_total", "discount_total", "surcharge_total",
             "credit_total", "adjusted_cost_total"],
            ["department", "cloud_provider"],
        )

        # 2. chargeback_report.csv (20 pts)
        criteria["chargeback_report"] = _check_csv(
            "chargeback_report.csv", gt["chargeback"], 20,
            ["showback_total", "tag_compliance_surcharge",
             "ri_underutilisation_penalty", "shared_services_allocation",
             "total_chargeback"],
            ["department"],
        )

        # 3. ri_savings_report.csv (15 pts)
        criteria["ri_savings_report"] = _check_csv(
            "ri_savings_report.csv", gt["ri_savings"], 15,
            ["total_ri_cost", "on_demand_equivalent", "ri_savings",
             "avg_utilisation_pct"],
            ["department", "cloud_provider"],
        )

        # 4. budget_variance.csv (15 pts)
        criteria["budget_variance"] = _check_csv(
            "budget_variance.csv", gt["variance"], 15,
            ["effective_budget", "total_chargeback", "variance", "variance_pct"],
            ["department"],
        )

        # 5. Total adjusted spend in response (10 pts)
        spend_match = re.search(r"TOTAL_ADJUSTED_SPEND:\s*([\d.,]+)", action or "")
        if spend_match:
            try:
                val = float(spend_match.group(1).replace(",", ""))
                if abs(val - gt["total_adjusted_spend"]) < 1.0:
                    criteria["total_adjusted_spend"] = {"passed": True, "score": 10, "max_score": 10}
                else:
                    criteria["total_adjusted_spend"] = {
                        "passed": False, "score": 0, "max_score": 10,
                        "reason": f"Expected ~{gt['total_adjusted_spend']}, got {val}",
                    }
            except (ValueError, TypeError):
                criteria["total_adjusted_spend"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": "Cannot parse spend value",
                }
        else:
            criteria["total_adjusted_spend"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "TOTAL_ADJUSTED_SPEND pattern not found",
            }

        # 6. Top department (10 pts)
        top_match = re.search(r"TOP_DEPARTMENT:\s*(\S+)", action or "")
        if top_match and top_match.group(1).strip() == gt["top_department"]:
            criteria["top_department"] = {"passed": True, "score": 10, "max_score": 10}
        else:
            criteria["top_department"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": f"Expected {gt['top_department']}",
            }

        # 7. Over-budget departments (10 pts)
        ob_match = re.search(r"OVER_BUDGET_DEPARTMENTS:\s*(.+)", action or "")
        if ob_match:
            raw = ob_match.group(1).strip()
            if raw.lower() == "none":
                reported = []
            else:
                reported = sorted([d.strip() for d in raw.split(",") if d.strip()])
            if reported == gt["over_budget_departments"]:
                criteria["over_budget_departments"] = {"passed": True, "score": 10, "max_score": 10}
            else:
                criteria["over_budget_departments"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Expected {gt['over_budget_departments']}, got {reported}",
                }
        else:
            criteria["over_budget_departments"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "OVER_BUDGET_DEPARTMENTS pattern not found",
            }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = total_score / max_score if max_score else 0.0
        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ═════════════════════════════════════════════════════════════════════════
    #  VERIFY  (self-test proving end-to-end solvability)
    # ═════════════════════════════════════════════════════════════════════════

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

        def _call(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ── 1.  Read workspace configuration files ──────────────────────────
        with open(os.path.join(self.workspace, "account_directory.json")) as f:
            acct_dir = json.load(f)
        with open(os.path.join(self.workspace, "department_headcount.json")) as f:
            headcount = json.load(f)
        shared_df = pd.read_csv(os.path.join(self.workspace, "shared_services_costs.csv"))
        total_shared_cost = float(shared_df["monthly_cost"].sum())

        policy = self._parse_yaml(os.path.join(self.workspace, "chargeback_policy.yaml"))
        nc_surcharge_pct = float(policy["tag_compliance"]["non_compliant_surcharge_pct"])
        ri_threshold = float(policy["ri_utilisation"]["underutilisation_threshold_pct"])
        ri_penalty_pct = float(policy["ri_utilisation"]["penalty_pct"])

        budget_rules = self._parse_budget_rules()
        over_budget_threshold = budget_rules["over_budget_threshold_pct"]
        billing_period = budget_rules["billing_period"]

        # Read all billing adjustment CSVs
        adj_df = self._load_adjustments()

        # ── 2.  Tool calls – gather data ────────────────────────────────────
        providers = _call("list_cloud_providers")["cloud_providers"]
        departments = _call("list_departments")["departments"]

        # Billing records (paginated, per provider)
        all_billing = []
        for prov in providers:
            pg = 1
            while True:
                res = _call("query_billing", cloud_provider=prov, page=pg, page_size=200)
                all_billing.extend(res["records"])
                if pg >= res["total_pages"]:
                    break
                pg += 1
        billing_df = pd.DataFrame(all_billing)

        # Resource tags (paginated)
        all_tags = []
        pg = 1
        while True:
            res = _call("query_resource_tags", page=pg, page_size=100)
            all_tags.extend(res["records"])
            if pg >= res["total_pages"]:
                break
            pg += 1
        tags_df = pd.DataFrame(all_tags)

        # RI utilisation (paginated)
        all_ri = []
        pg = 1
        while True:
            res = _call("query_ri_utilisation", page=pg, page_size=100)
            all_ri.extend(res["records"])
            if pg >= res["total_pages"]:
                break
            pg += 1
        ri_df = pd.DataFrame(all_ri)

        # Cost-centre budgets per department
        all_budgets = []
        for dept in departments:
            res = _call("get_cost_centre_budget", department=dept, budget_period=billing_period)
            all_budgets.extend(res["records"])
        budget_df = pd.DataFrame(all_budgets)

        # ── 3.  Compute ────────────────────────────────────────────────────

        # Map billing → department
        billing_df["department"] = billing_df["account_id"].map(
            lambda aid: acct_dir.get(aid, {}).get("department", "Unknown")
        )

        # Join billing with adjustments
        merged = billing_df.merge(adj_df, on=["resource_id", "date"], how="left")
        for col in ["negotiated_discount_pct", "volume_credit", "support_tier_surcharge_pct"]:
            merged[col] = merged[col].fillna(0.0)

        merged["discount_amount"] = merged["base_cost"] * merged["negotiated_discount_pct"] / 100.0
        merged["surcharge_amount"] = merged["base_cost"] * merged["support_tier_surcharge_pct"] / 100.0
        merged["adjusted_cost"] = (
            merged["base_cost"]
            - merged["discount_amount"]
            + merged["surcharge_amount"]
            - merged["volume_credit"]
        )

        # Showback
        showback = (
            merged.groupby(["department", "cloud_provider"])
            .agg(
                base_cost_total=("base_cost", "sum"),
                discount_total=("discount_amount", "sum"),
                surcharge_total=("surcharge_amount", "sum"),
                credit_total=("volume_credit", "sum"),
                adjusted_cost_total=("adjusted_cost", "sum"),
            )
            .reset_index()
        )
        for c in ["base_cost_total", "discount_total", "surcharge_total",
                   "credit_total", "adjusted_cost_total"]:
            showback[c] = showback[c].round(2)
        showback = showback.sort_values(["department", "cloud_provider"]).reset_index(drop=True)

        # Tag compliance surcharge
        nc_resources = set(tags_df.loc[tags_df["is_compliant"] == False, "resource_id"])  # noqa: E712
        merged["is_nc"] = merged["resource_id"].isin(nc_resources)
        nc_cost_by_dept = merged.loc[merged["is_nc"]].groupby("department")["adjusted_cost"].sum()

        # RI analysis
        res_to_acct = dict(zip(tags_df["resource_id"], tags_df["account_id"]))
        ri_df = ri_df.copy()
        ri_df["account_id"] = ri_df["resource_id"].map(res_to_acct)
        ri_df["department"] = ri_df["account_id"].map(
            lambda aid: acct_dir.get(str(aid), {}).get("department", "Unknown") if aid else "Unknown"
        )

        ri_under = ri_df[ri_df["utilisation_pct"] < ri_threshold].copy()
        ri_under["wasted_cost"] = ri_under["ri_hourly_rate"] * (
            ri_under["hours_reserved"] - ri_under["hours_used"]
        )
        ri_under["penalty"] = ri_under["wasted_cost"] * ri_penalty_pct / 100.0
        ri_penalty_by_dept = ri_under.groupby("department")["penalty"].sum()

        # Shared services
        total_hc = sum(headcount.values())
        shared_alloc = {
            dept: round(total_shared_cost * hc / total_hc, 2)
            for dept, hc in headcount.items()
        }

        # Chargeback
        showback_dept = merged.groupby("department")["adjusted_cost"].sum()
        all_depts = sorted(headcount.keys())
        cb_rows = []
        for dept in all_depts:
            sb = round(float(showback_dept.get(dept, 0)), 2)
            nc_sur = round(float(nc_cost_by_dept.get(dept, 0)) * nc_surcharge_pct / 100.0, 2)
            ri_pen = round(float(ri_penalty_by_dept.get(dept, 0)), 2)
            sh = shared_alloc.get(dept, 0.0)
            total_cb = round(sb + nc_sur + ri_pen + sh, 2)
            cb_rows.append({
                "department": dept,
                "showback_total": sb,
                "tag_compliance_surcharge": nc_sur,
                "ri_underutilisation_penalty": ri_pen,
                "shared_services_allocation": sh,
                "total_chargeback": total_cb,
            })
        chargeback_df = pd.DataFrame(cb_rows)

        # RI savings report
        ri_df["ri_cost"] = ri_df["ri_hourly_rate"] * ri_df["hours_reserved"]
        ri_df["od_equiv"] = ri_df["on_demand_rate"] * ri_df["hours_used"]
        ri_df["savings"] = ri_df["od_equiv"] - ri_df["ri_cost"]
        ri_savings = (
            ri_df.groupby(["department", "cloud_provider"])
            .agg(
                total_ri_cost=("ri_cost", "sum"),
                on_demand_equivalent=("od_equiv", "sum"),
                ri_savings=("savings", "sum"),
                avg_utilisation_pct=("utilisation_pct", "mean"),
            )
            .reset_index()
        )
        for c in ["total_ri_cost", "on_demand_equivalent", "ri_savings", "avg_utilisation_pct"]:
            ri_savings[c] = ri_savings[c].round(2)
        ri_savings = ri_savings.sort_values(["department", "cloud_provider"]).reset_index(drop=True)

        # Budget variance
        budget_agg = (
            budget_df.groupby("department")
            .agg(total_budget=("budget_amount", "sum"),
                 total_carry=("carry_over", "sum"))
            .reset_index()
        )
        budget_agg["effective_budget"] = (budget_agg["total_budget"] + budget_agg["total_carry"]).round(2)
        cb_map = dict(zip(chargeback_df["department"], chargeback_df["total_chargeback"]))
        var_rows = []
        for _, row in budget_agg.sort_values("department").iterrows():
            dept = row["department"]
            eff = row["effective_budget"]
            actual = cb_map.get(dept, 0.0)
            var = round(actual - eff, 2)
            var_pct = round((actual - eff) / eff * 100, 2) if eff != 0 else 0.0
            var_rows.append({
                "department": dept,
                "effective_budget": eff,
                "total_chargeback": actual,
                "variance": var,
                "variance_pct": var_pct,
            })
        variance_df = pd.DataFrame(var_rows)

        over_budget = sorted(
            variance_df.loc[variance_df["variance_pct"] > over_budget_threshold, "department"].tolist()
        )
        total_adjusted = round(float(merged["adjusted_cost"].sum()), 2)
        top_dept = chargeback_df.loc[chargeback_df["total_chargeback"].idxmax(), "department"]

        # ── 4.  Write deliverables ─────────────────────────────────────────
        showback.to_csv(os.path.join(self.workspace, "showback_report.csv"), index=False)
        chargeback_df.to_csv(os.path.join(self.workspace, "chargeback_report.csv"), index=False)
        ri_savings.to_csv(os.path.join(self.workspace, "ri_savings_report.csv"), index=False)
        variance_df.to_csv(os.path.join(self.workspace, "budget_variance.csv"), index=False)

        # ── 5.  Final response ─────────────────────────────────────────────
        ob_str = ", ".join(over_budget) if over_budget else "None"
        action = (
            f"TOTAL_ADJUSTED_SPEND: {total_adjusted}\n"
            f"TOP_DEPARTMENT: {top_dept}\n"
            f"OVER_BUDGET_DEPARTMENTS: {ob_str}"
        )

        assert tool_call_count >= 15, (
            f"Tool-call floor not met: only {tool_call_count} calls made (need ≥15)"
        )

        return self.step(action)
