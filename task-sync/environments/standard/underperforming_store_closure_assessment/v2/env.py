from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import math
import re
import yaml


def tool(description: str, parameters: dict):
    """Decorator that attaches tool metadata to a method."""

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

    # ==================================================================
    # Tool methods
    # ==================================================================

    @tool(
        description=(
            "Lists stores with basic information, paginated. "
            "Returns store_id, store_name, region, city, and store_type "
            "for each store on the requested page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed. Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": (
                        "Number of stores per page, maximum 20. Defaults to 20."
                    ),
                },
            },
            "required": [],
        },
    )
    def list_stores(self, page: int = 1, page_size: int = 20) -> dict:
        page_size = min(int(page_size), 20)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM stores")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT store_id, store_name, region, city, store_type "
            "FROM stores ORDER BY store_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "total_stores": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size),
            "stores": [
                {
                    "store_id": r[0],
                    "store_name": r[1],
                    "region": r[2],
                    "city": r[3],
                    "store_type": r[4],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Returns detailed information for a single store, including "
            "square footage, employee count, and opening date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "string",
                    "description": "The store identifier, e.g. 'S0001'.",
                }
            },
            "required": ["store_id"],
        },
    )
    def get_store_details(self, store_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM stores WHERE store_id = ?", (store_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Store {store_id} not found"}
        cols = [
            "store_id",
            "store_name",
            "region",
            "city",
            "address",
            "store_type",
            "square_footage",
            "employee_count",
            "open_date",
        ]
        return dict(zip(cols, row))

    @tool(
        description=(
            "Returns monthly revenue data for a store over the last N months "
            "(up to 24). Each record includes year, month, gross_revenue, "
            "net_revenue, transaction_count, and avg_ticket."
        ),
        parameters={
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "string",
                    "description": "The store identifier.",
                },
                "months": {
                    "type": "integer",
                    "description": (
                        "Number of recent months to retrieve, maximum 24. "
                        "Defaults to 24."
                    ),
                },
            },
            "required": ["store_id"],
        },
    )
    def get_revenue_data(self, store_id: str, months: int = 24) -> dict:
        months = min(int(months), 24)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT year, month, gross_revenue, net_revenue, "
            "transaction_count, avg_ticket "
            "FROM monthly_revenue WHERE store_id = ? "
            "ORDER BY year DESC, month DESC LIMIT ?",
            (store_id, months),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "store_id": store_id,
            "months_returned": len(rows),
            "data": [
                {
                    "year": r[0],
                    "month": r[1],
                    "gross_revenue": r[2],
                    "net_revenue": r[3],
                    "transaction_count": r[4],
                    "avg_ticket": r[5],
                }
                for r in reversed(rows)
            ],
        }

    @tool(
        description=(
            "Returns competitor information for a specific store. Each "
            "competitor record includes name, distance in km, category, "
            "operational status (active/closed), and observation dates."
        ),
        parameters={
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "string",
                    "description": "The store identifier.",
                }
            },
            "required": ["store_id"],
        },
    )
    def get_competitor_data(self, store_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT competitor_id, competitor_name, distance_km, category, "
            "status, first_seen, last_seen "
            "FROM competitors WHERE store_id = ? ORDER BY distance_km",
            (store_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "store_id": store_id,
            "total_competitors": len(rows),
            "competitors": [
                {
                    "competitor_id": r[0],
                    "name": r[1],
                    "distance_km": r[2],
                    "category": r[3],
                    "status": r[4],
                    "first_seen": r[5],
                    "last_seen": r[6],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Returns lease contract details for a store, including current "
            "monthly rent, lease start/end dates, proposed renewal rent, "
            "renewal term, and landlord name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "store_id": {
                    "type": "string",
                    "description": "The store identifier.",
                }
            },
            "required": ["store_id"],
        },
    )
    def get_lease_info(self, store_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT lease_id, monthly_rent, lease_start, lease_end, "
            "proposed_renewal_rent, renewal_term_years, landlord "
            "FROM lease_contracts WHERE store_id = ?",
            (store_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"No lease found for store {store_id}"}
        return {
            "store_id": store_id,
            "lease_id": row[0],
            "monthly_rent": row[1],
            "lease_start": row[2],
            "lease_end": row[3],
            "proposed_renewal_rent": row[4],
            "renewal_term_years": row[5],
            "landlord": row[6],
        }

    @tool(
        description=(
            "Returns marketing spend and attributed revenue data for a "
            "region. Provides total spend, total attributed revenue, ROI, "
            "and per-record breakdown by year, month, and channel."
        ),
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": (
                        "Region name: Northeast, Southeast, Midwest, "
                        "Southwest, or West."
                    ),
                },
                "year": {
                    "type": "integer",
                    "description": (
                        "Optional year filter. If omitted, returns all years."
                    ),
                },
            },
            "required": ["region"],
        },
    )
    def get_regional_marketing(self, region: str, year: int = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if year is not None:
            cur.execute(
                "SELECT year, month, channel, spend_amount, attributed_revenue "
                "FROM marketing_spend WHERE region = ? AND year = ? "
                "ORDER BY year, month, channel",
                (region, int(year)),
            )
        else:
            cur.execute(
                "SELECT year, month, channel, spend_amount, attributed_revenue "
                "FROM marketing_spend WHERE region = ? "
                "ORDER BY year, month, channel",
                (region,),
            )
        rows = cur.fetchall()
        conn.close()

        total_spend = sum(r[3] for r in rows)
        total_attr = sum(r[4] for r in rows)
        roi = total_attr / total_spend if total_spend > 0 else 0.0

        return {
            "region": region,
            "year_filter": year,
            "total_spend": round(total_spend, 2),
            "total_attributed_revenue": round(total_attr, 2),
            "roi": round(roi, 4),
            "record_count": len(rows),
            "data": [
                {
                    "year": r[0],
                    "month": r[1],
                    "channel": r[2],
                    "spend": r[3],
                    "attributed_revenue": r[4],
                }
                for r in rows
            ],
        }

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _load_workspace_store_data(self) -> dict:
        """Load per-store operational costs & flexibility from workspace CSVs."""
        ws_data = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("store_data_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        ws_data[row["store_id"]] = {
                            "monthly_utilities": float(row["monthly_utilities"]),
                            "monthly_maintenance": float(
                                row["monthly_maintenance"]
                            ),
                            "monthly_insurance": float(row["monthly_insurance"]),
                            "monthly_supplies": float(row["monthly_supplies"]),
                            "monthly_misc": float(row["monthly_misc"]),
                            "landlord_flexibility_score": int(
                                row["landlord_flexibility_score"]
                            ),
                        }
        return ws_data

    def _load_policy(self) -> dict:
        policy_path = os.path.join(
            self.workspace, "closure_scoring_policy.yaml"
        )
        with open(policy_path) as f:
            return yaml.safe_load(f)

    def _compute_ground_truth(self) -> list:
        """Compute ground-truth closure recommendations from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        policy = self._load_policy()
        weights = policy["scoring_weights"]
        threshold = policy["closure_threshold"]

        rt_map = policy["revenue_trend_config"]["decline_score_mapping"]
        cp_cfg = policy["competitor_pressure_config"]
        cp_scr = cp_cfg["scoring"]
        lc_cfg = policy["lease_cost_config"]
        lc_thr = lc_cfg["increase_thresholds"]
        lc_bs = lc_cfg["base_scores"]
        flex_adj = lc_cfg["flexibility_adjustment"]
        me_cfg = policy["marketing_efficiency_config"]
        me_year = me_cfg["evaluation_year"]
        me_rt = me_cfg["roi_thresholds"]
        me_sc = me_cfg["scores"]

        ws_data = self._load_workspace_store_data()

        # Marketing ROI per region
        region_roi = {}
        cur.execute(
            "SELECT region, SUM(spend_amount), SUM(attributed_revenue) "
            "FROM marketing_spend WHERE year = ? GROUP BY region",
            (me_year,),
        )
        for row in cur.fetchall():
            spend, attr = row[1] or 0, row[2] or 0
            region_roi[row[0]] = attr / spend if spend > 0 else 0.0

        # All stores
        cur.execute(
            "SELECT store_id, store_name, region FROM stores ORDER BY store_id"
        )
        all_stores = cur.fetchall()

        results = []
        for store_id, store_name, region in all_stores:
            # ---- Revenue trend ----
            cur.execute(
                "SELECT year, net_revenue FROM monthly_revenue "
                "WHERE store_id = ?",
                (store_id,),
            )
            revs = cur.fetchall()
            prev_12 = sum(r[1] for r in revs if r[0] == 2023)
            last_12 = sum(r[1] for r in revs if r[0] == 2024)
            trend_pct = (
                ((last_12 - prev_12) / prev_12 * 100) if prev_12 != 0 else 0.0
            )
            if trend_pct <= rt_map["severe_decline_threshold_pct"]:
                rev_score = float(rt_map["severe_score"])
            elif trend_pct <= rt_map["moderate_decline_threshold_pct"]:
                rev_score = float(rt_map["moderate_score"])
            elif trend_pct <= 0:
                rev_score = float(rt_map["mild_score"])
            else:
                rev_score = float(rt_map["stable_or_growing_score"])

            # ---- Competitor pressure ----
            radius = cp_cfg["density_radius_km"]
            window_start = cp_cfg["new_competitor_window_start"]
            cur.execute(
                "SELECT first_seen, distance_km, status "
                "FROM competitors WHERE store_id = ?",
                (store_id,),
            )
            comps = cur.fetchall()
            new_count = sum(
                1
                for c in comps
                if c[0] >= window_start
                and c[1] <= radius
                and c[2] == "active"
            )
            if new_count >= cp_scr["high_pressure_min_new"]:
                comp_score = float(cp_scr["high_pressure_score"])
            elif new_count >= cp_scr["medium_pressure_min_new"]:
                comp_score = float(cp_scr["medium_pressure_score"])
            else:
                comp_score = float(cp_scr["low_pressure_score"])

            # ---- Lease cost ----
            cur.execute(
                "SELECT monthly_rent, proposed_renewal_rent "
                "FROM lease_contracts WHERE store_id = ?",
                (store_id,),
            )
            lr = cur.fetchone()
            current_rent, proposed_rent = lr[0], lr[1]
            inc_pct = (
                (proposed_rent - current_rent) / current_rent
                if current_rent > 0
                else 0.0
            )
            if inc_pct >= lc_thr["high_increase_pct"]:
                base_lease = float(lc_bs["high_increase_score"])
            elif inc_pct >= lc_thr["moderate_increase_pct"]:
                base_lease = float(lc_bs["moderate_increase_score"])
            elif inc_pct >= 0:
                base_lease = float(lc_bs["low_increase_score"])
            else:
                base_lease = float(lc_bs["decrease_score"])

            flex = ws_data.get(store_id, {}).get(
                "landlord_flexibility_score", 0
            )
            if flex >= flex_adj["high_flexibility_min"]:
                lease_score = base_lease * (
                    1 - flex_adj["high_flexibility_discount"]
                )
            elif flex >= flex_adj["medium_flexibility_min"]:
                lease_score = base_lease * (
                    1 - flex_adj["medium_flexibility_discount"]
                )
            else:
                lease_score = base_lease

            # ---- Marketing efficiency ----
            roi = region_roi.get(region, 0.0)
            if roi <= me_rt["low_roi_max"]:
                mkt_score = float(me_sc["low_roi_score"])
            elif roi <= me_rt["medium_roi_max"]:
                mkt_score = float(me_sc["medium_roi_score"])
            else:
                mkt_score = float(me_sc["high_roi_score"])

            # ---- Composite ----
            composite = (
                weights["revenue_trend"] * rev_score
                + weights["competitor_pressure"] * comp_score
                + weights["lease_cost_impact"] * lease_score
                + weights["marketing_efficiency"] * mkt_score
            )
            composite = round(composite, 2)

            # ---- Savings ----
            ws_s = ws_data.get(store_id, {})
            monthly_ops = (
                ws_s.get("monthly_utilities", 0)
                + ws_s.get("monthly_maintenance", 0)
                + ws_s.get("monthly_insurance", 0)
                + ws_s.get("monthly_supplies", 0)
                + ws_s.get("monthly_misc", 0)
            )
            annual_ops = monthly_ops * 12
            annual_rent = proposed_rent * 12
            projected_net = last_12 * (1 + trend_pct / 100)
            savings = round(annual_rent + annual_ops - projected_net)

            results.append(
                {
                    "store_id": store_id,
                    "store_name": store_name,
                    "region": region,
                    "composite_score": composite,
                    "revenue_trend_score": round(rev_score, 2),
                    "competitor_pressure_score": round(comp_score, 2),
                    "lease_cost_score": round(lease_score, 2),
                    "marketing_efficiency_score": round(mkt_score, 2),
                    "estimated_annual_savings": savings,
                }
            )

        conn.close()

        candidates = [r for r in results if r["composite_score"] >= threshold]
        candidates.sort(key=lambda x: (-x["composite_score"], x["store_id"]))
        for rank, c in enumerate(candidates, 1):
            c["closure_priority_rank"] = rank

        return candidates

    # ==================================================================
    # Evaluation
    # ==================================================================

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
        ground_truth = self._compute_ground_truth()
        gt_ids = {c["store_id"] for c in ground_truth}
        gt_by_id = {c["store_id"]: c for c in ground_truth}

        total_score = 0
        max_score = 100
        criteria = {}

        # ---- Criterion 1: File format (10 pts) ----
        csv_path = os.path.join(self.workspace, "closure_recommendations.csv")
        file_ok = False
        agent_rows = []
        agent_data = {}
        expected_cols = {
            "store_id",
            "store_name",
            "region",
            "closure_priority_rank",
            "composite_score",
            "revenue_trend_score",
            "competitor_pressure_score",
            "lease_cost_score",
            "marketing_efficiency_score",
            "estimated_annual_savings",
        }
        if os.path.exists(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    if expected_cols.issubset(set(reader.fieldnames or [])):
                        agent_rows = list(reader)
                        agent_data = {r["store_id"]: r for r in agent_rows}
                        file_ok = True
            except Exception:
                pass

        if file_ok:
            criteria["file_format"] = {
                "passed": True,
                "score": 10,
                "max_score": 10,
            }
            total_score += 10
        else:
            criteria["file_format"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "File missing, unreadable, or missing required columns",
            }

        # ---- Criterion 2: Correct closure candidates (25 pts) ----
        agent_ids = set(agent_data.keys())
        if agent_ids == gt_ids and len(agent_ids) > 0:
            criteria["correct_candidates"] = {
                "passed": True,
                "score": 25,
                "max_score": 25,
            }
            total_score += 25
        else:
            if len(gt_ids) > 0:
                correct = len(agent_ids & gt_ids)
                extra = len(agent_ids - gt_ids)
                partial = max(0, (correct - extra)) / len(gt_ids)
                pts = round(25 * partial)
            else:
                pts = 25 if len(agent_ids) == 0 else 0
            criteria["correct_candidates"] = {
                "passed": False,
                "score": pts,
                "max_score": 25,
                "reason": (
                    f"Expected {len(gt_ids)} candidates, got {len(agent_ids)}. "
                    f"Correct={len(agent_ids & gt_ids)}, "
                    f"Missing={len(gt_ids - agent_ids)}, "
                    f"Extra={len(agent_ids - gt_ids)}"
                ),
            }
            total_score += pts

        # ---- Criterion 3: Correct ranking order (15 pts) ----
        if file_ok and len(agent_data) > 0:
            try:
                agent_ranked = sorted(
                    agent_rows,
                    key=lambda x: int(x.get("closure_priority_rank", 9999)),
                )
            except (ValueError, TypeError):
                agent_ranked = agent_rows
            agent_order = [r["store_id"] for r in agent_ranked]
            gt_order = [c["store_id"] for c in ground_truth]

            if agent_order == gt_order:
                criteria["ranking_order"] = {
                    "passed": True,
                    "score": 15,
                    "max_score": 15,
                }
                total_score += 15
            else:
                common = [s for s in agent_order if s in gt_ids]
                gt_common = [s for s in gt_order if s in set(common)]
                if len(gt_common) > 1:
                    concordant = 0
                    total_pairs = 0
                    pos = {s: i for i, s in enumerate(common)}
                    for i in range(len(gt_common)):
                        for j in range(i + 1, len(gt_common)):
                            total_pairs += 1
                            if pos.get(gt_common[i], -1) < pos.get(
                                gt_common[j], -1
                            ):
                                concordant += 1
                    ratio = concordant / total_pairs if total_pairs > 0 else 0
                    pts = round(15 * ratio)
                else:
                    pts = 0
                criteria["ranking_order"] = {
                    "passed": False,
                    "score": pts,
                    "max_score": 15,
                    "reason": "Ranking order does not match ground truth",
                }
                total_score += pts
        else:
            criteria["ranking_order"] = {
                "passed": False,
                "score": 0,
                "max_score": 15,
                "reason": "No valid data to evaluate ranking",
            }

        # ---- Criterion 4: Individual scores accuracy (20 pts) ----
        if file_ok and len(agent_data) > 0:
            score_fields = [
                "revenue_trend_score",
                "competitor_pressure_score",
                "lease_cost_score",
                "marketing_efficiency_score",
                "composite_score",
            ]
            correct_count = 0
            check_count = 0
            for sid in agent_ids & gt_ids:
                for field in score_fields:
                    check_count += 1
                    try:
                        a_val = float(agent_data[sid][field])
                        g_val = gt_by_id[sid][field]
                        if abs(a_val - g_val) <= 0.1:
                            correct_count += 1
                    except (ValueError, KeyError):
                        pass
            ratio = correct_count / check_count if check_count > 0 else 0
            pts = round(20 * ratio)
            criteria["individual_scores"] = {
                "passed": ratio >= 0.95,
                "score": min(pts, 20),
                "max_score": 20,
            }
            if not criteria["individual_scores"]["passed"]:
                criteria["individual_scores"]["reason"] = (
                    f"{correct_count}/{check_count} score values within tolerance"
                )
            total_score += min(pts, 20)
        else:
            criteria["individual_scores"] = {
                "passed": False,
                "score": 0,
                "max_score": 20,
                "reason": "No valid data to evaluate scores",
            }

        # ---- Criterion 5: Savings estimates (15 pts) ----
        if file_ok and len(agent_data) > 0:
            sav_correct = 0
            sav_total = 0
            for sid in agent_ids & gt_ids:
                sav_total += 1
                try:
                    a_sav = float(agent_data[sid]["estimated_annual_savings"])
                    g_sav = gt_by_id[sid]["estimated_annual_savings"]
                    if abs(g_sav) > 0:
                        if (
                            abs(a_sav - g_sav) / abs(g_sav) <= 0.05
                            or abs(a_sav - g_sav) <= 1000
                        ):
                            sav_correct += 1
                    elif abs(a_sav - g_sav) <= 1000:
                        sav_correct += 1
                except (ValueError, KeyError):
                    pass
            ratio = sav_correct / sav_total if sav_total > 0 else 0
            pts = round(15 * ratio)
            criteria["savings_estimates"] = {
                "passed": ratio >= 0.90,
                "score": min(pts, 15),
                "max_score": 15,
            }
            if not criteria["savings_estimates"]["passed"]:
                criteria["savings_estimates"]["reason"] = (
                    f"{sav_correct}/{sav_total} savings within tolerance"
                )
            total_score += min(pts, 15)
        else:
            criteria["savings_estimates"] = {
                "passed": False,
                "score": 0,
                "max_score": 15,
                "reason": "No valid data to evaluate savings",
            }

        # ---- Criterion 6: Response summary (15 pts) ----
        c6_pts = 0
        c6_reasons = []
        total_gt_savings = sum(
            c["estimated_annual_savings"] for c in ground_truth
        )
        num_gt = len(ground_truth)

        if re.search(r"\b" + str(num_gt) + r"\b", action):
            c6_pts += 8
        else:
            c6_reasons.append(
                f"Expected number of closure candidates ({num_gt}) not found"
            )

        amounts = re.findall(r"(-?\$?-?[\d,]+(?:\.\d+)?)", action)
        savings_found = False
        for amt_str in amounts:
            try:
                cleaned = amt_str.replace(",", "").replace("$", "")
                amt = float(cleaned)
                if abs(total_gt_savings) > 0:
                    if (
                        abs(amt - total_gt_savings) / abs(total_gt_savings)
                        <= 0.05
                    ):
                        savings_found = True
                        break
                elif abs(amt - total_gt_savings) <= 1000:
                    savings_found = True
                    break
            except ValueError:
                pass
        if savings_found:
            c6_pts += 7
        else:
            c6_reasons.append(
                f"Expected aggregate savings (~${total_gt_savings:,.0f}) not found"
            )

        criteria["response_summary"] = {
            "passed": c6_pts == 15,
            "score": c6_pts,
            "max_score": 15,
        }
        if c6_reasons:
            criteria["response_summary"]["reason"] = "; ".join(c6_reasons)
        total_score += c6_pts

        reward = total_score / max_score
        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ==================================================================
    # Verification
    # ==================================================================

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

        # ---- 1. Read workspace configuration ----
        policy = self._load_policy()
        weights = policy["scoring_weights"]
        threshold = policy["closure_threshold"]

        rt_map = policy["revenue_trend_config"]["decline_score_mapping"]
        cp_cfg = policy["competitor_pressure_config"]
        cp_scr = cp_cfg["scoring"]
        lc_cfg = policy["lease_cost_config"]
        lc_thr = lc_cfg["increase_thresholds"]
        lc_bs = lc_cfg["base_scores"]
        flex_adj = lc_cfg["flexibility_adjustment"]
        me_cfg = policy["marketing_efficiency_config"]
        me_year = me_cfg["evaluation_year"]
        me_rt = me_cfg["roi_thresholds"]
        me_sc = me_cfg["scores"]

        # Read per-store operational costs and flexibility from workspace CSVs
        ws_data = self._load_workspace_store_data()

        # ---- 2. List all stores via tools ----
        all_stores = []
        page = 1
        while True:
            result = self.tools["list_stores"](page=page, page_size=20)
            all_stores.extend(result["stores"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ---- 3. Get marketing ROI per region ----
        regions_seen = list({s["region"] for s in all_stores})
        region_roi = {}
        for region in regions_seen:
            mkt = self.tools["get_regional_marketing"](
                region=region, year=me_year
            )
            region_roi[region] = mkt["roi"]

        # ---- 4. Score every store ----
        store_scores = []
        for store in all_stores:
            sid = store["store_id"]
            region = store["region"]

            # Revenue trend
            rev = self.tools["get_revenue_data"](store_id=sid, months=24)
            prev_12 = sum(
                d["net_revenue"] for d in rev["data"] if d["year"] == 2023
            )
            last_12 = sum(
                d["net_revenue"] for d in rev["data"] if d["year"] == 2024
            )
            trend_pct = (
                ((last_12 - prev_12) / prev_12 * 100) if prev_12 != 0 else 0.0
            )
            if trend_pct <= rt_map["severe_decline_threshold_pct"]:
                rev_score = float(rt_map["severe_score"])
            elif trend_pct <= rt_map["moderate_decline_threshold_pct"]:
                rev_score = float(rt_map["moderate_score"])
            elif trend_pct <= 0:
                rev_score = float(rt_map["mild_score"])
            else:
                rev_score = float(rt_map["stable_or_growing_score"])

            # Competitor pressure
            comps = self.tools["get_competitor_data"](store_id=sid)
            radius = cp_cfg["density_radius_km"]
            window_start = cp_cfg["new_competitor_window_start"]
            new_count = sum(
                1
                for c in comps["competitors"]
                if c["first_seen"] >= window_start
                and c["distance_km"] <= radius
                and c["status"] == "active"
            )
            if new_count >= cp_scr["high_pressure_min_new"]:
                comp_score = float(cp_scr["high_pressure_score"])
            elif new_count >= cp_scr["medium_pressure_min_new"]:
                comp_score = float(cp_scr["medium_pressure_score"])
            else:
                comp_score = float(cp_scr["low_pressure_score"])

            # Lease cost
            lease = self.tools["get_lease_info"](store_id=sid)
            current_rent = lease["monthly_rent"]
            proposed_rent = lease["proposed_renewal_rent"]
            inc_pct = (
                (proposed_rent - current_rent) / current_rent
                if current_rent > 0
                else 0.0
            )
            if inc_pct >= lc_thr["high_increase_pct"]:
                base_lease = float(lc_bs["high_increase_score"])
            elif inc_pct >= lc_thr["moderate_increase_pct"]:
                base_lease = float(lc_bs["moderate_increase_score"])
            elif inc_pct >= 0:
                base_lease = float(lc_bs["low_increase_score"])
            else:
                base_lease = float(lc_bs["decrease_score"])

            flex = ws_data.get(sid, {}).get("landlord_flexibility_score", 0)
            if flex >= flex_adj["high_flexibility_min"]:
                lease_score = base_lease * (
                    1 - flex_adj["high_flexibility_discount"]
                )
            elif flex >= flex_adj["medium_flexibility_min"]:
                lease_score = base_lease * (
                    1 - flex_adj["medium_flexibility_discount"]
                )
            else:
                lease_score = base_lease

            # Marketing efficiency
            roi = region_roi.get(region, 0.0)
            if roi <= me_rt["low_roi_max"]:
                mkt_score = float(me_sc["low_roi_score"])
            elif roi <= me_rt["medium_roi_max"]:
                mkt_score = float(me_sc["medium_roi_score"])
            else:
                mkt_score = float(me_sc["high_roi_score"])

            # Composite
            composite = (
                weights["revenue_trend"] * rev_score
                + weights["competitor_pressure"] * comp_score
                + weights["lease_cost_impact"] * lease_score
                + weights["marketing_efficiency"] * mkt_score
            )
            composite = round(composite, 2)

            # Savings
            ws_s = ws_data.get(sid, {})
            monthly_ops = (
                ws_s.get("monthly_utilities", 0)
                + ws_s.get("monthly_maintenance", 0)
                + ws_s.get("monthly_insurance", 0)
                + ws_s.get("monthly_supplies", 0)
                + ws_s.get("monthly_misc", 0)
            )
            annual_ops = monthly_ops * 12
            annual_rent = proposed_rent * 12
            projected_net = last_12 * (1 + trend_pct / 100)
            savings = round(annual_rent + annual_ops - projected_net)

            store_scores.append(
                {
                    "store_id": sid,
                    "store_name": store["store_name"],
                    "region": region,
                    "composite_score": composite,
                    "revenue_trend_score": round(rev_score, 2),
                    "competitor_pressure_score": round(comp_score, 2),
                    "lease_cost_score": round(lease_score, 2),
                    "marketing_efficiency_score": round(mkt_score, 2),
                    "estimated_annual_savings": savings,
                }
            )

        # ---- 5. Determine closure candidates ----
        candidates = [
            s for s in store_scores if s["composite_score"] >= threshold
        ]
        candidates.sort(key=lambda x: (-x["composite_score"], x["store_id"]))
        for rank, c in enumerate(candidates, 1):
            c["closure_priority_rank"] = rank

        # ---- 6. Write output CSV ----
        output_path = os.path.join(
            self.workspace, "closure_recommendations.csv"
        )
        fieldnames = [
            "store_id",
            "store_name",
            "region",
            "closure_priority_rank",
            "composite_score",
            "revenue_trend_score",
            "competitor_pressure_score",
            "lease_cost_score",
            "marketing_efficiency_score",
            "estimated_annual_savings",
        ]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for c in candidates:
                writer.writerow({k: c[k] for k in fieldnames})

        # ---- 7. Build action string ----
        total_savings = sum(c["estimated_annual_savings"] for c in candidates)
        if total_savings >= 0:
            savings_str = f"${total_savings:,}"
        else:
            savings_str = f"-${abs(total_savings):,}"
        action = (
            f"Based on the comprehensive store closure analysis, "
            f"{len(candidates)} stores are recommended for closure. "
            f"The aggregate estimated annual savings across all "
            f"recommended closures is {savings_str}. "
            f"The closure recommendations have been saved to "
            f"closure_recommendations.csv with full scoring details."
        )

        return self.step(action)
