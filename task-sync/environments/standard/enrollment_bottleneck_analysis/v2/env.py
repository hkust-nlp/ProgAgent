import sqlite3
import os
import json
import csv
import yaml
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters
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

    # ========== Tool Methods ==========

    @tool(
        description="Lists clinical trial sites with basic information. Returns a paginated list of sites. Each page contains up to page_size results.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of sites per page (max 20)"
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["active", "paused", "closed"],
                    "description": "Optional filter by site status"
                }
            },
            "required": ["page", "page_size"]
        }
    )
    def list_sites(self, page: int, page_size: int, status_filter: str = None) -> dict:
        page_size = min(page_size, 20)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if status_filter:
            c.execute("SELECT COUNT(*) FROM sites WHERE status = ?", (status_filter,))
            total = c.fetchone()[0]
            offset = (page - 1) * page_size
            c.execute(
                "SELECT site_id, site_name, region, tier, status, therapeutic_area, study_start_date "
                "FROM sites WHERE status = ? ORDER BY site_id LIMIT ? OFFSET ?",
                (status_filter, page_size, offset)
            )
        else:
            c.execute("SELECT COUNT(*) FROM sites")
            total = c.fetchone()[0]
            offset = (page - 1) * page_size
            c.execute(
                "SELECT site_id, site_name, region, tier, status, therapeutic_area, study_start_date "
                "FROM sites ORDER BY site_id LIMIT ? OFFSET ?",
                (page_size, offset)
            )

        rows = [dict(r) for r in c.fetchall()]
        conn.close()

        total_pages = max(1, -(-total // page_size))  # ceil division
        return {
            "sites": rows,
            "page": page,
            "page_size": page_size,
            "total_sites": total,
            "total_pages": total_pages,
        }

    @tool(
        description="Returns screening outcome summary for a specific site, including total screened, total passed, total failed, and a breakdown of failure categories with counts.",
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site identifier (e.g. SITE_001)"
                }
            },
            "required": ["site_id"]
        }
    )
    def get_screening_summary(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM screening_logs WHERE site_id = ?", (site_id,))
        total = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM screening_logs WHERE site_id = ? AND outcome = 'pass'", (site_id,))
        passed = c.fetchone()[0]

        failed = total - passed

        c.execute(
            "SELECT failure_category, COUNT(*) FROM screening_logs "
            "WHERE site_id = ? AND outcome = 'fail' GROUP BY failure_category",
            (site_id,)
        )
        failure_breakdown = {row[0]: row[1] for row in c.fetchall()}
        conn.close()

        return {
            "site_id": site_id,
            "total_screened": total,
            "total_passed": passed,
            "total_failed": failed,
            "failure_breakdown": failure_breakdown,
        }

    @tool(
        description="Returns eligibility criteria results for a specific site, broken down by criterion code. For each criterion, provides the count of met, not_met results and the total assessments.",
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site identifier (e.g. SITE_001)"
                }
            },
            "required": ["site_id"]
        }
    )
    def get_eligibility_breakdown(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute(
            "SELECT criterion_code, result, COUNT(*) FROM eligibility_results "
            "WHERE site_id = ? GROUP BY criterion_code, result ORDER BY criterion_code",
            (site_id,)
        )

        criteria = {}
        for code, result, count in c.fetchall():
            if code not in criteria:
                criteria[code] = {"met": 0, "not_met": 0, "total": 0}
            criteria[code][result] = count
            criteria[code]["total"] += count

        conn.close()

        return {
            "site_id": site_id,
            "criteria": criteria,
        }

    @tool(
        description="Returns monthly enrollment history for a specific site, sorted by period. Each record includes the period (YYYY-MM), enrolled count, screened count, and dropout count.",
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site identifier (e.g. SITE_001)"
                }
            },
            "required": ["site_id"]
        }
    )
    def get_enrollment_history(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute(
            "SELECT period, enrolled_count, screened_count, dropout_count "
            "FROM enrollment_history WHERE site_id = ? ORDER BY period",
            (site_id,)
        )

        records = []
        for row in c.fetchall():
            records.append({
                "period": row[0],
                "enrolled_count": row[1],
                "screened_count": row[2],
                "dropout_count": row[3],
            })

        conn.close()

        return {
            "site_id": site_id,
            "history": records,
        }

    @tool(
        description="Returns investigator details for a specific site, including each investigator's ID, name, role, maximum and current weekly hours, and certification expiry date.",
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site identifier (e.g. SITE_001)"
                }
            },
            "required": ["site_id"]
        }
    )
    def get_site_investigators(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute(
            "SELECT investigator_id, name, role, max_weekly_hours, current_weekly_hours, certification_expiry "
            "FROM investigators WHERE site_id = ? ORDER BY investigator_id",
            (site_id,)
        )

        investigators = []
        for row in c.fetchall():
            investigators.append({
                "investigator_id": row[0],
                "name": row[1],
                "role": row[2],
                "max_weekly_hours": row[3],
                "current_weekly_hours": row[4],
                "certification_expiry": row[5],
            })

        conn.close()

        return {
            "site_id": site_id,
            "investigators": investigators,
        }

    # ========== Helper Methods for Computation ==========

    def _load_scoring_config(self):
        path = os.path.join(self.workspace, "scoring_config.yaml")
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _load_regional_benchmarks(self):
        path = os.path.join(self.workspace, "regional_benchmarks.csv")
        benchmarks = {}
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                benchmarks[row["region"]] = {
                    "default_monthly_target": int(row["default_monthly_target"]),
                    "expected_screen_pass_rate": float(row["expected_screen_pass_rate"]),
                }
        return benchmarks

    def _load_intervention_catalog(self):
        path = os.path.join(self.workspace, "intervention_catalog.yaml")
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _load_site_supplements(self):
        """Load per-site supplementary data from all scalable workspace files."""
        supplements = {}

        for filename in os.listdir(self.workspace):
            filepath = os.path.join(self.workspace, filename)
            if not filename.startswith("site_supplement_"):
                continue

            ext = filename.rsplit(".", 1)[-1] if "." in filename else ""

            try:
                if ext == "csv":
                    with open(filepath, "r") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            sid = row["site_id"]
                            risk = float(row["risk_adjustment_factor"])
                            target_str = row["custom_monthly_target"]
                            custom_target = None
                            if target_str and target_str not in ("", "None", "N/A", "null"):
                                custom_target = int(float(target_str))
                            supplements[sid] = {
                                "risk_adjustment_factor": risk,
                                "custom_monthly_target": custom_target,
                            }

                elif ext == "json":
                    with open(filepath, "r") as f:
                        data = json.load(f)
                    for entry in data:
                        sid = entry["site_id"]
                        supplements[sid] = {
                            "risk_adjustment_factor": float(entry["risk_adjustment_factor"]),
                            "custom_monthly_target": entry.get("custom_monthly_target"),
                        }

                elif ext == "txt":
                    with open(filepath, "r") as f:
                        lines = f.readlines()
                    for line in lines[2:]:  # Skip header and separator
                        parts = [p.strip() for p in line.strip().split("|")]
                        if len(parts) >= 3 and parts[0].startswith("SITE_"):
                            sid = parts[0]
                            risk = float(parts[1])
                            target_str = parts[2]
                            custom_target = None
                            if target_str not in ("N/A", "None", "null", ""):
                                custom_target = int(float(target_str))
                            supplements[sid] = {
                                "risk_adjustment_factor": risk,
                                "custom_monthly_target": custom_target,
                            }

                elif ext == "yaml":
                    with open(filepath, "r") as f:
                        data = yaml.safe_load(f)
                    if data:
                        for sid, vals in data.items():
                            supplements[sid] = {
                                "risk_adjustment_factor": float(vals["risk_adjustment_factor"]),
                                "custom_monthly_target": vals.get("custom_monthly_target"),
                            }

                elif ext == "md":
                    with open(filepath, "r") as f:
                        lines = f.readlines()
                    for line in lines[2:]:  # Skip header and separator
                        parts = [p.strip() for p in line.strip().split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 3 and parts[0].startswith("SITE_"):
                            sid = parts[0]
                            risk = float(parts[1])
                            target_str = parts[2]
                            custom_target = None
                            if target_str not in ("N/A", "None", "null", ""):
                                custom_target = int(float(target_str))
                            supplements[sid] = {
                                "risk_adjustment_factor": risk,
                                "custom_monthly_target": custom_target,
                            }
            except Exception:
                continue

        return supplements

    def _compute_ground_truth(self):
        """Compute the full ground truth intervention priorities."""
        config = self._load_scoring_config()
        benchmarks = self._load_regional_benchmarks()
        catalog = self._load_intervention_catalog()
        supplements = self._load_site_supplements()

        thresholds = config["thresholds"]
        weights = config["weights"]
        tier_mults = config["tier_multipliers"]
        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        cert_days = thresholds["certification_expiry_days"]

        # Get all active sites
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM sites WHERE status = 'active' ORDER BY site_id")
        active_sites = [dict(r) for r in c.fetchall()]
        conn.close()

        results = []

        for site in active_sites:
            sid = site["site_id"]
            region = site["region"]
            tier = site["tier"]

            # 1. Screening failure rate
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM screening_logs WHERE site_id = ?", (sid,))
            total_screened = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM screening_logs WHERE site_id = ? AND outcome = 'fail'", (sid,))
            total_failed = c.fetchone()[0]
            conn.close()

            sfr = total_failed / total_screened if total_screened > 0 else 0
            sfr_excess = max(0, sfr - thresholds["screen_failure_rate"])
            sfr_norm = sfr_excess / (1 - thresholds["screen_failure_rate"]) if thresholds["screen_failure_rate"] < 1 else 0
            sfr_component = sfr_norm * weights["screening_failure"]
            is_sfr = sfr_excess > 0

            # 2. Eligibility barrier index
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "SELECT criterion_code, result, COUNT(*) FROM eligibility_results "
                "WHERE site_id = ? GROUP BY criterion_code, result",
                (sid,)
            )
            crit_data = {}
            for code, result, count in c.fetchall():
                if code not in crit_data:
                    crit_data[code] = {"met": 0, "not_met": 0}
                crit_data[code][result] = count
            conn.close()

            fail_rates = []
            for code, d in crit_data.items():
                denom = d["met"] + d["not_met"]
                if denom > 0:
                    fail_rates.append(d["not_met"] / denom)
            ebi = max(fail_rates) if fail_rates else 0
            ebi_excess = max(0, ebi - thresholds["eligibility_barrier"])
            ebi_norm = ebi_excess / (1 - thresholds["eligibility_barrier"]) if thresholds["eligibility_barrier"] < 1 else 0
            ebi_component = ebi_norm * weights["eligibility_barrier"]
            is_ebi = ebi_excess > 0

            # 3. Enrollment ratio
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "SELECT period, enrolled_count FROM enrollment_history "
                "WHERE site_id = ? ORDER BY period",
                (sid,)
            )
            enrollment_records = c.fetchall()
            conn.close()

            last_3 = enrollment_records[-3:] if len(enrollment_records) >= 3 else enrollment_records
            avg_enrolled = sum(r[1] for r in last_3) / len(last_3) if last_3 else 0

            supp = supplements.get(sid, {})
            custom_target = supp.get("custom_monthly_target")
            if custom_target is not None:
                target = custom_target
            else:
                target = benchmarks.get(region, {}).get("default_monthly_target", 10)

            er = avg_enrolled / target if target > 0 else 0
            er_deficit = max(0, thresholds["enrollment_ratio"] - er)
            er_norm = er_deficit / thresholds["enrollment_ratio"] if thresholds["enrollment_ratio"] > 0 else 0
            er_component = er_norm * weights["enrollment_shortfall"]
            is_er = er_deficit > 0

            # 4. Investigator capacity
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "SELECT max_weekly_hours, current_weekly_hours, certification_expiry "
                "FROM investigators WHERE site_id = ?",
                (sid,)
            )
            inv_rows = c.fetchall()
            conn.close()

            utilizations = []
            cert_expiring = False
            for max_h, cur_h, cert_exp in inv_rows:
                if max_h > 0:
                    utilizations.append(cur_h / max_h)
                exp_date = datetime.strptime(cert_exp, "%Y-%m-%d")
                if exp_date >= ref_date and exp_date <= ref_date + timedelta(days=cert_days):
                    cert_expiring = True

            avg_util = sum(utilizations) / len(utilizations) if utilizations else 0
            util_excess = max(0, avg_util - thresholds["investigator_utilization"])
            util_norm = util_excess / (1 - thresholds["investigator_utilization"]) if thresholds["investigator_utilization"] < 1 else 0
            ic_component = util_norm * weights["investigator_capacity"] + (5.0 if cert_expiring else 0)
            is_ic = util_excess > 0 or cert_expiring

            # 5. Determine bottleneck type
            bottlenecks = []
            if is_sfr:
                bottlenecks.append("screening_failure")
            if is_ebi:
                bottlenecks.append("eligibility_barrier")
            if is_er:
                bottlenecks.append("enrollment_shortfall")
            if is_ic:
                bottlenecks.append("investigator_capacity")

            if not bottlenecks:
                continue

            if len(bottlenecks) == 1:
                btype = bottlenecks[0]
            else:
                btype = "multiple"

            # 6. Severity score
            base_severity = sfr_component + ebi_component + er_component + ic_component
            t_mult = tier_mults.get(tier, 1.0)
            risk_adj = supp.get("risk_adjustment_factor", 1.0)
            severity = round(min(100.0, base_severity * t_mult * risk_adj), 2)

            # 7. Intervention
            intervention = catalog.get(btype, catalog.get("multiple", ""))

            results.append({
                "site_id": sid,
                "site_name": site["site_name"],
                "region": region,
                "bottleneck_type": btype,
                "severity_score": severity,
                "recommended_intervention": intervention,
            })

        # 8. Rank
        results.sort(key=lambda x: (-x["severity_score"], x["site_id"]))
        for i, r in enumerate(results):
            r["priority_rank"] = i + 1

        return results, active_sites

    # ========== Evaluation ==========

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
        ground_truth, active_sites = self._compute_ground_truth()
        gt_by_sid = {r["site_id"]: r for r in ground_truth}

        # Criterion 1: File exists with correct columns (10 pts)
        output_path = os.path.join(self.workspace, "site_intervention_priorities.csv")
        expected_columns = ["site_id", "site_name", "region", "bottleneck_type",
                            "severity_score", "recommended_intervention", "priority_rank"]
        agent_data = []
        file_ok = False
        columns_ok = False
        if os.path.exists(output_path):
            try:
                with open(output_path, "r") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    columns_ok = all(c in cols for c in expected_columns)
                    if columns_ok:
                        agent_data = list(reader)
                        file_ok = True
            except Exception:
                pass

        if file_ok and columns_ok:
            eval_criteria["file_format"] = {"passed": True, "score": 10, "max_score": 10}
        elif os.path.exists(output_path):
            eval_criteria["file_format"] = {
                "passed": False, "score": 3, "max_score": 10,
                "reason": f"File exists but columns mismatch. Expected: {expected_columns}"
            }
        else:
            eval_criteria["file_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "Output file site_intervention_priorities.csv not found"
            }

        # Criterion 2: Correct site coverage (15 pts)
        gt_site_ids = set(gt_by_sid.keys())
        agent_site_ids = set()
        agent_by_sid = {}
        for row in agent_data:
            sid = row.get("site_id", "").strip()
            agent_site_ids.add(sid)
            agent_by_sid[sid] = row

        if gt_site_ids and agent_site_ids:
            correct_sites = gt_site_ids & agent_site_ids
            extra_sites = agent_site_ids - gt_site_ids
            missing_sites = gt_site_ids - agent_site_ids
            coverage_ratio = len(correct_sites) / len(gt_site_ids) if gt_site_ids else 0
            penalty = len(extra_sites) / max(len(gt_site_ids), 1) * 0.3
            cov_score = max(0, coverage_ratio - penalty)
            cov_pts = round(cov_score * 15, 1)
            passed = cov_pts >= 14
            eval_criteria["site_coverage"] = {
                "passed": passed, "score": cov_pts, "max_score": 15,
                "reason": None if passed else f"Missing: {len(missing_sites)}, Extra: {len(extra_sites)}"
            }
        else:
            eval_criteria["site_coverage"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "No valid site data to compare"
            }

        # Criterion 3: Bottleneck type accuracy (20 pts)
        bt_correct = 0
        bt_total = 0
        for sid in gt_site_ids & agent_site_ids:
            bt_total += 1
            gt_bt = gt_by_sid[sid]["bottleneck_type"]
            agent_bt = agent_by_sid.get(sid, {}).get("bottleneck_type", "").strip()
            if agent_bt == gt_bt:
                bt_correct += 1

        if bt_total > 0:
            bt_ratio = bt_correct / bt_total
            bt_pts = round(bt_ratio * 20, 1)
            eval_criteria["bottleneck_accuracy"] = {
                "passed": bt_pts >= 18,
                "score": bt_pts,
                "max_score": 20,
                "reason": None if bt_pts >= 18 else f"{bt_correct}/{bt_total} correct"
            }
        else:
            eval_criteria["bottleneck_accuracy"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "No matching sites to compare"
            }

        # Criterion 4: Severity score accuracy (20 pts)
        sev_close = 0
        sev_total = 0
        tolerance = 0.5
        for sid in gt_site_ids & agent_site_ids:
            sev_total += 1
            gt_sev = gt_by_sid[sid]["severity_score"]
            try:
                agent_sev = float(agent_by_sid.get(sid, {}).get("severity_score", -999))
            except (ValueError, TypeError):
                agent_sev = -999
            if abs(agent_sev - gt_sev) <= tolerance:
                sev_close += 1

        if sev_total > 0:
            sev_ratio = sev_close / sev_total
            sev_pts = round(sev_ratio * 20, 1)
            eval_criteria["severity_accuracy"] = {
                "passed": sev_pts >= 18,
                "score": sev_pts,
                "max_score": 20,
                "reason": None if sev_pts >= 18 else f"{sev_close}/{sev_total} within tolerance"
            }
        else:
            eval_criteria["severity_accuracy"] = {
                "passed": False, "score": 0, "max_score": 20,
                "reason": "No matching sites to compare"
            }

        # Criterion 5: Priority ranking accuracy (15 pts)
        rank_correct = 0
        rank_total = 0
        for sid in gt_site_ids & agent_site_ids:
            rank_total += 1
            gt_rank = gt_by_sid[sid]["priority_rank"]
            try:
                agent_rank = int(agent_by_sid.get(sid, {}).get("priority_rank", -1))
            except (ValueError, TypeError):
                agent_rank = -1
            if agent_rank == gt_rank:
                rank_correct += 1

        if rank_total > 0:
            rank_ratio = rank_correct / rank_total
            rank_pts = round(rank_ratio * 15, 1)
            eval_criteria["ranking_accuracy"] = {
                "passed": rank_pts >= 13,
                "score": rank_pts,
                "max_score": 15,
                "reason": None if rank_pts >= 13 else f"{rank_correct}/{rank_total} correct ranks"
            }
        else:
            eval_criteria["ranking_accuracy"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "No matching sites to compare"
            }

        # Criterion 6: Intervention text accuracy (10 pts)
        interv_correct = 0
        interv_total = 0
        for sid in gt_site_ids & agent_site_ids:
            interv_total += 1
            gt_interv = gt_by_sid[sid]["recommended_intervention"]
            agent_interv = agent_by_sid.get(sid, {}).get("recommended_intervention", "").strip()
            if agent_interv == gt_interv:
                interv_correct += 1

        if interv_total > 0:
            interv_ratio = interv_correct / interv_total
            interv_pts = round(interv_ratio * 10, 1)
            eval_criteria["intervention_accuracy"] = {
                "passed": interv_pts >= 9,
                "score": interv_pts,
                "max_score": 10,
                "reason": None if interv_pts >= 9 else f"{interv_correct}/{interv_total} correct"
            }
        else:
            eval_criteria["intervention_accuracy"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "No matching sites to compare"
            }

        # Criterion 7: Response summary (10 pts)
        resp_pts = 0
        action_lower = action.lower() if action else ""

        # Check for total active sites count
        n_active = len(active_sites)
        if str(n_active) in action:
            resp_pts += 2.5

        # Check for intervention count
        n_intervention = len(ground_truth)
        if str(n_intervention) in action:
            resp_pts += 2.5

        # Check for top bottleneck types mentioned
        from collections import Counter
        bt_counts = Counter(r["bottleneck_type"] for r in ground_truth)
        top3 = [bt for bt, _ in bt_counts.most_common(3)]
        mentioned = sum(1 for bt in top3 if bt.replace("_", " ") in action_lower or bt in action_lower)
        if mentioned >= 2:
            resp_pts += 2.5

        # Check for top 5 sites mentioned
        top5 = ground_truth[:5]
        top5_mentioned = sum(1 for r in top5 if r["site_id"] in action)
        if top5_mentioned >= 3:
            resp_pts += 2.5

        eval_criteria["response_summary"] = {
            "passed": resp_pts >= 8,
            "score": round(resp_pts, 1),
            "max_score": 10,
            "reason": None if resp_pts >= 8 else "Missing some required summary elements"
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        info = {
            "eval_criteria": eval_criteria,
            "total_score": round(total_score, 1),
            "max_score": max_score,
        }

        reward = round(total_score / max_score, 4) if max_score > 0 else 0.0
        return reward, info

    # ========== Verification ==========

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod

        tool_call_count = 0

        # Step 1: Load workspace config files
        config = self._load_scoring_config()
        benchmarks = self._load_regional_benchmarks()
        catalog = self._load_intervention_catalog()
        supplements = self._load_site_supplements()

        thresholds = config["thresholds"]
        weights_cfg = config["weights"]
        tier_mults = config["tier_multipliers"]
        ref_date = datetime.strptime(config["reference_date"], "%Y-%m-%d")
        cert_days = thresholds["certification_expiry_days"]

        # Step 2: Get all active sites via tool
        all_active_sites = []
        page = 1
        while True:
            result = self.tools["list_sites"](page=page, page_size=20, status_filter="active")
            tool_call_count += 1
            all_active_sites.extend(result["sites"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 3: For each active site, gather data via tools and compute bottleneck
        site_results = []

        for site in all_active_sites:
            sid = site["site_id"]
            region = site["region"]
            tier = site["tier"]

            # Get screening summary
            screening = self.tools["get_screening_summary"](site_id=sid)
            tool_call_count += 1

            total_screened = screening["total_screened"]
            total_failed = screening["total_failed"]
            sfr = total_failed / total_screened if total_screened > 0 else 0
            sfr_excess = max(0, sfr - thresholds["screen_failure_rate"])
            sfr_norm = sfr_excess / (1 - thresholds["screen_failure_rate"]) if thresholds["screen_failure_rate"] < 1 else 0
            sfr_component = sfr_norm * weights_cfg["screening_failure"]
            is_sfr = sfr_excess > 0

            # Get eligibility breakdown
            elig = self.tools["get_eligibility_breakdown"](site_id=sid)
            tool_call_count += 1

            fail_rates = []
            for code, d in elig["criteria"].items():
                denom = d["met"] + d["not_met"]
                if denom > 0:
                    fail_rates.append(d["not_met"] / denom)
            ebi = max(fail_rates) if fail_rates else 0
            ebi_excess = max(0, ebi - thresholds["eligibility_barrier"])
            ebi_norm = ebi_excess / (1 - thresholds["eligibility_barrier"]) if thresholds["eligibility_barrier"] < 1 else 0
            ebi_component = ebi_norm * weights_cfg["eligibility_barrier"]
            is_ebi = ebi_excess > 0

            # Get enrollment history
            enroll = self.tools["get_enrollment_history"](site_id=sid)
            tool_call_count += 1

            records = enroll["history"]
            last_3 = records[-3:] if len(records) >= 3 else records
            avg_enrolled = sum(r["enrolled_count"] for r in last_3) / len(last_3) if last_3 else 0

            supp = supplements.get(sid, {})
            custom_target = supp.get("custom_monthly_target")
            if custom_target is not None:
                target = custom_target
            else:
                target = benchmarks.get(region, {}).get("default_monthly_target", 10)

            er = avg_enrolled / target if target > 0 else 0
            er_deficit = max(0, thresholds["enrollment_ratio"] - er)
            er_norm = er_deficit / thresholds["enrollment_ratio"] if thresholds["enrollment_ratio"] > 0 else 0
            er_component = er_norm * weights_cfg["enrollment_shortfall"]
            is_er = er_deficit > 0

            # Get investigators
            inv_data = self.tools["get_site_investigators"](site_id=sid)
            tool_call_count += 1

            utilizations = []
            cert_expiring = False
            for inv in inv_data["investigators"]:
                max_h = inv["max_weekly_hours"]
                cur_h = inv["current_weekly_hours"]
                if max_h > 0:
                    utilizations.append(cur_h / max_h)
                exp_date = datetime.strptime(inv["certification_expiry"], "%Y-%m-%d")
                if exp_date >= ref_date and exp_date <= ref_date + timedelta(days=cert_days):
                    cert_expiring = True

            avg_util = sum(utilizations) / len(utilizations) if utilizations else 0
            util_excess = max(0, avg_util - thresholds["investigator_utilization"])
            util_norm = util_excess / (1 - thresholds["investigator_utilization"]) if thresholds["investigator_utilization"] < 1 else 0
            ic_component = util_norm * weights_cfg["investigator_capacity"] + (5.0 if cert_expiring else 0)
            is_ic = util_excess > 0 or cert_expiring

            # Determine bottleneck
            bottlenecks = []
            if is_sfr:
                bottlenecks.append("screening_failure")
            if is_ebi:
                bottlenecks.append("eligibility_barrier")
            if is_er:
                bottlenecks.append("enrollment_shortfall")
            if is_ic:
                bottlenecks.append("investigator_capacity")

            if not bottlenecks:
                continue

            btype = bottlenecks[0] if len(bottlenecks) == 1 else "multiple"

            # Severity
            base_severity = sfr_component + ebi_component + er_component + ic_component
            t_mult = tier_mults.get(tier, 1.0)
            risk_adj = supp.get("risk_adjustment_factor", 1.0)
            severity = round(min(100.0, base_severity * t_mult * risk_adj), 2)

            intervention = catalog.get(btype, catalog.get("multiple", ""))

            site_results.append({
                "site_id": sid,
                "site_name": site["site_name"],
                "region": region,
                "bottleneck_type": btype,
                "severity_score": severity,
                "recommended_intervention": intervention,
            })

        # Rank
        site_results.sort(key=lambda x: (-x["severity_score"], x["site_id"]))
        for i, r in enumerate(site_results):
            r["priority_rank"] = i + 1

        # Write output CSV
        output_path = os.path.join(self.workspace, "site_intervention_priorities.csv")
        fieldnames = ["site_id", "site_name", "region", "bottleneck_type",
                       "severity_score", "recommended_intervention", "priority_rank"]
        with open(output_path, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in site_results:
                writer.writerow(r)

        # Build response summary
        from collections import Counter
        n_active = len(all_active_sites)
        n_intervention = len(site_results)
        bt_counts = Counter(r["bottleneck_type"] for r in site_results)
        top3_bt = [bt for bt, _ in bt_counts.most_common(3)]
        top5 = site_results[:5]

        action_parts = [
            f"Analysis complete. {n_active} active sites were analyzed.",
            f"{n_intervention} sites require intervention.",
            f"Top bottleneck types: {', '.join(top3_bt)}.",
            "Top 5 priority sites:",
        ]
        for r in top5:
            action_parts.append(
                f"  {r['site_id']} ({r['site_name']}): {r['bottleneck_type']}, "
                f"severity {r['severity_score']}, rank {r['priority_rank']}"
            )
        action_parts.append(
            "The full prioritized intervention list has been saved to site_intervention_priorities.csv."
        )
        action = "\n".join(action_parts)

        assert tool_call_count >= 15, f"Only {tool_call_count} tool calls made, need at least 15"

        return self.step(action)
