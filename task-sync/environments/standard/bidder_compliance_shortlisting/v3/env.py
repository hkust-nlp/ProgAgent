#!/usr/bin/env python3
"""Environment for municipal infrastructure tender vendor evaluation task."""

import json
import os
import re
import glob
import sqlite3
import csv
import math

import yaml
import pandas as pd

from typing import Tuple, Dict, List, Any


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

    # ========== TOOL METHODS ==========

    @tool(
        description=(
            "List suppliers who submitted bids for the current municipal "
            "infrastructure tender. Returns a paginated list of bidder IDs "
            "and names."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                    "default": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)",
                    "default": 10,
                },
            },
            "required": [],
        },
    )
    def list_tender_bidders(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        total = conn.execute("SELECT COUNT(*) FROM tender_bids").fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            """
            SELECT tb.supplier_id, s.name, tb.submission_date
            FROM tender_bids tb
            JOIN suppliers s ON tb.supplier_id = s.supplier_id
            ORDER BY tb.supplier_id
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_bidders": total,
            "total_pages": math.ceil(total / page_size),
            "bidders": [
                {
                    "supplier_id": r[0],
                    "supplier_name": r[1],
                    "submission_date": r[2],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Get the detailed profile of a specific supplier including "
            "registration, location, category, and establishment year."
        ),
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The unique supplier identifier",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_profile(self, supplier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            """
            SELECT supplier_id, name, registration_number, city, state,
                   established_year, primary_category, employee_count, contact_email
            FROM suppliers WHERE supplier_id = ?
            """,
            (supplier_id,),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Supplier {supplier_id} not found"}
        return {
            "supplier_id": row[0],
            "name": row[1],
            "registration_number": row[2],
            "city": row[3],
            "state": row[4],
            "established_year": row[5],
            "primary_category": row[6],
            "employee_count": row[7],
            "contact_email": row[8],
        }

    @tool(
        description=(
            "Retrieve all qualification certificates held by a specific supplier, "
            "including certificate type, issuing body, dates, and current status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The unique supplier identifier",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier_certificates(self, supplier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """
            SELECT cert_id, cert_type, issuing_body, issue_date, expiry_date, cert_status
            FROM certificates WHERE supplier_id = ?
            ORDER BY cert_type
            """,
            (supplier_id,),
        ).fetchall()
        conn.close()
        return {
            "supplier_id": supplier_id,
            "certificate_count": len(rows),
            "certificates": [
                {
                    "cert_id": r[0],
                    "cert_type": r[1],
                    "issuing_body": r[2],
                    "issue_date": r[3],
                    "expiry_date": r[4],
                    "status": r[5],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Retrieve past project performance records for a specific supplier, "
            "including project details, scores, and on-time delivery status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The unique supplier identifier",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_performance_history(self, supplier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """
            SELECT record_id, project_name, client_name, domain,
                   contract_value, performance_score, completion_year, on_time
            FROM project_history WHERE supplier_id = ?
            ORDER BY completion_year DESC
            """,
            (supplier_id,),
        ).fetchall()
        conn.close()
        return {
            "supplier_id": supplier_id,
            "project_count": len(rows),
            "projects": [
                {
                    "record_id": r[0],
                    "project_name": r[1],
                    "client_name": r[2],
                    "domain": r[3],
                    "contract_value": r[4],
                    "performance_score": r[5],
                    "completion_year": r[6],
                    "on_time": bool(r[7]),
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Retrieve the bid line items submitted by a specific supplier "
            "for the current tender, including item codes, prices, and quantities."
        ),
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The unique supplier identifier",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_bid_details(self, supplier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """
            SELECT item_id, line_item_code, description, unit,
                   unit_price, quantity, total_price
            FROM bid_line_items WHERE supplier_id = ?
            ORDER BY line_item_code
            """,
            (supplier_id,),
        ).fetchall()
        conn.close()
        total_bid = sum(r[6] for r in rows)
        return {
            "supplier_id": supplier_id,
            "line_item_count": len(rows),
            "total_bid_amount": round(total_bid, 2),
            "line_items": [
                {
                    "item_id": r[0],
                    "line_item_code": r[1],
                    "description": r[2],
                    "unit": r[3],
                    "unit_price": r[4],
                    "quantity": r[5],
                    "total_price": r[6],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Retrieve sustainability criteria responses submitted by a specific "
            "supplier, showing compliance status for each criterion."
        ),
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "integer",
                    "description": "The unique supplier identifier",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_sustainability_responses(self, supplier_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """
            SELECT response_id, criterion_id, response, evidence_reference
            FROM sustainability_responses WHERE supplier_id = ?
            ORDER BY criterion_id
            """,
            (supplier_id,),
        ).fetchall()
        conn.close()
        return {
            "supplier_id": supplier_id,
            "response_count": len(rows),
            "responses": [
                {
                    "response_id": r[0],
                    "criterion_id": r[1],
                    "response": r[2],
                    "evidence_reference": r[3],
                }
                for r in rows
            ],
        }

    # ========== GROUND TRUTH COMPUTATION (used by step) ==========

    def _compute_ground_truth(self):
        """Compute the full ground truth for evaluation."""
        # Read config files
        with open(os.path.join(self.workspace, "tender_specification.yaml")) as f:
            tender_spec = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "sustainability_criteria.json")) as f:
            sus_criteria = json.load(f)["criteria"]
        with open(os.path.join(self.workspace, "scoring_methodology.yaml")) as f:
            scoring = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "disqualification_rules.json")) as f:
            disq_rules = json.load(f)["rules"]

        required_certs = tender_spec["required_certificates"]
        min_perf = tender_spec["min_avg_performance_score"]
        min_years = tender_spec["min_established_years"]
        eval_date = tender_spec["evaluation_date"]
        eval_year = int(eval_date.split("-")[0])

        mandatory_criteria = [
            c["criterion_id"] for c in sus_criteria if c["mandatory"]
        ]

        conn = sqlite3.connect(self.db_path)

        # Get all bidders
        bidders = conn.execute(
            """
            SELECT tb.supplier_id, s.name, s.established_year
            FROM tender_bids tb
            JOIN suppliers s ON tb.supplier_id = s.supplier_id
            ORDER BY tb.supplier_id
            """
        ).fetchall()

        # Read financial data from workspace CSVs
        financial_data = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "financial_batch_*.csv"))):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                financial_data[int(row["supplier_id"])] = {
                    "profit_margin_pct": float(row["profit_margin_pct"]),
                    "debt_ratio": float(row["debt_ratio"]),
                    "liquidity_ratio": float(row["liquidity_ratio"]),
                    "credit_score": int(row["credit_score"]),
                }

        # Read reference summaries for reliability ratings
        reliability_ratings = {}
        for fp in sorted(
            glob.glob(os.path.join(self.workspace, "reference_summary_*.txt"))
        ):
            with open(fp) as f:
                content = f.read()
            for match in re.finditer(
                r"\(ID:\s*(\d+)\).*?reliability_rating:\s*([\d.]+)/10",
                content,
                re.DOTALL,
            ):
                sid = int(match.group(1))
                rating = float(match.group(2))
                reliability_ratings[sid] = rating

        # Read technical evaluations
        technical_data = {}
        for fp in sorted(
            glob.glob(os.path.join(self.workspace, "technical_evaluation_*.json"))
        ):
            with open(fp) as f:
                evals = json.load(f)["evaluations"]
            for ev in evals:
                technical_data[int(ev["supplier_id"])] = {
                    "technical_score": float(ev["technical_score"]),
                    "innovation_score": float(ev["innovation_score"]),
                    "methodology_score": float(ev["methodology_score"]),
                }

        # Evaluate each bidder
        disqualified = []
        qualified = []

        for sid, sname, est_year in bidders:
            reasons = []

            # DQ-06: Established years
            years_in_business = eval_year - est_year
            if years_in_business < min_years:
                reasons.append(
                    f"DQ-06: Established only {years_in_business} years "
                    f"before evaluation (minimum {min_years})"
                )

            # DQ-01 & DQ-02: Certificate checks
            certs = conn.execute(
                "SELECT cert_type, cert_status FROM certificates WHERE supplier_id=?",
                (sid,),
            ).fetchall()
            cert_map = {}
            for ct, cs in certs:
                if ct not in cert_map:
                    cert_map[ct] = []
                cert_map[ct].append(cs)

            for req_cert in required_certs:
                if req_cert not in cert_map:
                    reasons.append(
                        f"DQ-01: Missing required certificate: {req_cert}"
                    )
                else:
                    # Check if at least one is active
                    if all(s == "expired" for s in cert_map[req_cert]):
                        reasons.append(
                            f"DQ-02: Required certificate expired: {req_cert}"
                        )

            # DQ-04: Performance score
            perf_rows = conn.execute(
                "SELECT performance_score FROM project_history WHERE supplier_id=?",
                (sid,),
            ).fetchall()
            avg_perf = (
                sum(r[0] for r in perf_rows) / len(perf_rows) if perf_rows else 0
            )
            if avg_perf < min_perf:
                reasons.append(
                    f"DQ-04: Average performance score {avg_perf:.1f} "
                    f"below minimum {min_perf}"
                )

            # DQ-03: Mandatory sustainability
            sus_rows = conn.execute(
                "SELECT criterion_id, response FROM sustainability_responses "
                "WHERE supplier_id=?",
                (sid,),
            ).fetchall()
            sus_map = {r[0]: r[1] for r in sus_rows}
            for mc in mandatory_criteria:
                if sus_map.get(mc) != "compliant":
                    reasons.append(
                        f"DQ-03: Mandatory sustainability criterion {mc} "
                        f"not compliant (status: {sus_map.get(mc, 'missing')})"
                    )
                    break  # One failure is enough for DQ-03

            # DQ-05: Debt ratio
            fin = financial_data.get(sid, {})
            debt_ratio = fin.get("debt_ratio", 1.0)
            if debt_ratio > 0.70:
                reasons.append(
                    f"DQ-05: Debt ratio {debt_ratio:.2f} exceeds 0.70"
                )

            if reasons:
                disqualified.append({
                    "supplier_id": sid,
                    "supplier_name": sname,
                    "reasons": reasons,
                })
            else:
                qualified.append({
                    "supplier_id": sid,
                    "supplier_name": sname,
                    "avg_performance": avg_perf,
                    "financial": fin,
                    "sustainability_responses": sus_map,
                    "reliability_rating": reliability_ratings.get(sid, 5.0),
                })

        conn.close()

        # Compute dimension scores for qualified bidders
        dims = scoring["dimensions"]

        # Compute all bid totals first for pricing normalization
        conn2 = sqlite3.connect(self.db_path)
        bid_totals = {}
        for q in qualified:
            sid = q["supplier_id"]
            total = conn2.execute(
                "SELECT SUM(total_price) FROM bid_line_items WHERE supplier_id=?",
                (sid,),
            ).fetchone()[0]
            bid_totals[sid] = total or 0.0
        conn2.close()

        lowest_bid = min(bid_totals.values()) if bid_totals else 1.0

        scored = []
        for q in qualified:
            sid = q["supplier_id"]

            # Performance dimension
            perf_avg = q["avg_performance"]
            rel_rating = q["reliability_rating"]
            rel_normalized = (rel_rating / 10.0) * 100.0
            performance_score = (
                perf_avg * dims["performance"]["components"]["project_history_avg"]["weight"]
                + rel_normalized * dims["performance"]["components"]["reliability_rating"]["weight"]
            )

            # Financial dimension
            fin = q["financial"]
            profit_norm = min(fin.get("profit_margin_pct", 0) / 30.0 * 100, 100)
            liq_norm = min(fin.get("liquidity_ratio", 0) / 5.0 * 100, 100)
            debt_norm = (1 - fin.get("debt_ratio", 1.0)) * 100
            credit_norm = min(fin.get("credit_score", 0) / 850.0 * 100, 100)
            fc = dims["financial"]["components"]
            financial_score = (
                profit_norm * fc["profit_margin_pct"]["weight"]
                + liq_norm * fc["liquidity_ratio"]["weight"]
                + debt_norm * fc["debt_health"]["weight"]
                + credit_norm * fc["credit_score"]["weight"]
            )

            # Pricing dimension
            total_bid = bid_totals[sid]
            pricing_score = (lowest_bid / total_bid * 100) if total_bid > 0 else 0

            # Sustainability dimension
            sus_resp = q["sustainability_responses"]
            sus_values = []
            all_criteria_ids = [c["criterion_id"] for c in json.load(
                open(os.path.join(self.workspace, "sustainability_criteria.json"))
            )["criteria"]]
            for cid in all_criteria_ids:
                resp = sus_resp.get(cid, "non_compliant")
                if resp == "compliant":
                    sus_values.append(1.0)
                elif resp == "partial":
                    sus_values.append(0.5)
                else:
                    sus_values.append(0.0)
            sustainability_score = (
                (sum(sus_values) / len(sus_values)) * 100 if sus_values else 0
            )

            # Technical dimension
            tech = technical_data.get(sid, {})
            tc = dims["technical"]["components"]
            technical_score = (
                tech.get("technical_score", 50) * tc["technical_score"]["weight"]
                + tech.get("innovation_score", 50) * tc["innovation_score"]["weight"]
                + tech.get("methodology_score", 50) * tc["methodology_score"]["weight"]
            )

            # Composite
            composite = (
                performance_score * dims["performance"]["weight"]
                + financial_score * dims["financial"]["weight"]
                + pricing_score * dims["pricing"]["weight"]
                + sustainability_score * dims["sustainability"]["weight"]
                + technical_score * dims["technical"]["weight"]
            )

            scored.append({
                "supplier_id": sid,
                "supplier_name": q["supplier_name"],
                "composite_score": round(composite, 2),
                "performance_score": round(performance_score, 2),
                "financial_score": round(financial_score, 2),
                "pricing_score": round(pricing_score, 2),
                "sustainability_score": round(sustainability_score, 2),
                "technical_score": round(technical_score, 2),
                "total_bid_amount": round(total_bid, 2),
            })

        # Sort: descending composite, ascending bid for ties
        scored.sort(key=lambda x: (-x["composite_score"], x["total_bid_amount"]))

        # Assign ranks
        for i, s in enumerate(scored, 1):
            s["rank"] = i

        return {
            "disqualified": disqualified,
            "qualified_ranked": scored,
            "total_bidders": len(bidders),
            "total_disqualified": len(disqualified),
            "total_qualified": len(scored),
        }

    # ========== STEP ==========

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt = self._compute_ground_truth()
        criteria = {}
        total_score = 0
        max_score = 0

        # --- Criterion 1: vendor_shortlist.csv exists with correct columns (15 pts) ---
        c1_max = 15
        max_score += c1_max
        shortlist_path = os.path.join(self.workspace, "vendor_shortlist.csv")
        expected_cols = [
            "rank", "supplier_id", "supplier_name", "composite_score",
            "performance_score", "financial_score", "pricing_score",
            "sustainability_score", "technical_score",
        ]
        if os.path.exists(shortlist_path):
            try:
                df = pd.read_csv(shortlist_path)
                actual_cols = [c.strip().lower() for c in df.columns]
                if all(c in actual_cols for c in expected_cols):
                    criteria["output_file_format"] = {
                        "passed": True, "score": c1_max, "max_score": c1_max,
                    }
                    total_score += c1_max
                else:
                    missing = [c for c in expected_cols if c not in actual_cols]
                    criteria["output_file_format"] = {
                        "passed": False, "score": 5, "max_score": c1_max,
                        "reason": f"Missing columns: {missing}",
                    }
                    total_score += 5
            except Exception as e:
                criteria["output_file_format"] = {
                    "passed": False, "score": 0, "max_score": c1_max,
                    "reason": f"Error reading CSV: {e}",
                }
        else:
            criteria["output_file_format"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "vendor_shortlist.csv not found",
            }

        # --- Criterion 2: Correct set of qualified vendors (20 pts) ---
        c2_max = 20
        max_score += c2_max
        gt_qualified_ids = set(
            s["supplier_id"] for s in gt["qualified_ranked"]
        )
        agent_qualified_ids = set()
        if os.path.exists(shortlist_path):
            try:
                df = pd.read_csv(shortlist_path)
                col = "supplier_id" if "supplier_id" in df.columns else None
                if col is None:
                    for c in df.columns:
                        if "supplier" in c.lower() and "id" in c.lower():
                            col = c
                            break
                if col:
                    agent_qualified_ids = set(int(x) for x in df[col])
            except Exception:
                pass

        if gt_qualified_ids and agent_qualified_ids:
            correct = gt_qualified_ids & agent_qualified_ids
            extra = agent_qualified_ids - gt_qualified_ids
            missing = gt_qualified_ids - agent_qualified_ids
            accuracy = len(correct) / max(len(gt_qualified_ids), len(agent_qualified_ids))
            c2_score = round(accuracy * c2_max)
            criteria["qualified_vendor_set"] = {
                "passed": accuracy == 1.0,
                "score": c2_score,
                "max_score": c2_max,
                "reason": (
                    None if accuracy == 1.0
                    else f"Extra: {extra}, Missing: {missing}"
                ),
            }
            total_score += c2_score
        elif not gt_qualified_ids:
            criteria["qualified_vendor_set"] = {
                "passed": len(agent_qualified_ids) == 0,
                "score": c2_max if len(agent_qualified_ids) == 0 else 0,
                "max_score": c2_max,
            }
            if len(agent_qualified_ids) == 0:
                total_score += c2_max
        else:
            criteria["qualified_vendor_set"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "No qualified vendors found in output",
            }

        # --- Criterion 3: Composite score accuracy (20 pts) ---
        c3_max = 20
        max_score += c3_max
        if os.path.exists(shortlist_path) and gt["qualified_ranked"]:
            try:
                df = pd.read_csv(shortlist_path)
                sid_col = None
                score_col = None
                for c in df.columns:
                    cl = c.strip().lower()
                    if cl == "supplier_id":
                        sid_col = c
                    elif cl == "composite_score":
                        score_col = c
                if sid_col and score_col:
                    agent_scores = {
                        int(row[sid_col]): float(row[score_col])
                        for _, row in df.iterrows()
                    }
                    gt_scores = {
                        s["supplier_id"]: s["composite_score"]
                        for s in gt["qualified_ranked"]
                    }
                    matching = 0
                    compared = 0
                    for sid, gt_sc in gt_scores.items():
                        if sid in agent_scores:
                            compared += 1
                            if abs(agent_scores[sid] - gt_sc) < 1.0:
                                matching += 1
                    accuracy = matching / compared if compared else 0
                    c3_score = round(accuracy * c3_max)
                    criteria["score_accuracy"] = {
                        "passed": accuracy >= 0.95,
                        "score": c3_score,
                        "max_score": c3_max,
                        "reason": (
                            None if accuracy >= 0.95
                            else f"Only {matching}/{compared} scores within tolerance"
                        ),
                    }
                    total_score += c3_score
                else:
                    criteria["score_accuracy"] = {
                        "passed": False, "score": 0, "max_score": c3_max,
                        "reason": "Required columns not found",
                    }
            except Exception as e:
                criteria["score_accuracy"] = {
                    "passed": False, "score": 0, "max_score": c3_max,
                    "reason": f"Error: {e}",
                }
        else:
            criteria["score_accuracy"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "No shortlist file or no qualified vendors",
            }

        # --- Criterion 4: Ranking order correctness (15 pts) ---
        c4_max = 15
        max_score += c4_max
        if os.path.exists(shortlist_path) and gt["qualified_ranked"]:
            try:
                df = pd.read_csv(shortlist_path)
                sid_col = None
                for c in df.columns:
                    if c.strip().lower() == "supplier_id":
                        sid_col = c
                        break
                if sid_col:
                    agent_order = [int(x) for x in df[sid_col]]
                    gt_order = [s["supplier_id"] for s in gt["qualified_ranked"]]
                    # Check if order matches
                    if agent_order == gt_order:
                        criteria["ranking_order"] = {
                            "passed": True, "score": c4_max, "max_score": c4_max,
                        }
                        total_score += c4_max
                    else:
                        # Partial credit: Kendall tau distance
                        common = set(agent_order) & set(gt_order)
                        if len(common) >= 2:
                            gt_pos = {
                                sid: i for i, sid in enumerate(gt_order)
                                if sid in common
                            }
                            agent_pos = {
                                sid: i for i, sid in enumerate(agent_order)
                                if sid in common
                            }
                            concordant = 0
                            total_pairs = 0
                            common_list = sorted(common)
                            for a in range(len(common_list)):
                                for b in range(a + 1, len(common_list)):
                                    sa, sb = common_list[a], common_list[b]
                                    if sa in gt_pos and sb in gt_pos and sa in agent_pos and sb in agent_pos:
                                        total_pairs += 1
                                        gt_cmp = gt_pos[sa] < gt_pos[sb]
                                        ag_cmp = agent_pos[sa] < agent_pos[sb]
                                        if gt_cmp == ag_cmp:
                                            concordant += 1
                            tau = concordant / total_pairs if total_pairs else 0
                            c4_score = round(tau * c4_max)
                        else:
                            c4_score = 0
                        criteria["ranking_order"] = {
                            "passed": False, "score": c4_score, "max_score": c4_max,
                            "reason": f"Order mismatch: expected {gt_order}, got {agent_order}",
                        }
                        total_score += c4_score
                else:
                    criteria["ranking_order"] = {
                        "passed": False, "score": 0, "max_score": c4_max,
                        "reason": "supplier_id column not found",
                    }
            except Exception as e:
                criteria["ranking_order"] = {
                    "passed": False, "score": 0, "max_score": c4_max,
                    "reason": f"Error: {e}",
                }
        else:
            criteria["ranking_order"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "No shortlist or no qualified vendors",
            }

        # --- Criterion 5: Disqualification report (15 pts) ---
        c5_max = 15
        max_score += c5_max
        disq_path = os.path.join(self.workspace, "disqualification_report.json")
        if os.path.exists(disq_path):
            try:
                with open(disq_path) as f:
                    disq_report = json.load(f)
                agent_disq_ids = set()
                if "disqualified_vendors" in disq_report:
                    for v in disq_report["disqualified_vendors"]:
                        agent_disq_ids.add(int(v.get("supplier_id", -1)))
                gt_disq_ids = set(d["supplier_id"] for d in gt["disqualified"])
                if gt_disq_ids:
                    correct = gt_disq_ids & agent_disq_ids
                    accuracy = len(correct) / max(len(gt_disq_ids), len(agent_disq_ids))
                    c5_score = round(accuracy * c5_max)
                    criteria["disqualification_report"] = {
                        "passed": accuracy == 1.0,
                        "score": c5_score,
                        "max_score": c5_max,
                        "reason": (
                            None if accuracy == 1.0
                            else f"Expected {gt_disq_ids}, got {agent_disq_ids}"
                        ),
                    }
                    total_score += c5_score
                else:
                    # No one should be disqualified
                    c5_score = c5_max if len(agent_disq_ids) == 0 else 0
                    criteria["disqualification_report"] = {
                        "passed": c5_score == c5_max,
                        "score": c5_score,
                        "max_score": c5_max,
                    }
                    total_score += c5_score
            except Exception as e:
                criteria["disqualification_report"] = {
                    "passed": False, "score": 0, "max_score": c5_max,
                    "reason": f"Error reading report: {e}",
                }
        else:
            criteria["disqualification_report"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "disqualification_report.json not found",
            }

        # --- Criterion 6: Response summary content (15 pts) ---
        c6_max = 15
        max_score += c6_max
        c6_score = 0
        reasons = []

        if gt["qualified_ranked"]:
            top_vendor = gt["qualified_ranked"][0]
            # Check if action contains top vendor name
            if top_vendor["supplier_name"] in action:
                c6_score += 5
            else:
                reasons.append("Top vendor name not in response")

            # Check total bidders count
            if str(gt["total_bidders"]) in action:
                c6_score += 3
            else:
                reasons.append("Total bidders count not in response")

            # Check qualified count
            if str(gt["total_qualified"]) in action:
                c6_score += 4
            else:
                reasons.append("Qualified count not in response")

            # Check top composite score
            top_score_str = f"{top_vendor['composite_score']:.2f}"
            if top_score_str in action:
                c6_score += 3
            else:
                reasons.append("Top composite score not in response")

        criteria["response_summary"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "; ".join(reasons) if reasons else None,
        }
        total_score += c6_score

        reward = total_score / max_score if max_score > 0 else 0.0

        return reward, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ========== VERIFY ==========

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import re as _re

        tool_call_count = 0

        def call_tool(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # Step 1: Read workspace config files
        with open(os.path.join(self.workspace, "tender_specification.yaml")) as f:
            tender_spec = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "sustainability_criteria.json")) as f:
            sus_criteria = json.load(f)["criteria"]
        with open(os.path.join(self.workspace, "scoring_methodology.yaml")) as f:
            scoring = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "disqualification_rules.json")) as f:
            disq_rules = json.load(f)["rules"]

        required_certs = tender_spec["required_certificates"]
        min_perf = tender_spec["min_avg_performance_score"]
        min_years = tender_spec["min_established_years"]
        eval_year = int(tender_spec["evaluation_date"].split("-")[0])

        mandatory_crit_ids = [c["criterion_id"] for c in sus_criteria if c["mandatory"]]
        all_crit_ids = [c["criterion_id"] for c in sus_criteria]

        # Step 2: Read financial data from workspace CSVs
        financial_data = {}
        for fp in sorted(glob.glob(os.path.join(self.workspace, "financial_batch_*.csv"))):
            df = pd.read_csv(fp)
            for _, row in df.iterrows():
                financial_data[int(row["supplier_id"])] = {
                    "profit_margin_pct": float(row["profit_margin_pct"]),
                    "debt_ratio": float(row["debt_ratio"]),
                    "liquidity_ratio": float(row["liquidity_ratio"]),
                    "credit_score": int(row["credit_score"]),
                }

        # Step 3: Read reference summaries for reliability ratings
        reliability_ratings = {}
        for fp in sorted(
            glob.glob(os.path.join(self.workspace, "reference_summary_*.txt"))
        ):
            with open(fp) as f:
                content = f.read()
            for match in _re.finditer(
                r"\(ID:\s*(\d+)\).*?reliability_rating:\s*([\d.]+)/10",
                content,
                _re.DOTALL,
            ):
                sid = int(match.group(1))
                rating = float(match.group(2))
                reliability_ratings[sid] = rating

        # Step 4: Read technical evaluations
        technical_data = {}
        for fp in sorted(
            glob.glob(os.path.join(self.workspace, "technical_evaluation_*.json"))
        ):
            with open(fp) as f:
                evals = json.load(f)["evaluations"]
            for ev in evals:
                technical_data[int(ev["supplier_id"])] = {
                    "technical_score": float(ev["technical_score"]),
                    "innovation_score": float(ev["innovation_score"]),
                    "methodology_score": float(ev["methodology_score"]),
                }

        # Step 5: List all tender bidders via tool
        all_bidders = []
        page = 1
        while True:
            result = call_tool("list_tender_bidders", page=page, page_size=10)
            all_bidders.extend(result["bidders"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 6: For each bidder, gather all data via tools
        disqualified = []
        qualified_data = []

        for bidder in all_bidders:
            sid = bidder["supplier_id"]
            sname = bidder["supplier_name"]
            reasons = []

            # Get profile (for established_year)
            profile = call_tool("get_supplier_profile", supplier_id=sid)
            est_year = profile["established_year"]
            years_in_business = eval_year - est_year
            if years_in_business < min_years:
                reasons.append(
                    f"DQ-06: Established only {years_in_business} years "
                    f"before evaluation (minimum {min_years})"
                )

            # Get certificates
            cert_result = call_tool("get_supplier_certificates", supplier_id=sid)
            cert_map = {}
            for c in cert_result["certificates"]:
                ct = c["cert_type"]
                if ct not in cert_map:
                    cert_map[ct] = []
                cert_map[ct].append(c["status"])

            for req_cert in required_certs:
                if req_cert not in cert_map:
                    reasons.append(f"DQ-01: Missing required certificate: {req_cert}")
                else:
                    if all(s == "expired" for s in cert_map[req_cert]):
                        reasons.append(f"DQ-02: Required certificate expired: {req_cert}")

            # Get performance history
            perf_result = call_tool("get_performance_history", supplier_id=sid)
            scores = [p["performance_score"] for p in perf_result["projects"]]
            avg_perf = sum(scores) / len(scores) if scores else 0
            if avg_perf < min_perf:
                reasons.append(
                    f"DQ-04: Average performance score {avg_perf:.1f} "
                    f"below minimum {min_perf}"
                )

            # Get sustainability responses
            sus_result = call_tool("get_sustainability_responses", supplier_id=sid)
            sus_map = {r["criterion_id"]: r["response"] for r in sus_result["responses"]}
            mandatory_fail = False
            for mc in mandatory_crit_ids:
                if sus_map.get(mc) != "compliant":
                    reasons.append(
                        f"DQ-03: Mandatory sustainability criterion {mc} "
                        f"not compliant (status: {sus_map.get(mc, 'missing')})"
                    )
                    mandatory_fail = True
                    break

            # DQ-05: Debt ratio from financial data
            fin = financial_data.get(sid, {})
            debt_ratio = fin.get("debt_ratio", 1.0)
            if debt_ratio > 0.70:
                reasons.append(f"DQ-05: Debt ratio {debt_ratio:.2f} exceeds 0.70")

            # Get bid details
            bid_result = call_tool("get_bid_details", supplier_id=sid)

            if reasons:
                disqualified.append({
                    "supplier_id": sid,
                    "supplier_name": sname,
                    "reasons": reasons,
                })
            else:
                qualified_data.append({
                    "supplier_id": sid,
                    "supplier_name": sname,
                    "avg_performance": avg_perf,
                    "financial": fin,
                    "sustainability_map": sus_map,
                    "reliability_rating": reliability_ratings.get(sid, 5.0),
                    "total_bid": bid_result["total_bid_amount"],
                    "technical": technical_data.get(sid, {}),
                })

        # Step 7: Compute dimension scores
        dims = scoring["dimensions"]

        # Find lowest bid among qualified
        if qualified_data:
            lowest_bid = min(q["total_bid"] for q in qualified_data)
        else:
            lowest_bid = 1.0

        scored = []
        for q in qualified_data:
            sid = q["supplier_id"]

            # Performance
            perf_avg = q["avg_performance"]
            rel_rating = q["reliability_rating"]
            rel_normalized = (rel_rating / 10.0) * 100.0
            performance_score = (
                perf_avg * dims["performance"]["components"]["project_history_avg"]["weight"]
                + rel_normalized * dims["performance"]["components"]["reliability_rating"]["weight"]
            )

            # Financial
            fin = q["financial"]
            profit_norm = min(fin.get("profit_margin_pct", 0) / 30.0 * 100, 100)
            liq_norm = min(fin.get("liquidity_ratio", 0) / 5.0 * 100, 100)
            debt_norm = (1 - fin.get("debt_ratio", 1.0)) * 100
            credit_norm = min(fin.get("credit_score", 0) / 850.0 * 100, 100)
            fc = dims["financial"]["components"]
            financial_score = (
                profit_norm * fc["profit_margin_pct"]["weight"]
                + liq_norm * fc["liquidity_ratio"]["weight"]
                + debt_norm * fc["debt_health"]["weight"]
                + credit_norm * fc["credit_score"]["weight"]
            )

            # Pricing
            pricing_score = (lowest_bid / q["total_bid"] * 100) if q["total_bid"] > 0 else 0

            # Sustainability
            sus_values = []
            for cid in all_crit_ids:
                resp = q["sustainability_map"].get(cid, "non_compliant")
                if resp == "compliant":
                    sus_values.append(1.0)
                elif resp == "partial":
                    sus_values.append(0.5)
                else:
                    sus_values.append(0.0)
            sustainability_score = (
                (sum(sus_values) / len(sus_values)) * 100 if sus_values else 0
            )

            # Technical
            tech = q["technical"]
            tc = dims["technical"]["components"]
            technical_score = (
                tech.get("technical_score", 50) * tc["technical_score"]["weight"]
                + tech.get("innovation_score", 50) * tc["innovation_score"]["weight"]
                + tech.get("methodology_score", 50) * tc["methodology_score"]["weight"]
            )

            # Composite
            composite = (
                performance_score * dims["performance"]["weight"]
                + financial_score * dims["financial"]["weight"]
                + pricing_score * dims["pricing"]["weight"]
                + sustainability_score * dims["sustainability"]["weight"]
                + technical_score * dims["technical"]["weight"]
            )

            scored.append({
                "supplier_id": sid,
                "supplier_name": q["supplier_name"],
                "composite_score": round(composite, 2),
                "performance_score": round(performance_score, 2),
                "financial_score": round(financial_score, 2),
                "pricing_score": round(pricing_score, 2),
                "sustainability_score": round(sustainability_score, 2),
                "technical_score": round(technical_score, 2),
                "total_bid_amount": round(q["total_bid"], 2),
            })

        # Sort
        scored.sort(key=lambda x: (-x["composite_score"], x["total_bid_amount"]))
        for i, s in enumerate(scored, 1):
            s["rank"] = i

        # Step 8: Write deliverables

        # vendor_shortlist.csv
        shortlist_rows = []
        for s in scored:
            shortlist_rows.append({
                "rank": s["rank"],
                "supplier_id": s["supplier_id"],
                "supplier_name": s["supplier_name"],
                "composite_score": f"{s['composite_score']:.2f}",
                "performance_score": f"{s['performance_score']:.2f}",
                "financial_score": f"{s['financial_score']:.2f}",
                "pricing_score": f"{s['pricing_score']:.2f}",
                "sustainability_score": f"{s['sustainability_score']:.2f}",
                "technical_score": f"{s['technical_score']:.2f}",
            })

        shortlist_path = os.path.join(self.workspace, "vendor_shortlist.csv")
        if shortlist_rows:
            df_out = pd.DataFrame(shortlist_rows)
            df_out.to_csv(shortlist_path, index=False)
        else:
            with open(shortlist_path, "w") as f:
                f.write(",".join([
                    "rank", "supplier_id", "supplier_name", "composite_score",
                    "performance_score", "financial_score", "pricing_score",
                    "sustainability_score", "technical_score",
                ]) + "\n")

        # disqualification_report.json
        disq_report = {
            "disqualified_vendors": disqualified,
            "total_evaluated": len(all_bidders),
            "total_disqualified": len(disqualified),
            "total_qualified": len(scored),
        }
        with open(
            os.path.join(self.workspace, "disqualification_report.json"), "w"
        ) as f:
            json.dump(disq_report, f, indent=2)

        # Step 9: Build action string
        top_name = scored[0]["supplier_name"] if scored else "N/A"
        top_score = scored[0]["composite_score"] if scored else 0
        action = (
            f"Evaluation complete. {len(all_bidders)} bidders were evaluated for the "
            f"municipal infrastructure tender. {len(disqualified)} vendors were "
            f"disqualified based on certificate, performance, sustainability, and "
            f"financial criteria. {len(scored)} vendors qualified and have been "
            f"ranked in the shortlist. The top-ranked vendor is {top_name} with a "
            f"composite score of {top_score:.2f}. The full ranked shortlist has been "
            f"saved to vendor_shortlist.csv and the disqualification report to "
            f"disqualification_report.json."
        )

        assert tool_call_count >= 15, (
            f"verify used only {tool_call_count} tool calls, need at least 15"
        )

        return self.step(action)
