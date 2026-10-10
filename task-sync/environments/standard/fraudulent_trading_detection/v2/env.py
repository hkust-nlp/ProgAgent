import sqlite3
import os
import json
import csv
import glob
import math
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import yaml
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml


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

    # ================================================================
    #  Tools
    # ================================================================

    @tool(
        description="Retrieves wealth alerts filtered by review status, paginated. Returns a list of alert objects and pagination metadata.",
        parameters={
            "type": "object",
            "properties": {
                "review_status": {
                    "type": "string",
                    "enum": ["pending", "resolved", "dismissed"],
                    "description": "Filter alerts by their review status."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)."
                }
            },
            "required": ["review_status", "page", "page_size"]
        }
    )
    def get_wealth_alerts(self, review_status: str, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM wealth_alerts WHERE review_status=?", (review_status,))
        total = c.fetchone()[0]
        c.execute(
            "SELECT * FROM wealth_alerts WHERE review_status=? ORDER BY alert_id LIMIT ? OFFSET ?",
            (review_status, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "alerts": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
        }

    @tool(
        description="Retrieves detailed profile information for a single player by their ID.",
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The unique player identifier."
                }
            },
            "required": ["player_id"]
        }
    )
    def get_player_profile(self, player_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE player_id=?", (player_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Player {player_id} not found"}
        return dict(row)

    @tool(
        description="Retrieves marketplace listings where the specified player is the seller, paginated. Returns listing objects and pagination metadata.",
        parameters={
            "type": "object",
            "properties": {
                "seller_id": {
                    "type": "integer",
                    "description": "Player ID of the seller."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)."
                }
            },
            "required": ["seller_id", "page", "page_size"]
        }
    )
    def get_player_listings(self, seller_id: int, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM marketplace_listings WHERE seller_id=?", (seller_id,))
        total = c.fetchone()[0]
        c.execute(
            "SELECT * FROM marketplace_listings WHERE seller_id=? ORDER BY listing_id LIMIT ? OFFSET ?",
            (seller_id, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "listings": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
        }

    @tool(
        description="Retrieves detailed information about a single item by its ID, including rarity tier, base market value, category, and level requirement.",
        parameters={
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "The unique item identifier."
                }
            },
            "required": ["item_id"]
        }
    )
    def get_item_details(self, item_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM items WHERE item_id=?", (item_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Item {item_id} not found"}
        return dict(row)

    @tool(
        description="Retrieves the transaction history for a given player, paginated. Returns transaction objects and pagination metadata.",
        parameters={
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The unique player identifier."
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)."
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 20)."
                }
            },
            "required": ["player_id", "page", "page_size"]
        }
    )
    def get_player_transactions(self, player_id: int, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM player_transactions WHERE player_id=?", (player_id,))
        total = c.fetchone()[0]
        c.execute(
            "SELECT * FROM player_transactions WHERE player_id=? ORDER BY tx_id LIMIT ? OFFSET ?",
            (player_id, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "listings": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
        }

    # ================================================================
    #  Ground-truth computation (used by step)
    # ================================================================

    def _load_workspace_config(self):
        with open(os.path.join(self.workspace, "fraud_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "rarity_config.json")) as f:
            rarity = json.load(f)
        region_risk = {}
        with open(os.path.join(self.workspace, "region_risk.csv"), newline="") as f:
            for row in csv.DictReader(f):
                region_risk[row["region"]] = float(row["risk_multiplier"])
        return rules, rarity, region_risk

    def _load_session_ips(self):
        """Return {player_id: set_of_ips} from all session CSV files."""
        player_ips: Dict[int, set] = defaultdict(set)
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "player_sessions_*.csv"))):
            with open(fpath, newline="") as f:
                for row in csv.DictReader(f):
                    player_ips[int(row["player_id"])].add(row["ip_address"])
        return player_ips

    def _load_account_flags(self):
        """Return {player_id: count_of_flags}."""
        counts: Dict[int, int] = defaultdict(int)
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "account_flags_*.json"))):
            with open(fpath) as f:
                flags = json.load(f)
            for fl in flags:
                counts[int(fl["player_id"])] += 1
        return counts

    def _load_price_snapshots(self):
        """Return {item_id: average of 3 most recent snapshot prices}."""
        snapshots: Dict[int, list] = defaultdict(list)
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "item_price_snapshots_*.csv"))):
            with open(fpath, newline="") as f:
                for row in csv.DictReader(f):
                    snapshots[int(row["item_id"])].append(
                        (row["snapshot_date"], float(row["observed_price"]))
                    )
        result = {}
        for iid, snaps in snapshots.items():
            snaps.sort(key=lambda x: x[0], reverse=True)
            top3 = [s[1] for s in snaps[:3]]
            result[iid] = sum(top3) / len(top3)
        return result

    def _compute_ground_truth(self):
        """Compute full fraud scoring for all players with pending alerts."""
        rules, rarity_cfg, region_risk = self._load_workspace_config()
        player_ips = self._load_session_ips()
        flag_counts = self._load_account_flags()
        market_prices = self._load_price_snapshots()

        sw = rules["scoring_weights"]
        th = rules["thresholds"]
        abs_scores = rules["alert_base_scores"]
        rec_tiers = rules["recommendation_tiers"]
        analysis_date = datetime.strptime(rules["analysis_date"], "%Y-%m-%d")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get pending alerts grouped by player
        c = conn.cursor()
        c.execute("SELECT * FROM wealth_alerts WHERE review_status='pending' ORDER BY alert_id")
        pending = [dict(r) for r in c.fetchall()]

        player_alerts: Dict[int, list] = defaultdict(list)
        for a in pending:
            player_alerts[a["player_id"]].append(a)

        results = []
        for pid, alerts in player_alerts.items():
            # 1) Alert base score: use highest severity
            sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            best_alert = max(alerts, key=lambda a: sev_order.get(a["severity"], 0))
            base_score = abs_scores.get(best_alert["severity"], 0)
            alert_type = best_alert["alert_type"]

            score_breakdown = {"alert_base": base_score}

            # Player info
            c.execute("SELECT * FROM players WHERE player_id=?", (pid,))
            player = dict(c.fetchone())

            # 2) New account bonus
            reg = datetime.strptime(player["registration_date"], "%Y-%m-%d")
            age_days = (analysis_date - reg).days
            new_acct = 0
            if age_days < th["new_account_threshold_days"]:
                new_acct = sw["new_account_bonus"]
            score_breakdown["new_account_bonus"] = new_acct

            # 3) Trade frequency
            cutoff = (analysis_date - timedelta(days=th["trade_frequency_period_days"])).strftime("%Y-%m-%d")
            c.execute(
                "SELECT COUNT(*) FROM marketplace_listings WHERE seller_id=? AND listing_date>=?",
                (pid, cutoff),
            )
            trade_count = c.fetchone()[0]
            freq_score = 0
            if trade_count > th["trade_frequency_threshold"]:
                freq_score = sw["high_frequency_trading"]
            score_breakdown["high_frequency_trading"] = freq_score

            # 4) Price anomaly & 5) Level mismatch — per listing in the period
            c.execute(
                "SELECT * FROM marketplace_listings WHERE seller_id=? AND listing_date>=?",
                (pid, cutoff),
            )
            listings = [dict(r) for r in c.fetchall()]

            price_anomaly_total = 0
            level_mismatch_total = 0
            for li in listings:
                iid = li["item_id"]
                c.execute("SELECT * FROM items WHERE item_id=?", (iid,))
                item = dict(c.fetchone())

                ref_price = market_prices.get(iid, item["base_value"])
                if li["price"] > th["price_anomaly_multiplier"] * ref_price:
                    price_anomaly_total += sw["price_anomaly_per_listing"]

                if item["level_requirement"] > player["account_level"]:
                    level_mismatch_total += sw["level_mismatch_per_listing"]

            score_breakdown["price_anomaly"] = price_anomaly_total
            score_breakdown["level_mismatch"] = level_mismatch_total

            # 6) Multi-IP
            n_ips = len(player_ips.get(pid, set()))
            multi_ip = 0
            if n_ips > th["multi_ip_threshold"]:
                multi_ip = sw["multi_ip_sessions"]
            score_breakdown["multi_ip_sessions"] = multi_ip

            # 7) Wealth influx severity
            total_influx = sum(a["influx_amount"] for a in alerts)
            influx_base = th["wealth_influx_base"]
            influx_score = 0
            if total_influx > influx_base:
                influx_score = int((total_influx - influx_base) / influx_base) * sw["wealth_influx_severity"]
            score_breakdown["wealth_influx_severity"] = influx_score

            # 8) Prior flags
            nflags = flag_counts.get(pid, 0)
            prior_score = nflags * sw["prior_flag_per_incident"]
            score_breakdown["prior_flags"] = prior_score

            # Raw sum before region multiplier
            raw = sum(score_breakdown.values())

            # 9) Region multiplier
            rmult = region_risk.get(player["region"], 1.0)
            final_score = round(raw * rmult, 1)

            # Primary evidence: highest scoring factor (excluding alert_base)
            evidence_candidates = {k: v for k, v in score_breakdown.items() if k != "alert_base"}
            if evidence_candidates and max(evidence_candidates.values()) > 0:
                primary_evidence = sorted(
                    evidence_candidates.keys(),
                    key=lambda k: (-evidence_candidates[k], k),
                )[0]
            else:
                primary_evidence = "alert_base"

            # Recommendation
            susp_thresh = th["suspicious_score_threshold"]
            if final_score >= susp_thresh:
                if final_score >= susp_thresh * rec_tiers["block_multiplier"]:
                    rec = "block"
                elif final_score >= susp_thresh * rec_tiers["restrict_multiplier"]:
                    rec = "restrict"
                else:
                    rec = "investigate"
            else:
                rec = None  # not suspicious

            results.append({
                "player_id": pid,
                "username": player["username"],
                "fraud_score": final_score,
                "alert_type": alert_type,
                "primary_evidence": primary_evidence,
                "recommendation": rec,
                "score_breakdown": score_breakdown,
            })

        conn.close()

        # Sort by fraud_score desc, then player_id asc
        results.sort(key=lambda r: (-r["fraud_score"], r["player_id"]))

        suspicious = [r for r in results if r["recommendation"] is not None]
        return {
            "all_reviewed": results,
            "suspicious": suspicious,
            "total_reviewed": len(results),
            "total_suspicious": len(suspicious),
        }

    # ================================================================
    #  step
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
        gt = self._compute_ground_truth()
        eval_criteria = {}

        # --- Criterion 1: Report file exists with correct columns (15 pts) ---
        report_path = os.path.join(self.workspace, "suspicious_accounts_report.csv")
        report_rows = []
        c1_pass = False
        c1_reason = ""
        expected_cols = ["player_id", "username", "fraud_score", "alert_type",
                         "primary_evidence", "recommendation"]
        if os.path.exists(report_path):
            with open(report_path, newline="") as f:
                reader = csv.DictReader(f)
                actual_cols = reader.fieldnames or []
                if list(actual_cols) == expected_cols:
                    report_rows = list(reader)
                    c1_pass = True
                else:
                    c1_reason = f"Expected columns {expected_cols}, got {list(actual_cols)}"
        else:
            c1_reason = "File suspicious_accounts_report.csv not found"
        eval_criteria["report_structure"] = {
            "passed": c1_pass,
            "score": 15 if c1_pass else 0,
            "max_score": 15,
            "reason": c1_reason if not c1_pass else "",
        }

        # --- Criterion 2: Correct suspicious accounts identified (25 pts) ---
        gt_ids = set(r["player_id"] for r in gt["suspicious"])
        report_ids = set()
        for row in report_rows:
            try:
                report_ids.add(int(row["player_id"]))
            except (ValueError, KeyError):
                pass
        if gt_ids or report_ids:
            tp = len(gt_ids & report_ids)
            precision = tp / len(report_ids) if report_ids else 0
            recall = tp / len(gt_ids) if gt_ids else 0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
        else:
            f1 = 1.0
        c2_score = round(25 * f1)
        eval_criteria["account_identification"] = {
            "passed": c2_score == 25,
            "score": c2_score,
            "max_score": 25,
            "reason": "" if c2_score == 25 else f"F1={f1:.2f}, expected IDs={sorted(gt_ids)}, got IDs={sorted(report_ids)}",
        }

        # --- Criterion 3: Fraud scores accurate (20 pts) ---
        gt_scores = {r["player_id"]: r["fraud_score"] for r in gt["suspicious"]}
        score_matches = 0
        score_total = max(len(gt_scores), 1)
        for row in report_rows:
            try:
                pid = int(row["player_id"])
                reported = float(row["fraud_score"])
                if pid in gt_scores and abs(reported - gt_scores[pid]) <= 2.0:
                    score_matches += 1
            except (ValueError, KeyError):
                pass
        c3_frac = score_matches / score_total
        c3_score = round(20 * c3_frac)
        eval_criteria["fraud_scores"] = {
            "passed": c3_score == 20,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_score == 20 else f"{score_matches}/{score_total} scores within tolerance",
        }

        # --- Criterion 4: Recommendations correct (15 pts) ---
        gt_recs = {r["player_id"]: r["recommendation"] for r in gt["suspicious"]}
        rec_matches = 0
        rec_total = max(len(gt_recs), 1)
        for row in report_rows:
            try:
                pid = int(row["player_id"])
                if pid in gt_recs and row.get("recommendation", "").strip() == gt_recs[pid]:
                    rec_matches += 1
            except (ValueError, KeyError):
                pass
        c4_frac = rec_matches / rec_total
        c4_score = round(15 * c4_frac)
        eval_criteria["recommendations"] = {
            "passed": c4_score == 15,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_score == 15 else f"{rec_matches}/{rec_total} recommendations correct",
        }

        # --- Criterion 5: Correct sorting (10 pts) ---
        c5_pass = False
        if report_rows and c1_pass:
            try:
                pairs = [(float(r["fraud_score"]), int(r["player_id"])) for r in report_rows]
                expected = sorted(pairs, key=lambda x: (-x[0], x[1]))
                c5_pass = pairs == expected
            except (ValueError, KeyError):
                pass
        eval_criteria["sorting"] = {
            "passed": c5_pass,
            "score": 10 if c5_pass else 0,
            "max_score": 10,
            "reason": "" if c5_pass else "Report rows not sorted by fraud_score desc, player_id asc",
        }

        # --- Criterion 6: Response summary (15 pts) ---
        c6_score = 0
        c6_reasons = []
        action_lower = action.lower() if action else ""
        # Total reviewed
        expected_reviewed = gt["total_reviewed"]
        if str(expected_reviewed) in (action or ""):
            c6_score += 5
        else:
            c6_reasons.append(f"Expected total reviewed={expected_reviewed}")
        # Total suspicious
        expected_suspicious = gt["total_suspicious"]
        if str(expected_suspicious) in (action or ""):
            c6_score += 5
        else:
            c6_reasons.append(f"Expected total suspicious={expected_suspicious}")
        # Tier counts
        tier_counts = defaultdict(int)
        for r in gt["suspicious"]:
            tier_counts[r["recommendation"]] += 1
        tier_str_found = True
        for tier in ["block", "restrict", "investigate"]:
            cnt = tier_counts.get(tier, 0)
            if str(cnt) not in (action or ""):
                tier_str_found = False
        if tier_str_found:
            c6_score += 5
        else:
            c6_reasons.append(f"Expected tier counts: {dict(tier_counts)}")
        eval_criteria["response_summary"] = {
            "passed": c6_score == 15,
            "score": c6_score,
            "max_score": 15,
            "reason": "; ".join(c6_reasons) if c6_reasons else "",
        }

        total_score = sum(c["score"] for c in eval_criteria.values())
        max_score = sum(c["max_score"] for c in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ================================================================
    #  verify
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
        tool_calls = 0

        # --- 1. Read config files ---
        with open(os.path.join(self.workspace, "fraud_rules.yaml")) as f:
            rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "rarity_config.json")) as f:
            rarity_cfg = json.load(f)
        region_risk = {}
        with open(os.path.join(self.workspace, "region_risk.csv"), newline="") as f:
            for row in csv.DictReader(f):
                region_risk[row["region"]] = float(row["risk_multiplier"])

        sw = rules["scoring_weights"]
        th = rules["thresholds"]
        abs_scores = rules["alert_base_scores"]
        rec_tiers = rules["recommendation_tiers"]
        analysis_date = datetime.strptime(rules["analysis_date"], "%Y-%m-%d")

        # --- 2. Read workspace data files ---
        # Session IPs
        player_ips: Dict[int, set] = defaultdict(set)
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "player_sessions_*.csv"))):
            with open(fpath, newline="") as f:
                for row in csv.DictReader(f):
                    player_ips[int(row["player_id"])].add(row["ip_address"])

        # Account flags
        flag_counts: Dict[int, int] = defaultdict(int)
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "account_flags_*.json"))):
            with open(fpath) as f:
                for fl in json.load(f):
                    flag_counts[int(fl["player_id"])] += 1

        # Price snapshots
        snapshots_raw: Dict[int, list] = defaultdict(list)
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "item_price_snapshots_*.csv"))):
            with open(fpath, newline="") as f:
                for row in csv.DictReader(f):
                    snapshots_raw[int(row["item_id"])].append(
                        (row["snapshot_date"], float(row["observed_price"]))
                    )
        market_prices = {}
        for iid, snaps in snapshots_raw.items():
            snaps.sort(key=lambda x: x[0], reverse=True)
            top3 = [s[1] for s in snaps[:3]]
            market_prices[iid] = sum(top3) / len(top3)

        # --- 3. Get all pending alerts via tool ---
        all_alerts = []
        res = self.tools["get_wealth_alerts"](review_status="pending", page=1, page_size=20)
        tool_calls += 1
        all_alerts.extend(res["alerts"])
        total_pages = res["total_pages"]
        for pg in range(2, total_pages + 1):
            res = self.tools["get_wealth_alerts"](review_status="pending", page=pg, page_size=20)
            tool_calls += 1
            all_alerts.extend(res["alerts"])

        # Group by player
        player_alerts: Dict[int, list] = defaultdict(list)
        for a in all_alerts:
            player_alerts[a["player_id"]].append(a)

        # --- 4. Score each player ---
        sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        results = []
        item_cache = {}

        for pid, alerts in player_alerts.items():
            best_alert = max(alerts, key=lambda a: sev_order.get(a["severity"], 0))
            base_score = abs_scores.get(best_alert["severity"], 0)
            alert_type = best_alert["alert_type"]
            score_breakdown = {"alert_base": base_score}

            # Player profile
            profile = self.tools["get_player_profile"](player_id=pid)
            tool_calls += 1

            # New account bonus
            reg = datetime.strptime(profile["registration_date"], "%Y-%m-%d")
            age_days = (analysis_date - reg).days
            new_acct = sw["new_account_bonus"] if age_days < th["new_account_threshold_days"] else 0
            score_breakdown["new_account_bonus"] = new_acct

            # Get all listings for this player
            all_listings = []
            cutoff = (analysis_date - timedelta(days=th["trade_frequency_period_days"])).strftime("%Y-%m-%d")
            lres = self.tools["get_player_listings"](seller_id=pid, page=1, page_size=20)
            tool_calls += 1
            all_listings.extend(lres["listings"])
            for pg in range(2, lres["total_pages"] + 1):
                lres = self.tools["get_player_listings"](seller_id=pid, page=pg, page_size=20)
                tool_calls += 1
                all_listings.extend(lres["listings"])

            # Filter to recent period
            recent_listings = [l for l in all_listings if l["listing_date"] >= cutoff]

            # Trade frequency
            freq_score = sw["high_frequency_trading"] if len(recent_listings) > th["trade_frequency_threshold"] else 0
            score_breakdown["high_frequency_trading"] = freq_score

            # Price anomaly & level mismatch
            price_anomaly_total = 0
            level_mismatch_total = 0
            for li in recent_listings:
                iid = li["item_id"]
                if iid not in item_cache:
                    item_cache[iid] = self.tools["get_item_details"](item_id=iid)
                    tool_calls += 1
                item = item_cache[iid]

                ref_price = market_prices.get(iid, item["base_value"])
                if li["price"] > th["price_anomaly_multiplier"] * ref_price:
                    price_anomaly_total += sw["price_anomaly_per_listing"]

                if item["level_requirement"] > profile["account_level"]:
                    level_mismatch_total += sw["level_mismatch_per_listing"]

            score_breakdown["price_anomaly"] = price_anomaly_total
            score_breakdown["level_mismatch"] = level_mismatch_total

            # Multi-IP
            n_ips = len(player_ips.get(pid, set()))
            multi_ip = sw["multi_ip_sessions"] if n_ips > th["multi_ip_threshold"] else 0
            score_breakdown["multi_ip_sessions"] = multi_ip

            # Wealth influx severity
            total_influx = sum(a["influx_amount"] for a in alerts)
            influx_base = th["wealth_influx_base"]
            influx_score = 0
            if total_influx > influx_base:
                influx_score = int((total_influx - influx_base) / influx_base) * sw["wealth_influx_severity"]
            score_breakdown["wealth_influx_severity"] = influx_score

            # Prior flags
            nflags = flag_counts.get(pid, 0)
            prior_score = nflags * sw["prior_flag_per_incident"]
            score_breakdown["prior_flags"] = prior_score

            # Get transactions (to show we use all tools)
            tres = self.tools["get_player_transactions"](player_id=pid, page=1, page_size=20)
            tool_calls += 1

            # Raw sum & region multiplier
            raw = sum(score_breakdown.values())
            rmult = region_risk.get(profile["region"], 1.0)
            final_score = round(raw * rmult, 1)

            # Primary evidence
            evidence_candidates = {k: v for k, v in score_breakdown.items() if k != "alert_base"}
            if evidence_candidates and max(evidence_candidates.values()) > 0:
                primary_evidence = sorted(
                    evidence_candidates.keys(),
                    key=lambda k: (-evidence_candidates[k], k),
                )[0]
            else:
                primary_evidence = "alert_base"

            # Recommendation
            susp_thresh = th["suspicious_score_threshold"]
            rec = None
            if final_score >= susp_thresh:
                if final_score >= susp_thresh * rec_tiers["block_multiplier"]:
                    rec = "block"
                elif final_score >= susp_thresh * rec_tiers["restrict_multiplier"]:
                    rec = "restrict"
                else:
                    rec = "investigate"

            results.append({
                "player_id": pid,
                "username": profile["username"],
                "fraud_score": final_score,
                "alert_type": alert_type,
                "primary_evidence": primary_evidence,
                "recommendation": rec,
            })

        # Sort
        results.sort(key=lambda r: (-r["fraud_score"], r["player_id"]))
        suspicious = [r for r in results if r["recommendation"] is not None]

        # --- 5. Write report ---
        report_path = os.path.join(self.workspace, "suspicious_accounts_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["player_id", "username", "fraud_score", "alert_type",
                            "primary_evidence", "recommendation"],
            )
            writer.writeheader()
            for r in suspicious:
                writer.writerow({
                    "player_id": r["player_id"],
                    "username": r["username"],
                    "fraud_score": r["fraud_score"],
                    "alert_type": r["alert_type"],
                    "primary_evidence": r["primary_evidence"],
                    "recommendation": r["recommendation"],
                })

        # --- 6. Build summary ---
        from collections import Counter
        tier_counts = Counter(r["recommendation"] for r in suspicious)
        action = (
            f"Fraud detection analysis complete. "
            f"Total accounts reviewed: {len(results)}. "
            f"Total suspicious accounts: {len(suspicious)}. "
            f"Accounts to block: {tier_counts.get('block', 0)}, "
            f"Accounts to restrict: {tier_counts.get('restrict', 0)}, "
            f"Accounts to investigate: {tier_counts.get('investigate', 0)}."
        )

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made, need >= 15"

        return self.step(action)
