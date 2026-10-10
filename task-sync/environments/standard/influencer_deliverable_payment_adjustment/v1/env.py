import sqlite3
import os
import json
import csv
import yaml
from datetime import datetime
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

    # ====================== TOOL METHODS ======================

    @tool(
        description="List contracts filtered by status, with pagination. Returns a page of contract summaries (contract_id, campaign_name, influencer_id, status). Page size is 10.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by contract status, e.g. 'pending_review', 'completed', 'cancelled'.",
                },
                "page": {
                    "type": "integer",
                    "description": "1-based page number.",
                },
            },
            "required": ["status", "page"],
        },
    )
    def list_contracts(self, status: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        page_size = 10
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT contract_id, campaign_name, influencer_id, status "
            "FROM contracts WHERE status = ? ORDER BY contract_id "
            "LIMIT ? OFFSET ?",
            (status, page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT COUNT(*) FROM contracts WHERE status = ?", (status,)
        )
        total = cur.fetchone()[0]
        conn.close()
        return {
            "contracts": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @tool(
        description="Get full details for a single contract by its ID. Returns all contract fields including dates, engagement thresholds, payment, target region, and posting hour window.",
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "integer",
                    "description": "The contract ID to look up.",
                },
            },
            "required": ["contract_id"],
        },
    )
    def get_contract_details(self, contract_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM contracts WHERE contract_id = ?", (contract_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Contract {contract_id} not found."}
        return dict(row)

    @tool(
        description="List all posts associated with a specific contract. Returns post_id, posted_at, content_type, likes, comments, shares, and impressions for each post.",
        parameters={
            "type": "object",
            "properties": {
                "contract_id": {
                    "type": "integer",
                    "description": "The contract ID whose posts to list.",
                },
            },
            "required": ["contract_id"],
        },
    )
    def list_contract_posts(self, contract_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT post_id, posted_at, content_type, likes, comments, shares, impressions "
            "FROM posts WHERE contract_id = ? ORDER BY post_id",
            (contract_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"contract_id": contract_id, "posts": rows, "count": len(rows)}

    @tool(
        description="Get all bot detection scan records for a given post. Each record contains bot_score, flagged_accounts, scan_confidence, scan_method, and scan_date.",
        parameters={
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "The post ID to retrieve bot detection records for.",
                },
            },
            "required": ["post_id"],
        },
    )
    def get_bot_report(self, post_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT detection_id, bot_score, flagged_accounts, scan_confidence, "
            "scan_method, scan_date FROM bot_detection WHERE post_id = ? "
            "ORDER BY scan_confidence DESC",
            (post_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"post_id": post_id, "scans": rows, "count": len(rows)}

    @tool(
        description="Get influencer profile details by influencer ID.",
        parameters={
            "type": "object",
            "properties": {
                "influencer_id": {
                    "type": "integer",
                    "description": "The influencer ID.",
                },
            },
            "required": ["influencer_id"],
        },
    )
    def get_influencer(self, influencer_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM influencers WHERE influencer_id = ?", (influencer_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Influencer {influencer_id} not found."}
        return dict(row)

    # ====================== GROUND TRUTH COMPUTATION ======================

    def _compute_ground_truth(self):
        """Compute the full ground truth using direct DB access and workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load compliance rules
        with open(os.path.join(self.workspace, "compliance_rules.yaml")) as f:
            rules = yaml.safe_load(f)

        # Load all audience data
        audience = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("audience_geo_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    audience.update(data)

        region_map = rules["region_country_mapping"]
        max_bot = rules["bot_detection"]["max_bot_score"]
        min_conf = rules["bot_detection"]["min_scan_confidence"]

        cur = conn.cursor()

        # Get pending_review contracts
        cur.execute("SELECT * FROM contracts WHERE status = 'pending_review' ORDER BY contract_id")
        contracts = [dict(r) for r in cur.fetchall()]

        all_violations = []  # list of dicts
        payment_adjustments = []  # list of dicts

        for c in contracts:
            cid = c["contract_id"]
            cur.execute("SELECT * FROM posts WHERE contract_id = ? ORDER BY post_id", (cid,))
            contract_posts = [dict(r) for r in cur.fetchall()]

            violation_types_seen = set()

            for p in contract_posts:
                pid = p["post_id"]
                posted = datetime.strptime(p["posted_at"], "%Y-%m-%d %H:%M:%S")
                start_d = datetime.strptime(c["start_date"], "%Y-%m-%d")
                end_d = datetime.strptime(c["end_date"], "%Y-%m-%d")

                # Date violation
                if posted.date() < start_d.date() or posted.date() > end_d.date():
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "date_violation",
                        "detail": f"Posted {posted.date()}, window {c['start_date']} to {c['end_date']}",
                    })
                    violation_types_seen.add("date_violation")

                # Hour violation
                if posted.hour < c["posting_hour_start"] or posted.hour > c["posting_hour_end"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "hour_violation",
                        "detail": f"Hour {posted.hour}, allowed {c['posting_hour_start']}-{c['posting_hour_end']}",
                    })
                    violation_types_seen.add("hour_violation")

                # Engagement
                eng_rate = (p["likes"] + p["comments"] + p["shares"]) / max(p["impressions"], 1)
                if eng_rate < c["min_engagement_rate"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "low_engagement",
                        "detail": f"Rate {eng_rate:.6f} < min {c['min_engagement_rate']}",
                    })
                    violation_types_seen.add("low_engagement")

                # Bot score
                cur.execute(
                    "SELECT bot_score, scan_confidence FROM bot_detection "
                    "WHERE post_id = ? AND scan_confidence >= ? "
                    "ORDER BY scan_confidence DESC LIMIT 1",
                    (pid, min_conf),
                )
                bot_row = cur.fetchone()
                if bot_row and bot_row["bot_score"] > max_bot:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "high_bot_score",
                        "detail": f"Bot score {bot_row['bot_score']} > max {max_bot}",
                    })
                    violation_types_seen.add("high_bot_score")

                # Audience location
                pid_str = str(pid)
                if pid_str in audience:
                    breakdown = audience[pid_str]["audience_breakdown"]
                    target_countries = region_map.get(c["target_region"], [])
                    region_pct = sum(breakdown.get(cc, 0.0) for cc in target_countries) / 100.0
                    if region_pct < c["min_region_pct"]:
                        all_violations.append({
                            "post_id": pid, "contract_id": cid,
                            "violation_type": "audience_location",
                            "detail": f"Region pct {region_pct:.4f} < min {c['min_region_pct']}",
                        })
                        violation_types_seen.add("audience_location")

            # Compute penalty
            penalty = 0
            if "date_violation" in violation_types_seen:
                penalty += rules["timing"]["date_violation_penalty_pct"]
            if "hour_violation" in violation_types_seen:
                penalty += rules["timing"]["hour_violation_penalty_pct"]
            if "low_engagement" in violation_types_seen:
                penalty += rules["engagement"]["penalty_pct"]
            if "high_bot_score" in violation_types_seen:
                penalty += rules["bot_detection"]["penalty_pct"]
            if "audience_location" in violation_types_seen:
                penalty += rules["audience_location"]["penalty_pct"]

            shortfall = max(c["required_posts"] - len(contract_posts), 0)
            penalty += shortfall * rules["post_count"]["penalty_per_missing_post_pct"]

            penalty = min(penalty, rules["max_total_penalty_pct"])
            adjusted = round(c["base_payment"] * (1 - penalty / 100), 2)

            payment_adjustments.append({
                "contract_id": cid,
                "campaign_name": c["campaign_name"],
                "base_payment": c["base_payment"],
                "total_penalty_pct": penalty,
                "adjusted_payment": adjusted,
            })

        conn.close()

        # Sort violations
        all_violations.sort(key=lambda v: (v["contract_id"], v["post_id"], v["violation_type"]))
        payment_adjustments.sort(key=lambda p: p["contract_id"])

        return all_violations, payment_adjustments

    # ====================== STEP ======================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        gt_violations, gt_payments = self._compute_ground_truth()

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ---------- Criterion 1: flagged_posts.csv exists with correct columns (10 pts) ----------
        c1_max = 10
        max_score += c1_max
        fp_path = os.path.join(self.workspace, "flagged_posts.csv")
        fp_ok = False
        fp_rows = []
        expected_cols = {"post_id", "contract_id", "violation_type", "detail"}
        if os.path.exists(fp_path):
            try:
                with open(fp_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = set(reader.fieldnames) if reader.fieldnames else set()
                    if expected_cols.issubset(cols):
                        fp_rows = list(reader)
                        fp_ok = True
            except Exception:
                pass

        if fp_ok:
            eval_criteria["flagged_posts_structure"] = {
                "passed": True, "score": c1_max, "max_score": c1_max,
            }
            total_score += c1_max
        else:
            eval_criteria["flagged_posts_structure"] = {
                "passed": False, "score": 0, "max_score": c1_max,
                "reason": "flagged_posts.csv missing or wrong columns",
            }

        # ---------- Criterion 2: flagged_posts content accuracy (25 pts) ----------
        c2_max = 25
        max_score += c2_max
        if fp_ok and gt_violations:
            # Build sets of (post_id, contract_id, violation_type)
            gt_set = set()
            for v in gt_violations:
                gt_set.add((str(v["post_id"]), str(v["contract_id"]), v["violation_type"]))

            pred_set = set()
            for r in fp_rows:
                pred_set.add((
                    str(r.get("post_id", "")).strip(),
                    str(r.get("contract_id", "")).strip(),
                    str(r.get("violation_type", "")).strip(),
                ))

            if gt_set or pred_set:
                tp = len(gt_set & pred_set)
                precision = tp / len(pred_set) if pred_set else 0
                recall = tp / len(gt_set) if gt_set else 0
                f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
                c2_score = round(f1 * c2_max)
            else:
                c2_score = c2_max

            eval_criteria["flagged_posts_accuracy"] = {
                "passed": c2_score == c2_max,
                "score": c2_score,
                "max_score": c2_max,
                "reason": "" if c2_score == c2_max else f"F1={f1:.3f}, precision={precision:.3f}, recall={recall:.3f}",
            }
            total_score += c2_score
        elif not gt_violations:
            # No violations expected
            c2_score = c2_max if len(fp_rows) == 0 else 0
            eval_criteria["flagged_posts_accuracy"] = {
                "passed": c2_score == c2_max,
                "score": c2_score,
                "max_score": c2_max,
                "reason": "" if c2_score == c2_max else "Expected no violations",
            }
            total_score += c2_score
        else:
            eval_criteria["flagged_posts_accuracy"] = {
                "passed": False, "score": 0, "max_score": c2_max,
                "reason": "flagged_posts.csv not readable",
            }

        # ---------- Criterion 3: payment_adjustments.csv exists with correct columns (10 pts) ----------
        c3_max = 10
        max_score += c3_max
        pa_path = os.path.join(self.workspace, "payment_adjustments.csv")
        pa_ok = False
        pa_rows = []
        pa_expected = {"contract_id", "campaign_name", "base_payment", "total_penalty_pct", "adjusted_payment"}
        if os.path.exists(pa_path):
            try:
                with open(pa_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = set(reader.fieldnames) if reader.fieldnames else set()
                    if pa_expected.issubset(cols):
                        pa_rows = list(reader)
                        pa_ok = True
            except Exception:
                pass

        if pa_ok:
            eval_criteria["payment_adjustments_structure"] = {
                "passed": True, "score": c3_max, "max_score": c3_max,
            }
            total_score += c3_max
        else:
            eval_criteria["payment_adjustments_structure"] = {
                "passed": False, "score": 0, "max_score": c3_max,
                "reason": "payment_adjustments.csv missing or wrong columns",
            }

        # ---------- Criterion 4: penalty percentages correct (20 pts) ----------
        c4_max = 20
        max_score += c4_max
        if pa_ok and gt_payments:
            gt_map = {str(p["contract_id"]): p for p in gt_payments}
            correct = 0
            total_contracts = len(gt_payments)
            for r in pa_rows:
                cid = str(r.get("contract_id", "")).strip()
                if cid in gt_map:
                    try:
                        pred_pen = int(float(r.get("total_penalty_pct", -1)))
                        if pred_pen == gt_map[cid]["total_penalty_pct"]:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            ratio = correct / total_contracts if total_contracts else 1
            c4_score = round(ratio * c4_max)
            eval_criteria["penalty_pct_accuracy"] = {
                "passed": c4_score == c4_max,
                "score": c4_score,
                "max_score": c4_max,
                "reason": "" if c4_score == c4_max else f"{correct}/{total_contracts} correct",
            }
            total_score += c4_score
        else:
            eval_criteria["penalty_pct_accuracy"] = {
                "passed": False, "score": 0, "max_score": c4_max,
                "reason": "payment_adjustments.csv not readable or no contracts",
            }

        # ---------- Criterion 5: adjusted payments correct (20 pts) ----------
        c5_max = 20
        max_score += c5_max
        if pa_ok and gt_payments:
            gt_map = {str(p["contract_id"]): p for p in gt_payments}
            correct = 0
            total_contracts = len(gt_payments)
            for r in pa_rows:
                cid = str(r.get("contract_id", "")).strip()
                if cid in gt_map:
                    try:
                        pred_adj = round(float(r.get("adjusted_payment", -1)), 2)
                        if abs(pred_adj - gt_map[cid]["adjusted_payment"]) < 0.015:
                            correct += 1
                    except (ValueError, TypeError):
                        pass
            ratio = correct / total_contracts if total_contracts else 1
            c5_score = round(ratio * c5_max)
            eval_criteria["adjusted_payment_accuracy"] = {
                "passed": c5_score == c5_max,
                "score": c5_score,
                "max_score": c5_max,
                "reason": "" if c5_score == c5_max else f"{correct}/{total_contracts} correct",
            }
            total_score += c5_score
        else:
            eval_criteria["adjusted_payment_accuracy"] = {
                "passed": False, "score": 0, "max_score": c5_max,
                "reason": "payment_adjustments.csv not readable or no contracts",
            }

        # ---------- Criterion 6: action summary (15 pts) ----------
        c6_max = 15
        max_score += c6_max
        c6_score = 0

        gt_total_violations = len(gt_violations)
        gt_penalized = sum(1 for p in gt_payments if p["total_penalty_pct"] > 0)
        gt_total_deduction = round(
            sum(p["base_payment"] - p["adjusted_payment"] for p in gt_payments), 2
        )

        # Parse action string
        import re
        try:
            m_viol = re.search(r"Total violations:\s*(\d+)", action)
            m_pen = re.search(r"Contracts penalized:\s*(\d+)", action)
            m_ded = re.search(r"Total deductions:\s*\$?([\d,]+\.?\d*)", action)

            if m_viol and int(m_viol.group(1)) == gt_total_violations:
                c6_score += 5
            if m_pen and int(m_pen.group(1)) == gt_penalized:
                c6_score += 5
            if m_ded:
                pred_ded = float(m_ded.group(1).replace(",", ""))
                if abs(pred_ded - gt_total_deduction) < 0.015:
                    c6_score += 5
        except Exception:
            pass

        eval_criteria["action_summary"] = {
            "passed": c6_score == c6_max,
            "score": c6_score,
            "max_score": c6_max,
            "reason": "" if c6_score == c6_max else f"Expected: violations={gt_total_violations}, penalized={gt_penalized}, deductions=${gt_total_deduction:.2f}",
        }
        total_score += c6_score

        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, info

    # ====================== VERIFY ======================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml as _yaml

        # Step 1: Read compliance rules from workspace
        with open(os.path.join(self.workspace, "compliance_rules.yaml")) as f:
            rules = _yaml.safe_load(f)

        region_map = rules["region_country_mapping"]
        max_bot = rules["bot_detection"]["max_bot_score"]
        min_conf = rules["bot_detection"]["min_scan_confidence"]

        # Step 2: Read all audience geo files from workspace
        audience = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("audience_geo_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = json.load(f)
                    audience.update(data)

        # Step 3: List all pending_review contracts via tools (paginated)
        pending_contracts = []
        page = 1
        while True:
            result = self.tools["list_contracts"](status="pending_review", page=page)
            pending_contracts.extend(result["contracts"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 4: For each contract, get details, get posts, check violations
        all_violations = []
        payment_adjustments = []

        for c_summary in pending_contracts:
            cid = c_summary["contract_id"]

            # Get full contract details
            c = self.tools["get_contract_details"](contract_id=cid)

            # Get posts
            posts_result = self.tools["list_contract_posts"](contract_id=cid)
            contract_posts = posts_result["posts"]

            violation_types_seen = set()

            for p in contract_posts:
                pid = p["post_id"]
                posted = datetime.strptime(p["posted_at"], "%Y-%m-%d %H:%M:%S")
                start_d = datetime.strptime(c["start_date"], "%Y-%m-%d")
                end_d = datetime.strptime(c["end_date"], "%Y-%m-%d")

                # Date violation
                if posted.date() < start_d.date() or posted.date() > end_d.date():
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "date_violation",
                        "detail": f"Posted {posted.date()}, window {c['start_date']} to {c['end_date']}",
                    })
                    violation_types_seen.add("date_violation")

                # Hour violation
                if posted.hour < c["posting_hour_start"] or posted.hour > c["posting_hour_end"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "hour_violation",
                        "detail": f"Hour {posted.hour}, allowed {c['posting_hour_start']}-{c['posting_hour_end']}",
                    })
                    violation_types_seen.add("hour_violation")

                # Engagement
                eng_rate = (p["likes"] + p["comments"] + p["shares"]) / max(p["impressions"], 1)
                if eng_rate < c["min_engagement_rate"]:
                    all_violations.append({
                        "post_id": pid, "contract_id": cid,
                        "violation_type": "low_engagement",
                        "detail": f"Rate {eng_rate:.6f} < min {c['min_engagement_rate']}",
                    })
                    violation_types_seen.add("low_engagement")

                # Bot score via tool
                bot_result = self.tools["get_bot_report"](post_id=pid)
                # Find highest-confidence scan with confidence >= min_conf
                valid_scans = [s for s in bot_result["scans"] if s["scan_confidence"] >= min_conf]
                if valid_scans:
                    best = max(valid_scans, key=lambda s: s["scan_confidence"])
                    if best["bot_score"] > max_bot:
                        all_violations.append({
                            "post_id": pid, "contract_id": cid,
                            "violation_type": "high_bot_score",
                            "detail": f"Bot score {best['bot_score']} > max {max_bot}",
                        })
                        violation_types_seen.add("high_bot_score")

                # Audience location from workspace files
                pid_str = str(pid)
                if pid_str in audience:
                    breakdown = audience[pid_str]["audience_breakdown"]
                    target_countries = region_map.get(c["target_region"], [])
                    region_pct = sum(breakdown.get(cc, 0.0) for cc in target_countries) / 100.0
                    if region_pct < c["min_region_pct"]:
                        all_violations.append({
                            "post_id": pid, "contract_id": cid,
                            "violation_type": "audience_location",
                            "detail": f"Region pct {region_pct:.4f} < min {c['min_region_pct']}",
                        })
                        violation_types_seen.add("audience_location")

            # Compute penalty
            penalty = 0
            if "date_violation" in violation_types_seen:
                penalty += rules["timing"]["date_violation_penalty_pct"]
            if "hour_violation" in violation_types_seen:
                penalty += rules["timing"]["hour_violation_penalty_pct"]
            if "low_engagement" in violation_types_seen:
                penalty += rules["engagement"]["penalty_pct"]
            if "high_bot_score" in violation_types_seen:
                penalty += rules["bot_detection"]["penalty_pct"]
            if "audience_location" in violation_types_seen:
                penalty += rules["audience_location"]["penalty_pct"]

            shortfall = max(c["required_posts"] - len(contract_posts), 0)
            penalty += shortfall * rules["post_count"]["penalty_per_missing_post_pct"]

            penalty = min(penalty, rules["max_total_penalty_pct"])
            adjusted = round(c["base_payment"] * (1 - penalty / 100), 2)

            payment_adjustments.append({
                "contract_id": cid,
                "campaign_name": c["campaign_name"],
                "base_payment": c["base_payment"],
                "total_penalty_pct": penalty,
                "adjusted_payment": adjusted,
            })

        # Sort violations
        all_violations.sort(key=lambda v: (v["contract_id"], v["post_id"], v["violation_type"]))
        payment_adjustments.sort(key=lambda pa: pa["contract_id"])

        # Write flagged_posts.csv
        fp_path = os.path.join(self.workspace, "flagged_posts.csv")
        with open(fp_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["post_id", "contract_id", "violation_type", "detail"])
            writer.writeheader()
            for v in all_violations:
                writer.writerow(v)

        # Write payment_adjustments.csv
        pa_path = os.path.join(self.workspace, "payment_adjustments.csv")
        with open(pa_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["contract_id", "campaign_name", "base_payment", "total_penalty_pct", "adjusted_payment"]
            )
            writer.writeheader()
            for pa in payment_adjustments:
                writer.writerow({
                    "contract_id": pa["contract_id"],
                    "campaign_name": pa["campaign_name"],
                    "base_payment": f"{pa['base_payment']:.2f}",
                    "total_penalty_pct": pa["total_penalty_pct"],
                    "adjusted_payment": f"{pa['adjusted_payment']:.2f}",
                })

        # Build action summary
        total_violations = len(all_violations)
        contracts_penalized = sum(1 for pa in payment_adjustments if pa["total_penalty_pct"] > 0)
        total_deduction = round(
            sum(pa["base_payment"] - pa["adjusted_payment"] for pa in payment_adjustments), 2
        )

        action = (
            f"Total violations: {total_violations}\n"
            f"Contracts penalized: {contracts_penalized}\n"
            f"Total deductions: ${total_deduction:.2f}"
        )

        return self.step(action)
