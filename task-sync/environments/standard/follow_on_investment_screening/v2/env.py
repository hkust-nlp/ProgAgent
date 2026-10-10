import sqlite3
import os
import json
import csv
import glob
import re
import math
from typing import Tuple, Dict, List, Any

import yaml


# --- Decorator for tool registration (keep unchanged) ---
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

    # ================================================================== #
    #  TOOLS                                                              #
    # ================================================================== #

    @tool(
        description="Returns a paginated list of portfolio companies. Each entry contains company_id and name only.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of companies per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_portfolio_companies(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM companies")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT company_id, name FROM companies ORDER BY company_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "companies": [{"company_id": r[0], "name": r[1]} for r in rows],
        }

    @tool(
        description="Returns detailed information for a single portfolio company identified by company_id.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique identifier of the portfolio company.",
                },
            },
            "required": ["company_id"],
        },
    )
    def get_company_info(self, company_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM companies WHERE company_id = ?", (company_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Company {company_id} not found."}
        return dict(row)

    @tool(
        description="Returns monthly financial records (revenue, expenses, burn_rate, cash_on_hand) for a portfolio company. Records are sorted chronologically.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique identifier of the portfolio company.",
                },
            },
            "required": ["company_id"],
        },
    )
    def get_company_financials(self, company_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT month, revenue, expenses, burn_rate, cash_on_hand "
            "FROM monthly_financials WHERE company_id = ? ORDER BY month",
            (company_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"company_id": company_id, "financials": rows}

    @tool(
        description="Returns the cap table for a portfolio company, listing all shareholders with their type, shares, ownership percentage, and the round in which they acquired equity.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique identifier of the portfolio company.",
                },
            },
            "required": ["company_id"],
        },
    )
    def get_cap_table(self, company_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT shareholder_name, shareholder_type, shares, ownership_pct, "
            "round_acquired FROM cap_table WHERE company_id = ? "
            "ORDER BY ownership_pct DESC",
            (company_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"company_id": company_id, "shareholders": rows}

    @tool(
        description="Returns all internal partner sentiment assessments for a portfolio company, including scores, dates, and focus areas.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique identifier of the portfolio company.",
                },
            },
            "required": ["company_id"],
        },
    )
    def get_partner_sentiments(self, company_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT partner_name, sentiment_score, assessment_date, focus_area "
            "FROM partner_sentiments WHERE company_id = ? "
            "ORDER BY assessment_date",
            (company_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"company_id": company_id, "sentiments": rows}

    @tool(
        description="Returns paginated competitor funding rounds filtered by sector. Each record includes competitor name, round type, amount raised, lead investor, and date.",
        parameters={
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": "The sector to filter competitor funding rounds by.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 100).",
                },
            },
            "required": ["sector", "page", "page_size"],
        },
    )
    def get_competitor_funding(self, sector: str, page: int, page_size: int) -> dict:
        page_size = min(page_size, 100)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM competitor_funding WHERE sector = ?", (sector,)
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT competitor_name, sector, round_type, amount_raised, "
            "lead_investor, funding_date FROM competitor_funding "
            "WHERE sector = ? ORDER BY funding_date DESC LIMIT ? OFFSET ?",
            (sector, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "sector": sector,
            "total": total,
            "page": page,
            "page_size": page_size,
            "rounds": rows,
        }

    # ================================================================== #
    #  HELPERS                                                            #
    # ================================================================== #

    def _extract_strategic_scores(self) -> Dict[int, float]:
        """Parse every intel_report_* file in workspace and return {company_id: score}."""
        scores: Dict[int, float] = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "intel_report_*"))):
            ext = os.path.splitext(fpath)[1].lower()
            try:
                if ext == ".json":
                    with open(fpath) as f:
                        data = json.load(f)
                    for entry in data:
                        scores[int(entry["company_id"])] = float(entry["strategic_fit_score"])
                elif ext == ".csv":
                    with open(fpath) as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            scores[int(row["company_id"])] = float(row["strategic_fit_score"])
                elif ext == ".yaml" or ext == ".yml":
                    with open(fpath) as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        for key, val in data.items():
                            m = re.match(r"company_(\d+)", key)
                            if m:
                                scores[int(m.group(1))] = float(val["strategic_fit_score"])
                elif ext == ".md":
                    with open(fpath) as f:
                        content = f.read()
                    for block in content.split("---"):
                        id_match = re.search(r"Company ID:\s*(\d+)", block)
                        sc_match = re.search(r"Strategic Fit Score:\s*([\d.]+)", block)
                        if id_match and sc_match:
                            scores[int(id_match.group(1))] = float(sc_match.group(1))
                elif ext == ".txt":
                    with open(fpath) as f:
                        content = f.read()
                    for block in content.split("=" * 60):
                        id_match = re.search(r"\(ID:\s*(\d+)\)", block)
                        sc_match = re.search(r"STRATEGIC FIT SCORE:\s*([\d.]+)", block)
                        if id_match and sc_match:
                            scores[int(id_match.group(1))] = float(sc_match.group(1))
            except Exception:
                continue
        return scores

    def _load_config(self):
        with open(os.path.join(self.workspace, "investment_criteria.yaml")) as f:
            criteria = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "scoring_config.json")) as f:
            scoring = json.load(f)
        return criteria, scoring

    def _compute_ground_truth(self):
        """Compute the full expected output using DB + workspace files."""
        criteria, scoring = self._load_config()
        strategic_scores = self._extract_strategic_scores()

        elig = criteria["eligibility"]
        weights = scoring["weights"]
        norm = scoring["normalization"]
        tiers_cfg = criteria["tier_thresholds"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # All companies
        companies = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM companies ORDER BY company_id"
            ).fetchall()
        ]

        results = []
        for c in companies:
            cid = c["company_id"]

            # --- Eligibility checks ---
            if c["stage"] not in elig["allowed_stages"]:
                continue

            # Financials: last 3 months
            fins = [
                dict(r)
                for r in conn.execute(
                    "SELECT month, revenue, expenses, burn_rate "
                    "FROM monthly_financials WHERE company_id = ? ORDER BY month",
                    (cid,),
                ).fetchall()
            ]
            if len(fins) < 4:
                continue

            last3 = fins[-3:]
            last4 = fins[-4:]

            avg_rev_last3 = sum(f["revenue"] for f in last3) / 3.0
            if avg_rev_last3 < elig["min_avg_monthly_revenue"]:
                continue

            # Cap table: founder ownership
            cap_rows = conn.execute(
                "SELECT shareholder_type, ownership_pct FROM cap_table "
                "WHERE company_id = ?",
                (cid,),
            ).fetchall()
            founder_own = sum(
                r["ownership_pct"]
                for r in cap_rows
                if r["shareholder_type"] in ("Founder", "Co-Founder")
            )
            if founder_own < elig["min_founder_ownership_pct"]:
                continue

            # Sentiments
            sents = conn.execute(
                "SELECT sentiment_score FROM partner_sentiments WHERE company_id = ?",
                (cid,),
            ).fetchall()
            if not sents:
                continue
            avg_sent = sum(r["sentiment_score"] for r in sents) / len(sents)
            if avg_sent < elig["min_avg_partner_sentiment"]:
                continue

            # Strategic fit
            if cid not in strategic_scores:
                continue
            sf_val = strategic_scores[cid]

            # --- Compute factor scores ---
            # Revenue growth (last 3 transitions)
            growth_rates = []
            for i in range(1, 4):
                prev_rev = last4[i - 1]["revenue"]
                cur_rev = last4[i]["revenue"]
                if prev_rev > 0:
                    growth_rates.append((cur_rev - prev_rev) / prev_rev * 100.0)
                else:
                    growth_rates.append(0.0)
            avg_growth = sum(growth_rates) / len(growth_rates)

            rev_score = min(100.0, max(0.0, avg_growth / norm["max_revenue_growth_pct"] * 100.0))

            # Burn efficiency
            burn_multiples = []
            for f in last3:
                if f["revenue"] > 0:
                    burn_multiples.append(f["burn_rate"] / f["revenue"])
                else:
                    burn_multiples.append(norm["max_burn_multiple"])
            avg_bm = sum(burn_multiples) / len(burn_multiples)
            burn_score = min(100.0, max(0.0, (1.0 - avg_bm / norm["max_burn_multiple"]) * 100.0))

            # Dilution health
            dil_score = min(100.0, founder_own / norm["benchmark_founder_ownership_pct"] * 100.0)

            # Competitive position
            total_comp = conn.execute(
                "SELECT COALESCE(SUM(amount_raised), 0) FROM competitor_funding WHERE sector = ?",
                (c["sector"],),
            ).fetchone()[0]
            comp_score = min(100.0, max(0.0, (1.0 - total_comp / norm["max_sector_competitor_funding"]) * 100.0))

            # Partner sentiment
            sent_score = min(100.0, avg_sent / 10.0 * 100.0)

            # Strategic fit
            sf_score = min(100.0, sf_val / 10.0 * 100.0)

            composite = (
                weights["revenue_growth"] * rev_score
                + weights["burn_efficiency"] * burn_score
                + weights["dilution_health"] * dil_score
                + weights["competitive_position"] * comp_score
                + weights["partner_sentiment"] * sent_score
                + weights["strategic_fit"] * sf_score
            )
            composite = round(composite, 2)

            if composite >= tiers_cfg["high_priority_min"]:
                tier = "High Priority"
            elif composite >= tiers_cfg["medium_priority_min"]:
                tier = "Medium Priority"
            else:
                tier = "Monitor"

            results.append({
                "company_name": c["name"],
                "composite_score": composite,
                "recommendation_tier": tier,
                "revenue_growth_pct": round(avg_growth, 2),
                "burn_multiple": round(avg_bm, 2),
                "founder_ownership_pct": round(founder_own, 2),
                "avg_partner_sentiment": round(avg_sent, 2),
                "strategic_fit_score": sf_val,
                "sector": c["sector"],
            })

        conn.close()

        # Sort: composite desc, then name asc
        results.sort(key=lambda r: (-r["composite_score"], r["company_name"]))
        for i, r in enumerate(results, 1):
            r["rank"] = i

        return results

    # ================================================================== #
    #  STEP                                                               #
    # ================================================================== #

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
        criteria_results = {}

        # ---- Criterion 1: File existence & columns (10 pts) ---- #
        csv_path = os.path.join(self.workspace, "prioritized_outreach.csv")
        required_cols = [
            "rank", "company_name", "composite_score", "recommendation_tier",
            "revenue_growth_pct", "burn_multiple", "founder_ownership_pct",
            "avg_partner_sentiment", "strategic_fit_score", "sector",
        ]
        agent_rows = []
        file_ok = False
        cols_ok = False
        if os.path.isfile(csv_path):
            file_ok = True
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    if all(c in actual_cols for c in required_cols):
                        cols_ok = True
                    for row in reader:
                        row = {k.strip(): v.strip() for k, v in row.items()}
                        agent_rows.append(row)
            except Exception:
                pass

        c1_score = 0
        if file_ok:
            c1_score += 5
        if cols_ok:
            c1_score += 5
        criteria_results["file_structure"] = {
            "passed": c1_score == 10,
            "score": c1_score,
            "max_score": 10,
            "reason": "" if c1_score == 10 else "Missing file or incorrect columns.",
        }

        # ---- Criterion 2: Eligible companies completeness (20 pts) ---- #
        expected_names = {r["company_name"] for r in expected}
        agent_names = {r.get("company_name", "") for r in agent_rows}
        if expected_names:
            present = expected_names & agent_names
            c2_score = round(len(present) / len(expected_names) * 20)
        else:
            c2_score = 20 if not agent_names else 0

        criteria_results["eligible_completeness"] = {
            "passed": c2_score == 20,
            "score": c2_score,
            "max_score": 20,
            "reason": "" if c2_score == 20 else f"Missing: {expected_names - agent_names}",
        }

        # ---- Criterion 3: No ineligible companies (10 pts) ---- #
        extra = agent_names - expected_names - {""}
        c3_score = 10 if not extra else max(0, 10 - len(extra) * 2)
        criteria_results["no_ineligible"] = {
            "passed": c3_score == 10,
            "score": c3_score,
            "max_score": 10,
            "reason": "" if c3_score == 10 else f"Extra companies: {extra}",
        }

        # ---- Criterion 4: Composite score accuracy (20 pts) ---- #
        expected_map = {r["company_name"]: r for r in expected}
        agent_map = {r.get("company_name", ""): r for r in agent_rows}
        score_correct = 0
        score_total = max(len(expected), 1)
        for name, exp_r in expected_map.items():
            ag = agent_map.get(name)
            if ag:
                try:
                    agent_cs = float(ag.get("composite_score", -1))
                    if abs(agent_cs - exp_r["composite_score"]) <= 0.5:
                        score_correct += 1
                except (ValueError, TypeError):
                    pass
        c4_score = round(score_correct / score_total * 20)
        criteria_results["score_accuracy"] = {
            "passed": c4_score == 20,
            "score": c4_score,
            "max_score": 20,
            "reason": "" if c4_score == 20 else f"{score_correct}/{score_total} scores within tolerance.",
        }

        # ---- Criterion 5: Ranking order (15 pts) ---- #
        expected_order = [r["company_name"] for r in expected]
        agent_order = [r.get("company_name", "") for r in agent_rows]
        # Check pairwise ordering
        if len(expected_order) <= 1:
            c5_score = 15
        else:
            correct_pairs = 0
            total_pairs = 0
            for i in range(len(expected_order)):
                for j in range(i + 1, len(expected_order)):
                    if expected_order[i] in agent_order and expected_order[j] in agent_order:
                        total_pairs += 1
                        idx_i = agent_order.index(expected_order[i])
                        idx_j = agent_order.index(expected_order[j])
                        if idx_i < idx_j:
                            correct_pairs += 1
            c5_score = round(correct_pairs / max(total_pairs, 1) * 15)

        criteria_results["ranking_order"] = {
            "passed": c5_score == 15,
            "score": c5_score,
            "max_score": 15,
            "reason": "" if c5_score == 15 else "Ranking order does not match expected.",
        }

        # ---- Criterion 6: Tier assignments (15 pts) ---- #
        tier_correct = 0
        tier_total = max(len(expected), 1)
        for name, exp_r in expected_map.items():
            ag = agent_map.get(name)
            if ag and ag.get("recommendation_tier", "").strip() == exp_r["recommendation_tier"]:
                tier_correct += 1
        c6_score = round(tier_correct / tier_total * 15)
        criteria_results["tier_assignment"] = {
            "passed": c6_score == 15,
            "score": c6_score,
            "max_score": 15,
            "reason": "" if c6_score == 15 else f"{tier_correct}/{tier_total} tiers correct.",
        }

        # ---- Criterion 7: Response summary (10 pts) ---- #
        high_priority = [r["company_name"] for r in expected if r["recommendation_tier"] == "High Priority"]
        if not high_priority:
            # If no high priority, check top 3
            high_priority = [r["company_name"] for r in expected[:3]]
        mentioned = sum(1 for name in high_priority if name in action)
        if high_priority:
            c7_score = round(mentioned / len(high_priority) * 10)
        else:
            c7_score = 10
        criteria_results["response_summary"] = {
            "passed": c7_score == 10,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_score == 10 else f"Only {mentioned}/{len(high_priority)} key companies mentioned in response.",
        }

        total_score = sum(v["score"] for v in criteria_results.values())
        max_score = sum(v["max_score"] for v in criteria_results.values())

        return total_score / max_score, {
            "eval_criteria": criteria_results,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ================================================================== #
    #  VERIFY                                                             #
    # ================================================================== #

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
        # --- Load config from workspace ---
        with open(os.path.join(self.workspace, "investment_criteria.yaml")) as f:
            criteria = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "scoring_config.json")) as f:
            scoring = json.load(f)

        elig = criteria["eligibility"]
        weights = scoring["weights"]
        norm = scoring["normalization"]
        tiers_cfg = criteria["tier_thresholds"]

        # --- Extract strategic fit scores from workspace files ---
        strategic_scores = self._extract_strategic_scores()

        # --- Gather all companies via tools ---
        all_companies = []
        page = 1
        while True:
            result = self.tools["list_portfolio_companies"](page=page, page_size=10)
            all_companies.extend(result["companies"])
            if page * 10 >= result["total"]:
                break
            page += 1

        # --- Gather details for each company ---
        company_data = {}
        for comp in all_companies:
            cid = comp["company_id"]
            info = self.tools["get_company_info"](company_id=cid)
            fins = self.tools["get_company_financials"](company_id=cid)
            cap = self.tools["get_cap_table"](company_id=cid)
            sents = self.tools["get_partner_sentiments"](company_id=cid)
            company_data[cid] = {
                "info": info,
                "financials": fins["financials"],
                "cap_table": cap["shareholders"],
                "sentiments": sents["sentiments"],
            }

        # --- Gather competitor funding per sector ---
        sectors_seen = set()
        for cid, cd in company_data.items():
            sectors_seen.add(cd["info"]["sector"])

        sector_funding = {}
        for sector in sectors_seen:
            total_funding = 0.0
            page = 1
            while True:
                result = self.tools["get_competitor_funding"](
                    sector=sector, page=page, page_size=100
                )
                for r in result["rounds"]:
                    total_funding += r["amount_raised"]
                if page * 100 >= result["total"]:
                    break
                page += 1
            sector_funding[sector] = total_funding

        # --- Score each company ---
        results = []
        for cid, cd in company_data.items():
            info = cd["info"]

            # Eligibility: stage
            if info["stage"] not in elig["allowed_stages"]:
                continue

            fins = cd["financials"]
            if len(fins) < 4:
                continue

            last3 = fins[-3:]
            last4 = fins[-4:]

            # Eligibility: avg revenue last 3 months
            avg_rev = sum(f["revenue"] for f in last3) / 3.0
            if avg_rev < elig["min_avg_monthly_revenue"]:
                continue

            # Eligibility: founder ownership
            founder_own = sum(
                sh["ownership_pct"]
                for sh in cd["cap_table"]
                if sh["shareholder_type"] in ("Founder", "Co-Founder")
            )
            if founder_own < elig["min_founder_ownership_pct"]:
                continue

            # Eligibility: partner sentiment
            sent_vals = [s["sentiment_score"] for s in cd["sentiments"]]
            if not sent_vals:
                continue
            avg_sent = sum(sent_vals) / len(sent_vals)
            if avg_sent < elig["min_avg_partner_sentiment"]:
                continue

            # Strategic fit
            if cid not in strategic_scores:
                continue
            sf_val = strategic_scores[cid]

            # Revenue growth score
            growth_rates = []
            for i in range(1, 4):
                prev_rev = last4[i - 1]["revenue"]
                cur_rev = last4[i]["revenue"]
                if prev_rev > 0:
                    growth_rates.append((cur_rev - prev_rev) / prev_rev * 100.0)
                else:
                    growth_rates.append(0.0)
            avg_growth = sum(growth_rates) / len(growth_rates)
            rev_score = min(100.0, max(0.0, avg_growth / norm["max_revenue_growth_pct"] * 100.0))

            # Burn efficiency score
            burn_multiples = []
            for f in last3:
                if f["revenue"] > 0:
                    burn_multiples.append(f["burn_rate"] / f["revenue"])
                else:
                    burn_multiples.append(norm["max_burn_multiple"])
            avg_bm = sum(burn_multiples) / len(burn_multiples)
            burn_score = min(100.0, max(0.0, (1.0 - avg_bm / norm["max_burn_multiple"]) * 100.0))

            # Dilution health score
            dil_score = min(100.0, founder_own / norm["benchmark_founder_ownership_pct"] * 100.0)

            # Competitive position score
            total_comp = sector_funding.get(info["sector"], 0.0)
            comp_score = min(100.0, max(0.0, (1.0 - total_comp / norm["max_sector_competitor_funding"]) * 100.0))

            # Partner sentiment score
            sent_score = min(100.0, avg_sent / 10.0 * 100.0)

            # Strategic fit score
            sf_score = min(100.0, sf_val / 10.0 * 100.0)

            composite = (
                weights["revenue_growth"] * rev_score
                + weights["burn_efficiency"] * burn_score
                + weights["dilution_health"] * dil_score
                + weights["competitive_position"] * comp_score
                + weights["partner_sentiment"] * sent_score
                + weights["strategic_fit"] * sf_score
            )
            composite = round(composite, 2)

            if composite >= tiers_cfg["high_priority_min"]:
                tier = "High Priority"
            elif composite >= tiers_cfg["medium_priority_min"]:
                tier = "Medium Priority"
            else:
                tier = "Monitor"

            results.append({
                "company_name": info["name"],
                "composite_score": composite,
                "recommendation_tier": tier,
                "revenue_growth_pct": round(avg_growth, 2),
                "burn_multiple": round(avg_bm, 2),
                "founder_ownership_pct": round(founder_own, 2),
                "avg_partner_sentiment": round(avg_sent, 2),
                "strategic_fit_score": sf_val,
                "sector": info["sector"],
            })

        # Sort: composite desc, name asc
        results.sort(key=lambda r: (-r["composite_score"], r["company_name"]))
        for i, r in enumerate(results, 1):
            r["rank"] = i

        # --- Write deliverable ---
        out_path = os.path.join(self.workspace, "prioritized_outreach.csv")
        fieldnames = [
            "rank", "company_name", "composite_score", "recommendation_tier",
            "revenue_growth_pct", "burn_multiple", "founder_ownership_pct",
            "avg_partner_sentiment", "strategic_fit_score", "sector",
        ]
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({k: r[k] for k in fieldnames})

        # --- Construct response ---
        high_priority = [r for r in results if r["recommendation_tier"] == "High Priority"]
        if not high_priority:
            top = results[:3]
        else:
            top = high_priority

        lines = ["Follow-on investment outreach analysis complete.\n"]
        lines.append(f"Total eligible companies: {len(results)}\n")
        lines.append("Key recommendations:\n")
        for r in top:
            lines.append(
                f"- {r['company_name']} (composite: {r['composite_score']}, "
                f"tier: {r['recommendation_tier']}, sector: {r['sector']})"
            )
        lines.append(
            "\nThe full prioritized outreach list has been saved to prioritized_outreach.csv."
        )
        action = "\n".join(lines)

        return self.step(action)
