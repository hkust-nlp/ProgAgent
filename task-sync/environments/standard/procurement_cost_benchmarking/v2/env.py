import json
import os
import re
import sqlite3
import csv
import glob
import math
from typing import Tuple, Dict, List, Any

import yaml


# --- Decorator for tool registration ---
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

    # ================================================================== #
    # Tool methods                                                        #
    # ================================================================== #

    @tool(
        description=(
            "List vendors registered in the procurement system. "
            "Returns paginated results with basic vendor information."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                    "default": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 15).",
                    "default": 15,
                },
            },
            "required": [],
        },
    )
    def list_vendors(self, page: int = 1, page_size: int = 15) -> dict:
        page_size = min(page_size, 15)
        offset = (max(1, page) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vendors")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM vendors ORDER BY vendor_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size),
            "vendors": rows,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Query vendor financial reports for a given fiscal year. "
            "Returns paginated financial summaries including revenue, "
            "debt, assets, current ratio, and credit score."
        ),
        parameters={
            "type": "object",
            "properties": {
                "fiscal_year": {
                    "type": "integer",
                    "description": "The fiscal year to retrieve financials for.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                    "default": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 15).",
                    "default": 15,
                },
            },
            "required": ["fiscal_year"],
        },
    )
    def query_vendor_financials(
        self, fiscal_year: int, page: int = 1, page_size: int = 15
    ) -> dict:
        page_size = min(page_size, 15)
        offset = (max(1, page) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM vendor_financials WHERE fiscal_year = ?",
            (fiscal_year,),
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM vendor_financials WHERE fiscal_year = ? "
            "ORDER BY vendor_id LIMIT ? OFFSET ?",
            (fiscal_year, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return _envelope({
            "fiscal_year": fiscal_year,
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "records": rows,
        })

    @tool(
        description=(
            "Search historical bid records with optional filters by "
            "procurement category and/or vendor ID. Returns paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by procurement category.",
                },
                "vendor_id": {
                    "type": "integer",
                    "description": "Filter by vendor ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                    "default": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
    )
    def search_historical_bids(
        self,
        category: str = None,
        vendor_id: int = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page_size = min(page_size, 20)
        offset = (max(1, page) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        where_clauses = []
        params: list = []
        if category is not None:
            where_clauses.append("category = ?")
            params.append(category)
        if vendor_id is not None:
            where_clauses.append("vendor_id = ?")
            params.append(vendor_id)
        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(f"SELECT COUNT(*) FROM historical_bids{where_sql}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT * FROM historical_bids{where_sql} ORDER BY bid_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({
            "page": page,
            "page_size": page_size,
            "total_records": total,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "bids": rows,
        }, ensure_ascii=False, default=str)

    @tool(
        description=(
            "Retrieve the material price index for a specific procurement "
            "category, year, and quarter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "The procurement/material category.",
                },
                "year": {
                    "type": "integer",
                    "description": "Calendar year.",
                },
                "quarter": {
                    "type": "integer",
                    "description": "Quarter (1-4).",
                },
            },
            "required": ["category", "year", "quarter"],
        },
    )
    def get_material_price_index(
        self, category: str, year: int, quarter: int
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM material_price_indices "
            "WHERE material_category = ? AND year = ? AND quarter = ?",
            (category, year, quarter),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return _envelope(dict(row))
        return _envelope({"error": f"No index found for {category} {year} Q{quarter}."})

    @tool(
        description=(
            "Retrieve the budget allocation for a specific procurement "
            "category and fiscal year."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "The procurement category.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "The fiscal year.",
                },
            },
            "required": ["category", "fiscal_year"],
        },
    )
    def get_budget_allocation(self, category: str, fiscal_year: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM budget_forecasts "
            "WHERE category = ? AND fiscal_year = ? LIMIT 1",
            (category, fiscal_year),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return json.dumps(dict(row), ensure_ascii=False, default=str)
        return json.dumps({"error": f"No budget found for {category} FY{fiscal_year}."}, ensure_ascii=False, default=str)

    # ================================================================== #
    # Internal helpers (used by step / verify)                            #
    # ================================================================== #

    def _read_config(self):
        """Read workspace config files and return parsed dicts."""
        with open(os.path.join(self.workspace, "scoring_weights.yaml")) as f:
            weights = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "eligibility_criteria.json")) as f:
            eligibility = json.load(f)
        with open(os.path.join(self.workspace, "market_forecast.json")) as f:
            forecast = json.load(f)
        return weights, eligibility, forecast

    def _read_workspace_vendor_data(self):
        """Read operational_risk_rating and past_delivery_score from workspace files."""
        operational_risk = {}
        delivery_scores = {}

        # vendor dossiers (.md) — operational_risk_rating
        for fp in sorted(glob.glob(os.path.join(self.workspace, "vendor_dossier_*.md"))):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(
                r"## Vendor (\d+):.*?\n.*?Operational Risk Rating:\s*([\d.]+)",
                content,
                re.DOTALL,
            ):
                vid = int(m.group(1))
                operational_risk[vid] = float(m.group(2))

        # performance data (.csv) — past_delivery_score
        for fp in sorted(glob.glob(os.path.join(self.workspace, "performance_data_*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    vid = int(row["vendor_id"])
                    delivery_scores[vid] = float(row["past_delivery_score"])

        return operational_risk, delivery_scores

    def _compute_expected(self):
        """Compute expected benchmark results from DB + workspace."""
        weights, eligibility, forecast = self._read_config()
        operational_risk, delivery_scores = self._read_workspace_vendor_data()

        ref_year = eligibility["reference_fiscal_year"]
        proc_year = eligibility["procurement_year"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # --- eligible vendors ---
        vendors_all = [
            dict(r)
            for r in conn.execute("SELECT * FROM vendors ORDER BY vendor_id").fetchall()
        ]
        financials_ref = {
            r["vendor_id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM vendor_financials WHERE fiscal_year = ?", (ref_year,)
            ).fetchall()
        }

        eligible = {}
        for v in vendors_all:
            vid = v["vendor_id"]
            if eligibility.get("must_be_active") and not v["active"]:
                continue
            fin = financials_ref.get(vid)
            if not fin:
                continue
            if fin["credit_score"] < eligibility["min_credit_score"]:
                continue
            if fin["current_ratio"] < eligibility["min_current_ratio"]:
                continue
            dta = fin["total_debt"] / fin["total_assets"] if fin["total_assets"] else 1.0
            if dta > eligibility["max_debt_to_asset_ratio"]:
                continue
            years_active = proc_year - v["incorporation_year"]
            if years_active < eligibility["min_years_active"]:
                continue
            eligible[vid] = {**v, "financials": fin, "debt_to_asset": dta}

        # --- risk scores ---
        rsw = weights["risk_score_weights"]
        fhw = weights["financial_health_sub_weights"]
        norm = weights["normalization"]

        risk_scores = {}
        for vid, info in eligible.items():
            fin = info["financials"]
            cs_norm = (fin["credit_score"] - norm["credit_score_min"]) / norm["credit_score_range"]
            cr_norm = min(fin["current_ratio"] / norm["current_ratio_cap"], 1.0)
            lev = 1.0 - info["debt_to_asset"]
            fh = (
                fhw["credit_score_normalized"] * cs_norm
                + fhw["current_ratio_normalized"] * cr_norm
                + fhw["leverage_score"] * lev
            )
            opr = operational_risk.get(vid, 3.0)
            opr_score = (5.0 - opr) / 4.0
            ds = delivery_scores.get(vid, 70.0) / 100.0
            composite = (
                rsw["financial_health"] * fh
                + rsw["operational_risk"] * opr_score
                + rsw["delivery_track_record"] * ds
            )
            risk_scores[vid] = round(composite, 4)

        # --- historical avg bids per (vendor, category) ---
        bids = [
            dict(r) for r in conn.execute("SELECT * FROM historical_bids").fetchall()
        ]
        from collections import defaultdict

        bid_sums = defaultdict(lambda: [0.0, 0])
        for b in bids:
            key = (b["vendor_id"], b["category"])
            bid_sums[key][0] += b["bid_amount"]
            bid_sums[key][1] += 1
        avg_bids = {k: v[0] / v[1] for k, v in bid_sums.items()}

        # --- price adjustment ---
        pa = weights["price_adjustment"]
        categories = sorted(
            set(cat for (_, cat) in avg_bids.keys())
        )
        price_adj_factors = {}
        for cat in categories:
            ref_row = conn.execute(
                "SELECT index_value FROM material_price_indices "
                "WHERE material_category=? AND year=? AND quarter=?",
                (cat, pa["reference_year"], pa["reference_quarter"]),
            ).fetchone()
            base_row = conn.execute(
                "SELECT index_value FROM material_price_indices "
                "WHERE material_category=? AND year=? AND quarter=?",
                (cat, pa["base_year"], pa["base_quarter"]),
            ).fetchone()
            if ref_row and base_row:
                ref_val = ref_row["index_value"]
                base_val = base_row["index_value"]
            else:
                ref_val = base_val = 100.0
            fa = forecast["category_adjustments"].get(cat, {}).get(
                "forecast_adjustment_factor", 1.0
            )
            price_adj_factors[cat] = (ref_val / base_val) * fa

        # --- risk premium ---
        rp_cfg = weights["risk_premium"]

        # --- build benchmark rows ---
        report_rows = []
        for (vid, cat), avg_bid in avg_bids.items():
            if vid not in eligible:
                continue
            paf = price_adj_factors.get(cat, 1.0)
            pab = avg_bid * paf
            rs = risk_scores[vid]
            rp = rp_cfg["base"] + rp_cfg["scale_factor"] * (1 - rs)
            rac = pab * (1 + rp)
            report_rows.append({
                "category": cat,
                "vendor_id": vid,
                "vendor_name": eligible[vid]["vendor_name"],
                "historical_avg_bid": round(avg_bid, 2),
                "price_adjustment_factor": round(paf, 4),
                "price_adjusted_bid": round(pab, 2),
                "risk_score": round(rs, 4),
                "risk_premium": round(rp, 4),
                "risk_adjusted_cost": round(rac, 2),
            })

        report_rows.sort(key=lambda r: (r["category"], r["risk_adjusted_cost"]))

        # --- category summary ---
        cat_summary = {}
        for cat in sorted(set(r["category"] for r in report_rows)):
            cat_rows = [r for r in report_rows if r["category"] == cat]
            costs = [r["risk_adjusted_cost"] for r in cat_rows]
            median_cost = round(float(sorted(costs)[len(costs) // 2]) if len(costs) % 2 == 1
                                else float((sorted(costs)[len(costs) // 2 - 1] + sorted(costs)[len(costs) // 2]) / 2), 2)
            best = cat_rows[0]
            budget_row = conn.execute(
                "SELECT allocated_budget FROM budget_forecasts WHERE category=? AND fiscal_year=? LIMIT 1",
                (cat, proc_year),
            ).fetchone()
            budget_alloc = budget_row["allocated_budget"] if budget_row else 0.0
            cat_summary[cat] = {
                "benchmark_cost": median_cost,
                "min_cost": round(min(costs), 2),
                "max_cost": round(max(costs), 2),
                "num_eligible_vendors": len(cat_rows),
                "recommended_vendor_id": best["vendor_id"],
                "recommended_vendor_name": best["vendor_name"],
                "budget_allocation": round(budget_alloc, 2),
                "within_budget": median_cost <= budget_alloc,
            }

        # --- overall ---
        total_cost = round(sum(cs["benchmark_cost"] for cs in cat_summary.values()), 2)
        all_rs = [risk_scores[vid] for vid in eligible]
        avg_rs = sum(all_rs) / len(all_rs) if all_rs else 0.0
        if avg_rs >= 0.7:
            rating = "LOW"
        elif avg_rs >= 0.4:
            rating = "MEDIUM"
        else:
            rating = "HIGH"
        cats_within = sum(1 for cs in cat_summary.values() if cs["within_budget"])

        conn.close()

        return {
            "report_rows": report_rows,
            "cat_summary": cat_summary,
            "total_cost": total_cost,
            "avg_risk_score": round(avg_rs, 4),
            "overall_rating": rating,
            "cats_within_budget": cats_within,
            "total_categories": len(cat_summary),
        }

    # ================================================================== #
    # step                                                                #
    # ================================================================== #

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        expected = self._compute_expected()
        criteria: Dict[str, Dict[str, Any]] = {}

        # ---- 1. benchmark_report.csv structure (10 pts) ----
        report_path = os.path.join(self.workspace, "benchmark_report.csv")
        expected_cols = [
            "category", "vendor_id", "vendor_name",
            "historical_avg_bid", "price_adjustment_factor",
            "price_adjusted_bid", "risk_score", "risk_premium",
            "risk_adjusted_cost",
        ]
        if os.path.exists(report_path):
            with open(report_path) as f:
                reader = csv.DictReader(f)
                actual_rows = list(reader)
                actual_cols = reader.fieldnames or []
            cols_ok = all(c in actual_cols for c in expected_cols)
            rows_count_ok = len(actual_rows) == len(expected["report_rows"])
            passed = cols_ok and rows_count_ok
            reason = ""
            if not cols_ok:
                reason += f"Missing columns: {set(expected_cols) - set(actual_cols)}. "
            if not rows_count_ok:
                reason += f"Expected {len(expected['report_rows'])} rows, got {len(actual_rows)}. "
            criteria["benchmark_report_structure"] = {
                "passed": passed,
                "score": 10 if passed else 0,
                "max_score": 10,
                "reason": reason or None,
            }
        else:
            actual_rows = []
            criteria["benchmark_report_structure"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "benchmark_report.csv not found.",
            }

        # ---- 2. benchmark_report.csv values (25 pts) ----
        if actual_rows and criteria["benchmark_report_structure"]["passed"]:
            # Build lookup: (category, vendor_id) -> expected row
            exp_lookup = {}
            for er in expected["report_rows"]:
                exp_lookup[(er["category"], er["vendor_id"])] = er
            correct = 0
            total_checks = 0
            for ar in actual_rows:
                try:
                    key = (ar["category"].strip(), int(ar["vendor_id"]))
                except (ValueError, KeyError):
                    total_checks += 3
                    continue
                er = exp_lookup.get(key)
                if not er:
                    total_checks += 3
                    continue
                # check 3 key values with tolerance
                for field in ["price_adjusted_bid", "risk_score", "risk_adjusted_cost"]:
                    total_checks += 1
                    try:
                        av = float(ar.get(field, ""))
                        ev = er[field]
                        tol = 0.015 if field == "risk_score" else max(1.0, abs(ev) * 0.005)
                        if abs(av - ev) <= tol:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            pct = correct / total_checks if total_checks else 0
            score = round(25 * pct)
            criteria["benchmark_report_values"] = {
                "passed": pct >= 0.95,
                "score": score,
                "max_score": 25,
                "reason": f"{correct}/{total_checks} value checks passed." if pct < 1.0 else None,
            }
        else:
            criteria["benchmark_report_values"] = {
                "passed": False,
                "score": 0,
                "max_score": 25,
                "reason": "Cannot evaluate values without valid report structure.",
            }

        # ---- 3. benchmark_report.csv sorting (10 pts) ----
        if actual_rows and len(actual_rows) > 1:
            sorted_ok = True
            for i in range(len(actual_rows) - 1):
                cat_a = actual_rows[i].get("category", "").strip()
                cat_b = actual_rows[i + 1].get("category", "").strip()
                try:
                    cost_a = float(actual_rows[i].get("risk_adjusted_cost", 0))
                    cost_b = float(actual_rows[i + 1].get("risk_adjusted_cost", 0))
                except ValueError:
                    sorted_ok = False
                    break
                if cat_a > cat_b:
                    sorted_ok = False
                    break
                if cat_a == cat_b and cost_a > cost_b + 0.01:
                    sorted_ok = False
                    break
            criteria["benchmark_report_sorting"] = {
                "passed": sorted_ok,
                "score": 10 if sorted_ok else 0,
                "max_score": 10,
                "reason": None if sorted_ok else "Rows not sorted by category ASC then risk_adjusted_cost ASC.",
            }
        else:
            criteria["benchmark_report_sorting"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "Insufficient rows to evaluate sorting.",
            }

        # ---- 4. category_summary.json structure (10 pts) ----
        summary_path = os.path.join(self.workspace, "category_summary.json")
        expected_cats = set(expected["cat_summary"].keys())
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                try:
                    actual_summary = json.load(f)
                except json.JSONDecodeError:
                    actual_summary = {}
            actual_cats = set(actual_summary.keys())
            required_fields = [
                "benchmark_cost", "num_eligible_vendors",
                "recommended_vendor_id", "budget_allocation", "within_budget",
            ]
            fields_ok = all(
                all(fld in actual_summary.get(cat, {}) for fld in required_fields)
                for cat in expected_cats if cat in actual_summary
            )
            cats_ok = expected_cats == actual_cats
            passed = cats_ok and fields_ok
            reason = ""
            if not cats_ok:
                reason += f"Category mismatch: expected {expected_cats}, got {actual_cats}. "
            if not fields_ok:
                reason += "Some required fields missing. "
            criteria["category_summary_structure"] = {
                "passed": passed,
                "score": 10 if passed else 0,
                "max_score": 10,
                "reason": reason or None,
            }
        else:
            actual_summary = {}
            criteria["category_summary_structure"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "category_summary.json not found.",
            }

        # ---- 5. category_summary.json values (20 pts) ----
        if actual_summary and criteria["category_summary_structure"]["passed"]:
            checks = 0
            correct = 0
            for cat, exp_cs in expected["cat_summary"].items():
                act_cs = actual_summary.get(cat, {})
                # benchmark_cost
                checks += 1
                try:
                    if abs(float(act_cs.get("benchmark_cost", 0)) - exp_cs["benchmark_cost"]) <= max(1.0, abs(exp_cs["benchmark_cost"]) * 0.005):
                        correct += 1
                except (ValueError, TypeError):
                    pass
                # num_eligible_vendors
                checks += 1
                try:
                    if int(act_cs.get("num_eligible_vendors", -1)) == exp_cs["num_eligible_vendors"]:
                        correct += 1
                except (ValueError, TypeError):
                    pass
                # recommended_vendor_id
                checks += 1
                try:
                    if int(act_cs.get("recommended_vendor_id", -1)) == exp_cs["recommended_vendor_id"]:
                        correct += 1
                except (ValueError, TypeError):
                    pass
                # within_budget
                checks += 1
                wb = act_cs.get("within_budget")
                if isinstance(wb, bool):
                    if wb == exp_cs["within_budget"]:
                        correct += 1
                elif isinstance(wb, str):
                    if wb.lower() == str(exp_cs["within_budget"]).lower():
                        correct += 1
            pct = correct / checks if checks else 0
            score = round(20 * pct)
            criteria["category_summary_values"] = {
                "passed": pct >= 0.95,
                "score": score,
                "max_score": 20,
                "reason": f"{correct}/{checks} checks passed." if pct < 1.0 else None,
            }
        else:
            criteria["category_summary_values"] = {
                "passed": False,
                "score": 0,
                "max_score": 20,
                "reason": "Cannot evaluate summary values without valid structure.",
            }

        # ---- 6. Response: total estimated procurement cost (15 pts) ----
        action_lower = action.lower() if action else ""
        cost_match = re.search(
            r"total\s+estimated\s+procurement\s+cost[:\s]*\$?([\d,]+(?:\.\d+)?)",
            action_lower,
        )
        if cost_match:
            try:
                reported_cost = float(cost_match.group(1).replace(",", ""))
                tol = max(1.0, abs(expected["total_cost"]) * 0.005)
                passed = abs(reported_cost - expected["total_cost"]) <= tol
                criteria["response_total_cost"] = {
                    "passed": passed,
                    "score": 15 if passed else 0,
                    "max_score": 15,
                    "reason": None if passed else f"Expected ~{expected['total_cost']}, got {reported_cost}.",
                }
            except ValueError:
                criteria["response_total_cost"] = {
                    "passed": False,
                    "score": 0,
                    "max_score": 15,
                    "reason": "Could not parse cost value.",
                }
        else:
            criteria["response_total_cost"] = {
                "passed": False,
                "score": 0,
                "max_score": 15,
                "reason": "Pattern 'Total estimated procurement cost: $X' not found in response.",
            }

        # ---- 7. Response: overall risk rating (10 pts) ----
        rating_match = re.search(
            r"overall\s+risk\s+rating[:\s]*(LOW|MEDIUM|HIGH)",
            action,
            re.IGNORECASE,
        )
        if rating_match:
            reported_rating = rating_match.group(1).upper()
            passed = reported_rating == expected["overall_rating"]
            criteria["response_risk_rating"] = {
                "passed": passed,
                "score": 10 if passed else 0,
                "max_score": 10,
                "reason": None if passed else f"Expected {expected['overall_rating']}, got {reported_rating}.",
            }
        else:
            criteria["response_risk_rating"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "Pattern 'Overall risk rating: LEVEL' not found in response.",
            }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = total_score / max_score if max_score else 0.0

        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ================================================================== #
    # verify                                                              #
    # ================================================================== #

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import statistics

        # --- Read workspace config ---
        with open(os.path.join(self.workspace, "scoring_weights.yaml")) as f:
            weights = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "eligibility_criteria.json")) as f:
            eligibility = json.load(f)
        with open(os.path.join(self.workspace, "market_forecast.json")) as f:
            forecast = json.load(f)

        # --- Read workspace vendor data ---
        operational_risk = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "vendor_dossier_*.md"))):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(
                r"## Vendor (\d+):.*?\n.*?Operational Risk Rating:\s*([\d.]+)",
                content,
                re.DOTALL,
            ):
                operational_risk[int(m.group(1))] = float(m.group(2))

        delivery_scores = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "performance_data_*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    delivery_scores[int(row["vendor_id"])] = float(row["past_delivery_score"])

        # --- Gather all vendors via tool ---
        all_vendors = []
        page = 1
        while True:
            result = json.loads(self.tools["list_vendors"](page=page, page_size=15))
            all_vendors.extend(result["vendors"])
            if page >= result["total_pages"]:
                break
            page += 1

        ref_year = eligibility["reference_fiscal_year"]
        proc_year = eligibility["procurement_year"]

        # --- Gather financials via tool ---
        all_financials = {}
        page = 1
        while True:
            result = json.loads(self.tools["query_vendor_financials"](fiscal_year=ref_year, page=page, page_size=15)["content"][0]["text"])
            for rec in result["records"]:
                all_financials[rec["vendor_id"]] = rec
            if page >= result["total_pages"]:
                break
            page += 1

        # --- Filter eligible vendors ---
        eligible = {}
        for v in all_vendors:
            vid = v["vendor_id"]
            if eligibility.get("must_be_active") and not v["active"]:
                continue
            fin = all_financials.get(vid)
            if not fin:
                continue
            if fin["credit_score"] < eligibility["min_credit_score"]:
                continue
            if fin["current_ratio"] < eligibility["min_current_ratio"]:
                continue
            dta = fin["total_debt"] / fin["total_assets"] if fin["total_assets"] else 1.0
            if dta > eligibility["max_debt_to_asset_ratio"]:
                continue
            years_active = proc_year - v["incorporation_year"]
            if years_active < eligibility["min_years_active"]:
                continue
            eligible[vid] = {**v, "financials": fin, "debt_to_asset": dta}

        # --- Risk scores ---
        rsw = weights["risk_score_weights"]
        fhw = weights["financial_health_sub_weights"]
        norm = weights["normalization"]

        risk_scores = {}
        for vid, info in eligible.items():
            fin = info["financials"]
            cs_norm = (fin["credit_score"] - norm["credit_score_min"]) / norm["credit_score_range"]
            cr_norm = min(fin["current_ratio"] / norm["current_ratio_cap"], 1.0)
            lev = 1.0 - info["debt_to_asset"]
            fh = (
                fhw["credit_score_normalized"] * cs_norm
                + fhw["current_ratio_normalized"] * cr_norm
                + fhw["leverage_score"] * lev
            )
            opr = operational_risk.get(vid, 3.0)
            opr_score = (5.0 - opr) / 4.0
            ds = delivery_scores.get(vid, 70.0) / 100.0
            composite = (
                rsw["financial_health"] * fh
                + rsw["operational_risk"] * opr_score
                + rsw["delivery_track_record"] * ds
            )
            risk_scores[vid] = round(composite, 4)

        # --- Gather bids per category via tool ---
        categories = sorted(set(
            forecast["category_adjustments"].keys()
        ))

        from collections import defaultdict
        bid_sums = defaultdict(lambda: [0.0, 0])

        for cat in categories:
            page = 1
            while True:
                result = json.loads(self.tools["search_historical_bids"](category=cat, page=page, page_size=20))
                for b in result["bids"]:
                    key = (b["vendor_id"], b["category"])
                    bid_sums[key][0] += b["bid_amount"]
                    bid_sums[key][1] += 1
                if page >= result["total_pages"]:
                    break
                page += 1

        avg_bids = {k: v[0] / v[1] for k, v in bid_sums.items()}

        # --- Price adjustment factors via tool ---
        pa = weights["price_adjustment"]
        price_adj_factors = {}
        for cat in categories:
            ref_idx = json.loads(self.tools["get_material_price_index"](
                category=cat, year=pa["reference_year"], quarter=pa["reference_quarter"]
            )["content"][0]["text"])
            base_idx = json.loads(self.tools["get_material_price_index"](
                category=cat, year=pa["base_year"], quarter=pa["base_quarter"]
            )["content"][0]["text"])
            ref_val = ref_idx.get("index_value", 100.0)
            base_val = base_idx.get("index_value", 100.0)
            fa = forecast["category_adjustments"].get(cat, {}).get(
                "forecast_adjustment_factor", 1.0
            )
            price_adj_factors[cat] = (ref_val / base_val) * fa

        # --- Budget allocations via tool ---
        budgets = {}
        for cat in categories:
            result = json.loads(self.tools["get_budget_allocation"](category=cat, fiscal_year=proc_year))
            budgets[cat] = result.get("allocated_budget", 0.0)

        # --- Build benchmark report ---
        rp_cfg = weights["risk_premium"]
        report_rows = []
        for (vid, cat), avg_bid in avg_bids.items():
            if vid not in eligible:
                continue
            paf = price_adj_factors.get(cat, 1.0)
            pab = avg_bid * paf
            rs = risk_scores[vid]
            rp = rp_cfg["base"] + rp_cfg["scale_factor"] * (1 - rs)
            rac = pab * (1 + rp)
            report_rows.append({
                "category": cat,
                "vendor_id": vid,
                "vendor_name": eligible[vid]["vendor_name"],
                "historical_avg_bid": round(avg_bid, 2),
                "price_adjustment_factor": round(paf, 4),
                "price_adjusted_bid": round(pab, 2),
                "risk_score": round(rs, 4),
                "risk_premium": round(rp, 4),
                "risk_adjusted_cost": round(rac, 2),
            })

        report_rows.sort(key=lambda r: (r["category"], r["risk_adjusted_cost"]))

        # Write benchmark_report.csv
        report_path = os.path.join(self.workspace, "benchmark_report.csv")
        fieldnames = [
            "category", "vendor_id", "vendor_name",
            "historical_avg_bid", "price_adjustment_factor",
            "price_adjusted_bid", "risk_score", "risk_premium",
            "risk_adjusted_cost",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)

        # --- Category summary ---
        cat_summary = {}
        for cat in sorted(set(r["category"] for r in report_rows)):
            cat_rows = [r for r in report_rows if r["category"] == cat]
            costs = sorted(r["risk_adjusted_cost"] for r in cat_rows)
            n = len(costs)
            if n % 2 == 1:
                median_cost = costs[n // 2]
            else:
                median_cost = (costs[n // 2 - 1] + costs[n // 2]) / 2
            median_cost = round(median_cost, 2)
            best = cat_rows[0]
            budget_alloc = budgets.get(cat, 0.0)
            cat_summary[cat] = {
                "benchmark_cost": median_cost,
                "min_cost": round(costs[0], 2),
                "max_cost": round(costs[-1], 2),
                "num_eligible_vendors": len(cat_rows),
                "recommended_vendor_id": best["vendor_id"],
                "recommended_vendor_name": best["vendor_name"],
                "budget_allocation": round(budget_alloc, 2),
                "within_budget": median_cost <= budget_alloc,
            }

        summary_path = os.path.join(self.workspace, "category_summary.json")
        with open(summary_path, "w") as f:
            json.dump(cat_summary, f, indent=2)

        # --- Construct response ---
        total_cost = round(sum(cs["benchmark_cost"] for cs in cat_summary.values()), 2)
        all_rs = list(risk_scores.values())
        avg_rs = sum(all_rs) / len(all_rs) if all_rs else 0.0
        if avg_rs >= 0.7:
            rating = "LOW"
        elif avg_rs >= 0.4:
            rating = "MEDIUM"
        else:
            rating = "HIGH"
        cats_within = sum(1 for cs in cat_summary.values() if cs["within_budget"])

        action = (
            f"Risk-adjusted cost benchmark analysis complete.\n\n"
            f"Total estimated procurement cost: ${total_cost:,.2f}\n"
            f"Overall risk rating: {rating}\n"
            f"{cats_within} out of {len(cat_summary)} categories are within budget.\n"
        )

        return self.step(action)
