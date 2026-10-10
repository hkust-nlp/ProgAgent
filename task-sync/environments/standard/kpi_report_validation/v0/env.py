import sqlite3
import json
import os
import csv
import re
import math
import yaml
from typing import Tuple, Dict, List, Any


# --- Decorator for tool registration ---
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---- Severity classification helpers (pure computation, no DB access) ----

def classify_severity(submitted, reference, tol_type, tol_value, mat_threshold, fund, escalation_funds):
    """Return severity string or None if within tolerance."""
    if reference == 0:
        if submitted == 0:
            return None
        disc_abs = abs(submitted)
        disc_ratio = float("inf")
    else:
        disc_abs = abs(submitted - reference)
        if tol_type == "relative":
            disc_ratio = disc_abs / abs(reference)
        else:
            disc_ratio = disc_abs

    if disc_ratio <= tol_value:
        return None

    multiplier = disc_ratio / tol_value if tol_value > 0 else float("inf")
    exceeds_materiality = disc_abs > mat_threshold

    if multiplier > 3 and exceeds_materiality:
        severity = "CRITICAL"
    elif multiplier > 3 or exceeds_materiality:
        severity = "HIGH"
    elif multiplier > 2:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    if fund in escalation_funds and severity == "MEDIUM":
        severity = "HIGH"

    return severity


def classify_qoq_severity(growth_rate, growth_cap, abs_change, mat_threshold, fund, escalation_funds):
    """Return severity for a QoQ anomaly, or None if within cap."""
    if growth_rate <= growth_cap:
        return None

    multiplier = growth_rate / growth_cap if growth_cap > 0 else float("inf")
    exceeds_materiality = abs_change > mat_threshold

    if multiplier > 3 and exceeds_materiality:
        severity = "CRITICAL"
    elif multiplier > 3 or exceeds_materiality:
        severity = "HIGH"
    elif multiplier > 2:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    if fund in escalation_funds and severity == "MEDIUM":
        severity = "HIGH"

    return severity


def _parse_escalation_funds(fund_policy_text):
    """Extract set of fund names that escalate MEDIUM -> HIGH."""
    escalation_funds = set()
    # Match longest fund names first so 'Fund III'/'Fund IV' don't get
    # mis-detected as 'Fund I'/'Fund II' substrings.
    fund_names = ["Fund III", "Fund IV", "Fund II", "Fund I"]
    for line in fund_policy_text.split("\n"):
        if "escalated to HIGH" not in line:
            continue
        remaining = line
        for fn in fund_names:
            if fn in remaining:
                escalation_funds.add(fn)
                remaining = remaining.replace(fn, "")
    return escalation_funds


def _load_configs(workspace):
    """Load all workspace config files. Returns (rules, mat_thresholds, escalation_funds)."""
    with open(os.path.join(workspace, "validation_rules.yaml")) as f:
        rules = yaml.safe_load(f)

    mat_thresholds = {}
    with open(os.path.join(workspace, "materiality_thresholds.csv")) as f:
        reader = csv.DictReader(f)
        for row in reader:
            sector = row["sector"]
            mat_thresholds[sector] = {}
            for k, v in row.items():
                if k != "sector":
                    try:
                        mat_thresholds[sector][k] = float(v)
                    except (ValueError, TypeError):
                        mat_thresholds[sector][k] = 0.0

    with open(os.path.join(workspace, "fund_review_policy.txt")) as f:
        escalation_funds = _parse_escalation_funds(f.read())

    return rules, mat_thresholds, escalation_funds


def _prev_quarter(quarter):
    """Given 'Q4-2025' return 'Q3-2025'; given 'Q1-2025' return 'Q4-2024'."""
    q_num = int(quarter.split("-")[0][1])
    q_year = int(quarter.split("-")[1])
    if q_num == 1:
        return f"Q4-{q_year - 1}"
    return f"Q{q_num - 1}-{q_year}"


SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


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
        description="List portfolio companies with optional filtering. Returns paginated results.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed). Defaults to 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of companies per page. Defaults to 5.",
                },
                "sector": {
                    "type": "string",
                    "description": "Optional sector filter (e.g., 'FinTech').",
                },
                "fund": {
                    "type": "string",
                    "description": "Optional fund filter (e.g., 'Fund II').",
                },
            },
            "required": [],
        },
    )
    def list_portfolio_companies(self, page=1, page_size=5, sector=None, fund=None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        page = int(page)
        page_size = int(page_size)

        query = "SELECT company_id, name, sector, fund, stage FROM companies WHERE 1=1"
        params = []
        if sector:
            query += " AND sector = ?"
            params.append(sector)
        if fund:
            query += " AND fund = ?"
            params.append(fund)

        count_q = query.replace(
            "SELECT company_id, name, sector, fund, stage",
            "SELECT COUNT(*)",
        )
        total = conn.execute(count_q, params).fetchone()[0]

        query += " ORDER BY company_id LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = conn.execute(query, params).fetchall()
        conn.close()

        companies = [
            {
                "company_id": r["company_id"],
                "name": r["name"],
                "sector": r["sector"],
                "fund": r["fund"],
                "stage": r["stage"],
            }
            for r in rows
        ]
        total_pages = max(1, math.ceil(total / page_size))
        return {
            "companies": companies,
            "page": page,
            "page_size": page_size,
            "total_companies": total,
            "total_pages": total_pages,
        }

    @tool(
        description="Get detailed information for a specific portfolio company, including board seat partner and investment date.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique company identifier.",
                },
            },
            "required": ["company_id"],
        },
    )
    def get_company_details(self, company_id):
        company_id = int(company_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM companies WHERE company_id = ?", (company_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Company {company_id} not found"}
        return {
            "company_id": row["company_id"],
            "name": row["name"],
            "sector": row["sector"],
            "fund": row["fund"],
            "stage": row["stage"],
            "board_seat_partner": row["board_seat_partner"],
            "investment_date": row["investment_date"],
        }

    @tool(
        description="Retrieve SaaS monitoring platform metrics for a portfolio company in a given quarter.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique company identifier.",
                },
                "quarter": {
                    "type": "string",
                    "description": "Quarter in format 'Q4-2025'.",
                },
            },
            "required": ["company_id", "quarter"],
        },
    )
    def get_saas_platform_metrics(self, company_id, quarter):
        company_id = int(company_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT metric_name, value FROM saas_metrics WHERE company_id = ? AND quarter = ?",
            (company_id, quarter),
        ).fetchall()
        conn.close()
        if not rows:
            return {"error": f"No SaaS metrics found for company {company_id} in {quarter}"}
        metrics = {r["metric_name"]: r["value"] for r in rows}
        return {"company_id": company_id, "quarter": quarter, "metrics": metrics}

    @tool(
        description="Retrieve signed board deck figures for a portfolio company in a given quarter, including signoff details.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique company identifier.",
                },
                "quarter": {
                    "type": "string",
                    "description": "Quarter in format 'Q4-2025'.",
                },
            },
            "required": ["company_id", "quarter"],
        },
    )
    def get_board_deck_figures(self, company_id, quarter):
        company_id = int(company_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT metric_name, value, signoff_partner, signoff_date FROM board_deck_figures WHERE company_id = ? AND quarter = ?",
            (company_id, quarter),
        ).fetchall()
        conn.close()
        if not rows:
            return {"error": f"No board deck figures for company {company_id} in {quarter}"}
        metrics = {r["metric_name"]: r["value"] for r in rows}
        return {
            "company_id": company_id,
            "quarter": quarter,
            "metrics": metrics,
            "signoff_partner": rows[0]["signoff_partner"],
            "signoff_date": rows[0]["signoff_date"],
        }

    @tool(
        description="Retrieve the validated baseline metrics from a previous quarter for a portfolio company.",
        parameters={
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "integer",
                    "description": "The unique company identifier.",
                },
                "quarter": {
                    "type": "string",
                    "description": "The previous quarter to look up, e.g. 'Q3-2025'.",
                },
            },
            "required": ["company_id", "quarter"],
        },
    )
    def get_previous_quarter_baseline(self, company_id, quarter):
        company_id = int(company_id)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT metric_name, value, validated FROM previous_reports WHERE company_id = ? AND quarter = ?",
            (company_id, quarter),
        ).fetchall()
        conn.close()
        if not rows:
            return {"error": f"No baseline for company {company_id} in {quarter}"}
        metrics = {r["metric_name"]: r["value"] for r in rows if r["validated"]}
        return {"company_id": company_id, "quarter": quarter, "metrics": metrics}

    # ================================================================
    # Internal ground-truth computation (used by step only)
    # ================================================================

    def _compute_expected_exceptions(self):
        """Recompute all expected exceptions from DB + workspace files."""
        rules, mat_thresholds, escalation_funds = _load_configs(self.workspace)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Read submissions manifest
        manifest_path = os.path.join(self.workspace, "submissions_manifest.csv")
        submissions = []
        with open(manifest_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                submissions.append(row)

        exceptions = []

        for sub in submissions:
            cid = int(sub["company_id"])
            company_name = sub["company_name"]

            # Read submission file
            sub_path = os.path.join(self.workspace, sub["submission_file"])
            with open(sub_path) as f:
                sub_data = json.load(f)

            quarter = sub_data["quarter"]

            # Company info
            crow = conn.execute(
                "SELECT sector, fund FROM companies WHERE company_id = ?", (cid,)
            ).fetchone()
            sector = crow["sector"]
            fund = crow["fund"]

            # SaaS metrics
            saas = {}
            for r in conn.execute(
                "SELECT metric_name, value FROM saas_metrics WHERE company_id = ? AND quarter = ?",
                (cid, quarter),
            ):
                saas[r["metric_name"]] = r["value"]

            # Board deck
            board = {}
            for r in conn.execute(
                "SELECT metric_name, value FROM board_deck_figures WHERE company_id = ? AND quarter = ?",
                (cid, quarter),
            ):
                board[r["metric_name"]] = r["value"]

            # Previous quarter
            prev_q = _prev_quarter(quarter)
            prev = {}
            for r in conn.execute(
                "SELECT metric_name, value FROM previous_reports WHERE company_id = ? AND quarter = ? AND validated = 1",
                (cid, prev_q),
            ):
                prev[r["metric_name"]] = r["value"]

            for metric, submitted_val in sub_data["metrics"].items():
                tol_info = rules["tolerances"].get(metric)
                if not tol_info:
                    continue
                tol_type = tol_info["type"]
                tol_value = float(tol_info["value"])
                mat_val = float(mat_thresholds.get(sector, {}).get(metric, 1e18))

                # vs SaaS
                if metric in saas:
                    ref_val = saas[metric]
                    sev = classify_severity(
                        submitted_val, ref_val, tol_type, tol_value, mat_val, fund, escalation_funds
                    )
                    if sev:
                        disc_pct = (
                            abs(submitted_val - ref_val) / abs(ref_val) * 100
                            if ref_val != 0
                            else (100.0 if submitted_val != 0 else 0.0)
                        )
                        exceptions.append({
                            "company_id": cid,
                            "company_name": company_name,
                            "metric_name": metric,
                            "submitted_value": submitted_val,
                            "reference_source": "saas_platform",
                            "reference_value": ref_val,
                            "discrepancy_pct": round(disc_pct, 2),
                            "severity": sev,
                        })

                # vs board deck
                if metric in board:
                    ref_val = board[metric]
                    sev = classify_severity(
                        submitted_val, ref_val, tol_type, tol_value, mat_val, fund, escalation_funds
                    )
                    if sev:
                        disc_pct = (
                            abs(submitted_val - ref_val) / abs(ref_val) * 100
                            if ref_val != 0
                            else (100.0 if submitted_val != 0 else 0.0)
                        )
                        exceptions.append({
                            "company_id": cid,
                            "company_name": company_name,
                            "metric_name": metric,
                            "submitted_value": submitted_val,
                            "reference_source": "board_deck",
                            "reference_value": ref_val,
                            "discrepancy_pct": round(disc_pct, 2),
                            "severity": sev,
                        })

                # QoQ growth check
                growth_cap = rules.get("qoq_growth_caps", {}).get(metric)
                if growth_cap is not None and metric in prev:
                    prev_val = prev[metric]
                    if prev_val != 0:
                        growth = abs(submitted_val - prev_val) / abs(prev_val)
                        if growth > float(growth_cap):
                            abs_change = abs(submitted_val - prev_val)
                            sev = classify_qoq_severity(
                                growth, float(growth_cap), abs_change, mat_val, fund, escalation_funds
                            )
                            if sev:
                                exceptions.append({
                                    "company_id": cid,
                                    "company_name": company_name,
                                    "metric_name": metric,
                                    "submitted_value": submitted_val,
                                    "reference_source": "qoq_baseline",
                                    "reference_value": prev_val,
                                    "discrepancy_pct": round(growth * 100, 2),
                                    "severity": sev,
                                })

        conn.close()

        exceptions.sort(
            key=lambda x: (
                SEVERITY_ORDER.get(x["severity"], 99),
                x["company_name"],
                x["metric_name"],
                x["reference_source"],
            )
        )
        return exceptions

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
        expected = self._compute_expected_exceptions()

        eval_criteria = {}
        total_score = 0.0
        max_score = 0.0

        # ---- Criterion 1: File format (10 pts) ----
        max_score += 10
        expected_cols = [
            "company_id", "company_name", "metric_name", "submitted_value",
            "reference_source", "reference_value", "discrepancy_pct", "severity",
        ]
        report_path = os.path.join(self.workspace, "exception_report.csv")
        agent_exceptions = []
        file_score = 0

        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    header_line = f.readline().strip()
                header_fields = [h.strip() for h in header_line.split(",")]

                with open(report_path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        agent_exceptions.append(row)

                if header_fields == expected_cols:
                    file_score = 10
                elif set(expected_cols).issubset(set(header_fields)):
                    file_score = 5
            except Exception:
                pass

        eval_criteria["file_format"] = {
            "passed": file_score == 10,
            "score": file_score,
            "max_score": 10,
        }
        if file_score < 10:
            eval_criteria["file_format"]["reason"] = (
                "File missing or columns wrong" if file_score == 0 else "Column order incorrect"
            )
        total_score += file_score

        # Build lookup dicts
        expected_keys = {}
        for e in expected:
            key = (int(e["company_id"]), e["metric_name"].lower(), e["reference_source"].lower())
            expected_keys[key] = e

        agent_keys = {}
        for a in agent_exceptions:
            try:
                key = (
                    int(a.get("company_id", -1)),
                    a.get("metric_name", "").strip().lower(),
                    a.get("reference_source", "").strip().lower(),
                )
                agent_keys[key] = a
            except (ValueError, TypeError):
                continue

        # ---- Criterion 2: Board-deck discrepancy recall (20 pts) ----
        max_score += 20
        bd_expected = {k: v for k, v in expected_keys.items() if k[2] == "board_deck"}
        bd_found = sum(1 for k in bd_expected if k in agent_keys)
        bd_total = len(bd_expected)
        bd_score = round(bd_found / bd_total * 20, 2) if bd_total > 0 else 20.0
        eval_criteria["board_deck_recall"] = {
            "passed": bd_found == bd_total,
            "score": bd_score,
            "max_score": 20,
        }
        if bd_found != bd_total:
            eval_criteria["board_deck_recall"]["reason"] = f"Found {bd_found}/{bd_total}"
        total_score += bd_score

        # ---- Criterion 3: SaaS-platform discrepancy recall (20 pts) ----
        max_score += 20
        saas_expected = {k: v for k, v in expected_keys.items() if k[2] == "saas_platform"}
        saas_found = sum(1 for k in saas_expected if k in agent_keys)
        saas_total = len(saas_expected)
        saas_score = round(saas_found / saas_total * 20, 2) if saas_total > 0 else 20.0
        eval_criteria["saas_platform_recall"] = {
            "passed": saas_found == saas_total,
            "score": saas_score,
            "max_score": 20,
        }
        if saas_found != saas_total:
            eval_criteria["saas_platform_recall"]["reason"] = f"Found {saas_found}/{saas_total}"
        total_score += saas_score

        # ---- Criterion 4: QoQ anomaly recall (15 pts) ----
        max_score += 15
        qoq_expected = {k: v for k, v in expected_keys.items() if k[2] == "qoq_baseline"}
        qoq_found = sum(1 for k in qoq_expected if k in agent_keys)
        qoq_total = len(qoq_expected)
        qoq_score = round(qoq_found / qoq_total * 15, 2) if qoq_total > 0 else 15.0
        eval_criteria["qoq_anomaly_recall"] = {
            "passed": qoq_found == qoq_total,
            "score": qoq_score,
            "max_score": 15,
        }
        if qoq_found != qoq_total:
            eval_criteria["qoq_anomaly_recall"]["reason"] = f"Found {qoq_found}/{qoq_total}"
        total_score += qoq_score

        # ---- Criterion 5: Severity accuracy (15 pts) ----
        max_score += 15
        matched_keys = set(expected_keys.keys()) & set(agent_keys.keys())
        sev_correct = 0
        for k in matched_keys:
            agent_sev = agent_keys[k].get("severity", "").strip().upper()
            if agent_sev == expected_keys[k]["severity"]:
                sev_correct += 1
        sev_total = len(matched_keys)
        sev_score = round(sev_correct / sev_total * 15, 2) if sev_total > 0 else 0.0
        eval_criteria["severity_accuracy"] = {
            "passed": sev_correct == sev_total,
            "score": sev_score,
            "max_score": 15,
        }
        if sev_correct != sev_total:
            eval_criteria["severity_accuracy"]["reason"] = f"Correct {sev_correct}/{sev_total}"
        total_score += sev_score

        # ---- Criterion 6: Precision — no false positives (10 pts) ----
        max_score += 10
        false_positives = len(set(agent_keys.keys()) - set(expected_keys.keys()))
        prec_score = max(0, 10 - 2 * false_positives)
        eval_criteria["precision"] = {
            "passed": false_positives == 0,
            "score": prec_score,
            "max_score": 10,
        }
        if false_positives > 0:
            eval_criteria["precision"]["reason"] = f"{false_positives} false positives"
        total_score += prec_score

        # ---- Criterion 7: Summary statistics in response (10 pts) ----
        max_score += 10
        expected_total = len(expected)
        expected_by_sev = {}
        for e in expected:
            s = e["severity"]
            expected_by_sev[s] = expected_by_sev.get(s, 0) + 1
        expected_companies = len(set(e["company_id"] for e in expected))

        summary_score = 0
        # Total exceptions
        total_match = re.search(r"[Tt]otal\s+exceptions[:\s]+(\d+)", action or "")
        if total_match and int(total_match.group(1)) == expected_total:
            summary_score += 4

        # Severity breakdown
        sev_ok = 0
        for sev_name in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            pat = re.search(rf"{sev_name}[:\s]+(\d+)", action or "", re.IGNORECASE)
            if pat and int(pat.group(1)) == expected_by_sev.get(sev_name, 0):
                sev_ok += 1
        if sev_ok == 4:
            summary_score += 4
        elif sev_ok >= 2:
            summary_score += 2

        # Companies with exceptions
        comp_match = re.search(r"[Cc]ompanies\s+with\s+exceptions[:\s]+(\d+)", action or "")
        if comp_match and int(comp_match.group(1)) == expected_companies:
            summary_score += 2

        eval_criteria["summary_statistics"] = {
            "passed": summary_score == 10,
            "score": summary_score,
            "max_score": 10,
        }
        if summary_score < 10:
            eval_criteria["summary_statistics"]["reason"] = "Partial or missing summary data"
        total_score += summary_score

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

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
        # ---- Load workspace configs ----
        rules, mat_thresholds, escalation_funds = _load_configs(self.workspace)

        # ---- Discover all companies via tool (paginated) ----
        all_companies = {}
        page = 1
        while True:
            result = self.tools["list_portfolio_companies"](page=page, page_size=5)
            for c in result["companies"]:
                all_companies[c["company_id"]] = c
            if page >= result["total_pages"]:
                break
            page += 1

        # ---- Read submissions manifest ----
        manifest_path = os.path.join(self.workspace, "submissions_manifest.csv")
        submissions = []
        with open(manifest_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                submissions.append(row)

        exceptions = []

        for sub in submissions:
            cid = int(sub["company_id"])
            company_name = sub["company_name"]

            # Read submission file
            with open(os.path.join(self.workspace, sub["submission_file"])) as f:
                sub_data = json.load(f)

            quarter = sub_data["quarter"]
            prev_q = _prev_quarter(quarter)

            # Get company details via tool
            company_info = self.tools["get_company_details"](company_id=cid)
            sector = company_info["sector"]
            fund = company_info["fund"]

            # Get reference data via tools
            saas_result = self.tools["get_saas_platform_metrics"](company_id=cid, quarter=quarter)
            board_result = self.tools["get_board_deck_figures"](company_id=cid, quarter=quarter)
            prev_result = self.tools["get_previous_quarter_baseline"](company_id=cid, quarter=prev_q)

            saas_m = saas_result.get("metrics", {})
            board_m = board_result.get("metrics", {})
            prev_m = prev_result.get("metrics", {})

            for metric, submitted_val in sub_data["metrics"].items():
                tol_info = rules["tolerances"].get(metric)
                if not tol_info:
                    continue
                tol_type = tol_info["type"]
                tol_value = float(tol_info["value"])
                mat_val = float(mat_thresholds.get(sector, {}).get(metric, 1e18))

                # vs SaaS
                if metric in saas_m:
                    ref_val = saas_m[metric]
                    sev = classify_severity(
                        submitted_val, ref_val, tol_type, tol_value, mat_val, fund, escalation_funds
                    )
                    if sev:
                        disc_pct = (
                            abs(submitted_val - ref_val) / abs(ref_val) * 100
                            if ref_val != 0 else 0.0
                        )
                        exceptions.append({
                            "company_id": cid,
                            "company_name": company_name,
                            "metric_name": metric,
                            "submitted_value": submitted_val,
                            "reference_source": "saas_platform",
                            "reference_value": ref_val,
                            "discrepancy_pct": round(disc_pct, 2),
                            "severity": sev,
                        })

                # vs board deck
                if metric in board_m:
                    ref_val = board_m[metric]
                    sev = classify_severity(
                        submitted_val, ref_val, tol_type, tol_value, mat_val, fund, escalation_funds
                    )
                    if sev:
                        disc_pct = (
                            abs(submitted_val - ref_val) / abs(ref_val) * 100
                            if ref_val != 0 else 0.0
                        )
                        exceptions.append({
                            "company_id": cid,
                            "company_name": company_name,
                            "metric_name": metric,
                            "submitted_value": submitted_val,
                            "reference_source": "board_deck",
                            "reference_value": ref_val,
                            "discrepancy_pct": round(disc_pct, 2),
                            "severity": sev,
                        })

                # QoQ growth check
                growth_cap = rules.get("qoq_growth_caps", {}).get(metric)
                if growth_cap is not None and metric in prev_m:
                    prev_val = prev_m[metric]
                    if prev_val != 0:
                        growth = abs(submitted_val - prev_val) / abs(prev_val)
                        if growth > float(growth_cap):
                            abs_change = abs(submitted_val - prev_val)
                            sev = classify_qoq_severity(
                                growth, float(growth_cap), abs_change, mat_val, fund, escalation_funds
                            )
                            if sev:
                                exceptions.append({
                                    "company_id": cid,
                                    "company_name": company_name,
                                    "metric_name": metric,
                                    "submitted_value": submitted_val,
                                    "reference_source": "qoq_baseline",
                                    "reference_value": prev_val,
                                    "discrepancy_pct": round(growth * 100, 2),
                                    "severity": sev,
                                })

        # ---- Sort ----
        exceptions.sort(
            key=lambda x: (
                SEVERITY_ORDER.get(x["severity"], 99),
                x["company_name"],
                x["metric_name"],
                x["reference_source"],
            )
        )

        # ---- Write exception report ----
        report_path = os.path.join(self.workspace, "exception_report.csv")
        fieldnames = [
            "company_id", "company_name", "metric_name", "submitted_value",
            "reference_source", "reference_value", "discrepancy_pct", "severity",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(exceptions)

        # ---- Build summary action string ----
        total = len(exceptions)
        by_severity = {}
        for e in exceptions:
            by_severity[e["severity"]] = by_severity.get(e["severity"], 0) + 1
        companies_with_exc = len(set(e["company_id"] for e in exceptions))

        lines = [f"Total exceptions: {total}"]
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            lines.append(f"{sev}: {by_severity.get(sev, 0)}")
        lines.append(f"Companies with exceptions: {companies_with_exc}")
        lines.append("Exception report saved as exception_report.csv")
        action = "\n".join(lines)

        return self.step(action)
