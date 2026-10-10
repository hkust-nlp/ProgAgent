"""
Environment for the Mechanical Royalty Discrepancy task.
Provides tools for querying track registrations and payment ledgers,
plus step/verify for evaluation.
"""
import sqlite3
import os
import csv
import json
import glob
from typing import Tuple, Dict, List, Any
from collections import defaultdict


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
    # Tool methods
    # ================================================================

    @tool(
        description=(
            "Look up track metadata by ISRC code. Returns title, artist, "
            "album, label, release date, genre, and duration."
        ),
        parameters={
            "type": "object",
            "properties": {
                "isrc": {
                    "type": "string",
                    "description": "The ISRC code to look up (e.g. US-S3K-24-00012)",
                },
            },
            "required": ["isrc"],
        },
    )
    def lookup_track(self, isrc: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM tracks WHERE isrc = ?", (isrc,))
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": "Track not found", "isrc": isrc}
        cols = [
            "track_id", "isrc", "title", "artist", "album",
            "label", "release_date", "genre", "duration_seconds",
        ]
        return dict(zip(cols, row))

    @tool(
        description=(
            "Retrieve all active registration entries (publisher and songwriter "
            "splits) for a given ISRC. Each entry includes entity name, type, "
            "role, split percentage, and registration territory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "isrc": {
                    "type": "string",
                    "description": "The ISRC code to query registrations for",
                },
            },
            "required": ["isrc"],
        },
    )
    def get_registrations(self, isrc: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT * FROM registrations WHERE isrc = ? AND status = 'active'",
            (isrc,),
        )
        rows = c.fetchall()
        conn.close()
        if not rows:
            return {"isrc": isrc, "registrations": []}
        cols = [
            "reg_id", "isrc", "entity_name", "entity_type", "role",
            "split_pct", "territory", "effective_date", "status",
        ]
        return {
            "isrc": isrc,
            "registrations": [dict(zip(cols, row)) for row in rows],
        }

    @tool(
        description=(
            "List tracks with pagination. Returns ISRCs and basic metadata. "
            "Page size is capped at 25."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (max 25, default 20)",
                },
            },
            "required": ["page"],
        },
    )
    def list_tracks(self, page: int, page_size: int = 20) -> dict:
        page_size = min(page_size, 25)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        c.execute(
            "SELECT isrc, title, artist, label FROM tracks "
            "ORDER BY track_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = c.fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_tracks": total,
            "total_pages": (total + page_size - 1) // page_size,
            "tracks": [
                {"isrc": r[0], "title": r[1], "artist": r[2], "label": r[3]}
                for r in rows
            ],
        }

    @tool(
        description=(
            "Get payment history for a given ISRC. Optionally filter by "
            "reporting period label (e.g. '2024_Q1'). Returns all payment "
            "records including payee name, amount, currency, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "isrc": {
                    "type": "string",
                    "description": "The ISRC code to query payments for",
                },
                "period": {
                    "type": "string",
                    "description": (
                        "Optional period label to filter by, e.g. '2024_Q1'"
                    ),
                },
            },
            "required": ["isrc"],
        },
    )
    def get_payment_history(self, isrc: str, period: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if period:
            c.execute(
                "SELECT * FROM payments WHERE isrc = ? AND period_label = ?",
                (isrc, period),
            )
        else:
            c.execute("SELECT * FROM payments WHERE isrc = ?", (isrc,))
        rows = c.fetchall()
        conn.close()
        cols = [
            "payment_id", "isrc", "payee_name", "payee_type", "amount",
            "currency", "period_label", "payment_date", "status",
        ]
        return {
            "isrc": isrc,
            "payments": [dict(zip(cols, row)) for row in rows],
        }

    @tool(
        description=(
            "Search payment records by payee name (exact or partial match). "
            "Results are paginated; page size is capped at 25."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payee_name": {
                    "type": "string",
                    "description": "Full or partial payee name to search for",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed (default 1)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 25, default 20)",
                },
            },
            "required": ["payee_name"],
        },
    )
    def search_payments(
        self, payee_name: str, page: int = 1, page_size: int = 20
    ) -> dict:
        page_size = min(page_size, 25)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        like_pat = f"%{payee_name}%"
        total = c.execute(
            "SELECT COUNT(*) FROM payments WHERE payee_name LIKE ?",
            (like_pat,),
        ).fetchone()[0]
        c.execute(
            "SELECT * FROM payments WHERE payee_name LIKE ? "
            "ORDER BY payment_id LIMIT ? OFFSET ?",
            (like_pat, page_size, offset),
        )
        rows = c.fetchall()
        conn.close()
        cols = [
            "payment_id", "isrc", "payee_name", "payee_type", "amount",
            "currency", "period_label", "payment_date", "status",
        ]
        return {
            "total_results": total,
            "page": page,
            "page_size": page_size,
            "payments": [dict(zip(cols, row)) for row in rows],
        }

    @tool(
        description=(
            "Get royalty account information for a named entity. Returns "
            "collection society affiliation, territory, bank verification "
            "status, and contact email."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Exact name of the publisher or songwriter",
                },
            },
            "required": ["entity_name"],
        },
    )
    def get_account_info(self, entity_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT * FROM royalty_accounts WHERE entity_name = ?",
            (entity_name,),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            return {"error": "Account not found", "entity_name": entity_name}
        cols = [
            "account_id", "entity_name", "entity_type",
            "collection_society", "territory", "bank_status", "contact_email",
        ]
        return dict(zip(cols, row))

    # ================================================================
    # Helper: parse workspace for ground-truth computation
    # ================================================================

    def _compute_ground_truth(self):
        """
        Compute ground-truth discrepancies from DB + workspace.
        Used by both step() and verify().
        """
        # --- Discover and parse streaming reports ---
        streaming_files = sorted(
            glob.glob(os.path.join(self.workspace, "streaming_*.csv"))
        )
        all_streaming = []
        for fpath in streaming_files:
            basename = os.path.basename(fpath).replace(".csv", "")
            basename = basename.replace("streaming_", "", 1)
            parts = basename.split("_")
            period_label = "_".join(parts[-2:])
            platform = "_".join(parts[:-2])
            with open(fpath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    all_streaming.append({
                        "isrc": row["isrc"],
                        "stream_count": int(row["stream_count"]),
                        "territory": row["territory"],
                        "platform": platform,
                        "period": period_label,
                    })

        # --- Read config files ---
        rates = {}
        with open(os.path.join(self.workspace, "royalty_rates.yaml")) as f:
            for line in f:
                line = line.strip()
                if (
                    ":" in line
                    and not line.startswith("#")
                    and not line.startswith("platform")
                ):
                    parts = line.split(":", 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if val:
                        try:
                            rates[key] = float(val)
                        except ValueError:
                            pass

        with open(os.path.join(self.workspace, "reconciliation_policy.json")) as f:
            policy = json.load(f)
        shortfall_threshold = policy["shortfall_threshold_usd"]
        split_tolerance = policy["split_tolerance_pct"]

        commissions = {}
        with open(os.path.join(self.workspace, "territory_commissions.csv"), newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                commissions[row["territory_code"]] = float(row["commission_rate"])

        # --- Query DB ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        all_regs = {}
        for row in c.execute(
            "SELECT * FROM registrations WHERE status = 'active'"
        ):
            isrc = row["isrc"]
            all_regs.setdefault(isrc, []).append(dict(row))

        all_payments = {}
        for row in c.execute("SELECT * FROM payments"):
            isrc = row["isrc"]
            all_payments.setdefault(isrc, []).append(dict(row))

        track_info = {}
        for row in c.execute("SELECT isrc, title, artist FROM tracks"):
            track_info[row["isrc"]] = {
                "title": row["title"],
                "artist": row["artist"],
            }

        conn.close()

        # --- Compute discrepancies ---
        unique_isrcs = sorted(set(e["isrc"] for e in all_streaming))

        stream_by_isrc_period = defaultdict(lambda: defaultdict(list))
        for e in all_streaming:
            stream_by_isrc_period[e["isrc"]][e["period"]].append(e)

        gt = []

        for isrc in unique_isrcs:
            info = track_info.get(isrc, {"title": "Unknown", "artist": "Unknown"})
            periods = stream_by_isrc_period[isrc]

            # Total gross royalty across all periods
            total_gross = 0.0
            for period_label, entries in periods.items():
                total_gross += sum(
                    e["stream_count"] * rates.get(e["platform"], 0)
                    for e in entries
                )

            regs = all_regs.get(isrc, [])

            if not regs:
                gt.append({
                    "isrc": isrc,
                    "track_title": info["title"],
                    "artist": info["artist"],
                    "discrepancy_type": "UNREGISTERED",
                    "expected_amount": round(total_gross, 2),
                    "paid_amount": 0.00,
                    "shortfall": round(total_gross, 2),
                    "details": "No registration record found",
                })
                continue

            # Split anomaly check
            split_sum = sum(r["split_pct"] for r in regs)
            if abs(split_sum - 100.0) > split_tolerance:
                gt.append({
                    "isrc": isrc,
                    "track_title": info["title"],
                    "artist": info["artist"],
                    "discrepancy_type": "SPLIT_ANOMALY",
                    "expected_amount": 100.00,
                    "paid_amount": round(split_sum, 2),
                    "shortfall": 0.00,
                    "details": f"Split sum is {split_sum:.2f}%, deviates from 100%",
                })

            # Expected net per payee per period (rounded per payee-period)
            territory = regs[0]["territory"]
            commission_rate = commissions.get(territory, 0.10)

            total_expected_net = 0.0
            for period_label, entries in periods.items():
                period_gross = sum(
                    e["stream_count"] * rates.get(e["platform"], 0)
                    for e in entries
                )
                for reg in regs:
                    payee_net = (
                        period_gross * reg["split_pct"] / 100.0
                        * (1 - commission_rate)
                    )
                    total_expected_net += round(payee_net, 2)
            total_expected_net = round(total_expected_net, 2)

            payments = all_payments.get(isrc, [])
            total_paid = round(sum(p["amount"] for p in payments), 2)

            if not payments:
                gt.append({
                    "isrc": isrc,
                    "track_title": info["title"],
                    "artist": info["artist"],
                    "discrepancy_type": "UNPAID",
                    "expected_amount": total_expected_net,
                    "paid_amount": 0.00,
                    "shortfall": total_expected_net,
                    "details": "No payment records found",
                })
            elif total_expected_net - total_paid > shortfall_threshold:
                gt.append({
                    "isrc": isrc,
                    "track_title": info["title"],
                    "artist": info["artist"],
                    "discrepancy_type": "UNDERPAID",
                    "expected_amount": total_expected_net,
                    "paid_amount": total_paid,
                    "shortfall": round(total_expected_net - total_paid, 2),
                    "details": (
                        f"Paid {total_paid:.2f} of expected "
                        f"{total_expected_net:.2f}"
                    ),
                })

        gt.sort(key=lambda x: (x["discrepancy_type"], x["isrc"]))
        return gt, unique_isrcs

    # ================================================================
    # step
    # ================================================================

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
        gt, unique_isrcs = self._compute_ground_truth()

        # Ground truth indexed by type
        gt_by_type = defaultdict(set)
        gt_amounts = {}
        for d in gt:
            gt_by_type[d["discrepancy_type"]].add(d["isrc"])
            gt_amounts[(d["discrepancy_type"], d["isrc"])] = {
                "expected": d["expected_amount"],
                "paid": d["paid_amount"],
                "shortfall": d["shortfall"],
            }

        # --- Read agent outputs ---
        report_path = os.path.join(self.workspace, "discrepancy_report.csv")
        summary_path = os.path.join(self.workspace, "summary.json")

        required_cols = [
            "isrc", "track_title", "artist", "discrepancy_type",
            "expected_amount", "paid_amount", "shortfall", "details",
        ]

        criteria = {}
        total_score = 0.0

        # ---- Criterion 1: report format (10 pts) ----
        agent_rows = []
        if os.path.exists(report_path):
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    agent_rows = list(reader)
                    cols = list(reader.fieldnames or [])
                if all(c in cols for c in required_cols):
                    criteria["report_format"] = {
                        "passed": True, "score": 10, "max_score": 10,
                    }
                    total_score += 10
                else:
                    missing = [c for c in required_cols if c not in cols]
                    criteria["report_format"] = {
                        "passed": False, "score": 5, "max_score": 10,
                        "reason": f"Missing columns: {missing}",
                    }
                    total_score += 5
            except Exception as e:
                agent_rows = []
                criteria["report_format"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": str(e),
                }
        else:
            criteria["report_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "discrepancy_report.csv not found",
            }

        # Parse agent rows
        agent_by_type = defaultdict(set)
        agent_amounts = {}
        for row in agent_rows:
            dtype = row.get("discrepancy_type", "").strip()
            isrc = row.get("isrc", "").strip()
            agent_by_type[dtype].add(isrc)
            try:
                agent_amounts[(dtype, isrc)] = {
                    "expected": float(row.get("expected_amount", 0)),
                    "paid": float(row.get("paid_amount", 0)),
                    "shortfall": float(row.get("shortfall", 0)),
                }
            except (ValueError, TypeError):
                pass

        # Helper: Jaccard-based scoring
        def _score_set(agent_set, gt_set, max_pts):
            if not gt_set and not agent_set:
                return max_pts, True
            if not gt_set:
                return (max_pts if not agent_set else 0.0), (not agent_set)
            union = gt_set | agent_set
            inter = gt_set & agent_set
            score = max_pts * len(inter) / len(union) if union else max_pts
            return round(score, 2), (inter == gt_set == agent_set)

        # ---- Criterion 2: UNREGISTERED accuracy (20 pts) ----
        s, p = _score_set(
            agent_by_type.get("UNREGISTERED", set()),
            gt_by_type.get("UNREGISTERED", set()),
            20,
        )
        criteria["unregistered_accuracy"] = {
            "passed": p, "score": s, "max_score": 20,
        }
        if not p:
            criteria["unregistered_accuracy"]["reason"] = (
                f"Expected {len(gt_by_type.get('UNREGISTERED', set()))} ISRCs, "
                f"agent reported {len(agent_by_type.get('UNREGISTERED', set()))}"
            )
        total_score += s

        # ---- Criterion 3: UNPAID accuracy (20 pts) ----
        s, p = _score_set(
            agent_by_type.get("UNPAID", set()),
            gt_by_type.get("UNPAID", set()),
            20,
        )
        criteria["unpaid_accuracy"] = {
            "passed": p, "score": s, "max_score": 20,
        }
        if not p:
            criteria["unpaid_accuracy"]["reason"] = (
                f"Expected {len(gt_by_type.get('UNPAID', set()))} ISRCs, "
                f"agent reported {len(agent_by_type.get('UNPAID', set()))}"
            )
        total_score += s

        # ---- Criterion 4: UNDERPAID accuracy (25 pts = 15 set + 10 amounts) ----
        gt_under = gt_by_type.get("UNDERPAID", set())
        ag_under = agent_by_type.get("UNDERPAID", set())
        set_score, set_pass = _score_set(ag_under, gt_under, 15)

        matched = gt_under & ag_under
        amt_score = 0.0
        if matched:
            correct = 0
            for isrc in matched:
                gt_a = gt_amounts.get(("UNDERPAID", isrc), {})
                ag_a = agent_amounts.get(("UNDERPAID", isrc), {})
                if gt_a and ag_a:
                    gt_s = gt_a["shortfall"]
                    ag_s = ag_a["shortfall"]
                    if gt_s > 0 and abs(ag_s - gt_s) / gt_s <= 0.05:
                        correct += 1
                    elif gt_s == 0 and ag_s == 0:
                        correct += 1
            amt_score = round(10 * correct / len(matched), 2)
        elif not gt_under:
            amt_score = 10.0

        criteria["underpaid_accuracy"] = {
            "passed": set_pass and amt_score >= 9.99,
            "score": round(set_score + amt_score, 2),
            "max_score": 25,
        }
        if not criteria["underpaid_accuracy"]["passed"]:
            criteria["underpaid_accuracy"]["reason"] = (
                f"Set: {len(matched)}/{len(gt_under)} matched; "
                f"amount score: {amt_score:.1f}/10"
            )
        total_score += set_score + amt_score

        # ---- Criterion 5: SPLIT_ANOMALY accuracy (10 pts) ----
        s, p = _score_set(
            agent_by_type.get("SPLIT_ANOMALY", set()),
            gt_by_type.get("SPLIT_ANOMALY", set()),
            10,
        )
        criteria["split_anomaly_accuracy"] = {
            "passed": p, "score": s, "max_score": 10,
        }
        if not p:
            criteria["split_anomaly_accuracy"]["reason"] = (
                f"Expected {len(gt_by_type.get('SPLIT_ANOMALY', set()))} ISRCs, "
                f"agent reported {len(agent_by_type.get('SPLIT_ANOMALY', set()))}"
            )
        total_score += s

        # ---- Criterion 6: summary.json accuracy (15 pts) ----
        summary_score = 0.0
        summary_pass = False
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    agent_summary = json.load(f)

                gt_summary = {
                    "total_tracks_analyzed": len(unique_isrcs),
                    "total_discrepancies": len(gt),
                    "unregistered_count": len(
                        gt_by_type.get("UNREGISTERED", set())
                    ),
                    "unpaid_count": len(gt_by_type.get("UNPAID", set())),
                    "underpaid_count": len(gt_by_type.get("UNDERPAID", set())),
                    "split_anomaly_count": len(
                        gt_by_type.get("SPLIT_ANOMALY", set())
                    ),
                    "total_shortfall": round(
                        sum(d["shortfall"] for d in gt), 2
                    ),
                }

                checks = 0
                total_checks = len(gt_summary)
                for key, gt_val in gt_summary.items():
                    agent_val = agent_summary.get(key)
                    if agent_val is None:
                        continue
                    if isinstance(gt_val, float):
                        try:
                            if gt_val > 0 and abs(float(agent_val) - gt_val) / gt_val <= 0.05:
                                checks += 1
                            elif gt_val == 0 and float(agent_val) == 0:
                                checks += 1
                        except (ValueError, TypeError):
                            pass
                    else:
                        try:
                            if int(agent_val) == gt_val:
                                checks += 1
                        except (ValueError, TypeError):
                            pass

                summary_score = round(15 * checks / total_checks, 2)
                summary_pass = checks == total_checks
            except Exception:
                summary_score = 0.0
        else:
            pass  # score stays 0

        criteria["summary_accuracy"] = {
            "passed": summary_pass,
            "score": summary_score,
            "max_score": 15,
        }
        if not summary_pass:
            criteria["summary_accuracy"]["reason"] = (
                "summary.json missing or inaccurate"
            )
        total_score += summary_score

        max_total = 100.0
        reward = round(total_score / max_total, 4)

        info = {
            "eval_criteria": criteria,
            "total_score": round(total_score, 2),
            "max_score": max_total,
        }
        return reward, info

    # ================================================================
    # verify
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
        # 1. Discover streaming report files
        streaming_files = sorted(
            glob.glob(os.path.join(self.workspace, "streaming_*.csv"))
        )

        # 2. Parse streaming data
        all_streaming = []
        for fpath in streaming_files:
            basename = os.path.basename(fpath).replace(".csv", "")
            basename = basename.replace("streaming_", "", 1)
            parts = basename.split("_")
            period_label = "_".join(parts[-2:])
            platform = "_".join(parts[:-2])
            with open(fpath, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    all_streaming.append({
                        "isrc": row["isrc"],
                        "stream_count": int(row["stream_count"]),
                        "territory": row["territory"],
                        "platform": platform,
                        "period": period_label,
                    })

        # 3. Read configuration files
        rates = {}
        with open(os.path.join(self.workspace, "royalty_rates.yaml")) as f:
            for line in f:
                line = line.strip()
                if (
                    ":" in line
                    and not line.startswith("#")
                    and not line.startswith("platform")
                ):
                    parts = line.split(":", 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if val:
                        try:
                            rates[key] = float(val)
                        except ValueError:
                            pass

        with open(
            os.path.join(self.workspace, "reconciliation_policy.json")
        ) as f:
            policy = json.load(f)
        shortfall_threshold = policy["shortfall_threshold_usd"]
        split_tolerance = policy["split_tolerance_pct"]

        commissions = {}
        with open(
            os.path.join(self.workspace, "territory_commissions.csv"),
            newline="",
        ) as f:
            reader = csv.DictReader(f)
            for row in reader:
                commissions[row["territory_code"]] = float(
                    row["commission_rate"]
                )

        # 4. Collect unique ISRCs and group streaming data
        unique_isrcs = sorted(set(e["isrc"] for e in all_streaming))

        stream_by_isrc = defaultdict(list)
        for e in all_streaming:
            stream_by_isrc[e["isrc"]].append(e)

        # 5. For each ISRC, call tools and compute discrepancies
        discrepancies = []

        for isrc in unique_isrcs:
            # --- tool calls ---
            track_result = self.tools["lookup_track"](isrc=isrc)
            reg_result = self.tools["get_registrations"](isrc=isrc)

            title = (
                track_result.get("title", "Unknown")
                if "error" not in track_result
                else "Unknown"
            )
            artist = (
                track_result.get("artist", "Unknown")
                if "error" not in track_result
                else "Unknown"
            )

            entries = stream_by_isrc[isrc]
            entries_by_period = defaultdict(list)
            for e in entries:
                entries_by_period[e["period"]].append(e)

            # Total gross across all periods
            total_gross = sum(
                e["stream_count"] * rates.get(e["platform"], 0)
                for e in entries
            )

            regs = reg_result.get("registrations", [])

            if not regs:
                discrepancies.append({
                    "isrc": isrc,
                    "track_title": title,
                    "artist": artist,
                    "discrepancy_type": "UNREGISTERED",
                    "expected_amount": round(total_gross, 2),
                    "paid_amount": 0.00,
                    "shortfall": round(total_gross, 2),
                    "details": "No registration record found",
                })
                continue

            # Split anomaly check
            split_sum = sum(r["split_pct"] for r in regs)
            if abs(split_sum - 100.0) > split_tolerance:
                discrepancies.append({
                    "isrc": isrc,
                    "track_title": title,
                    "artist": artist,
                    "discrepancy_type": "SPLIT_ANOMALY",
                    "expected_amount": 100.00,
                    "paid_amount": round(split_sum, 2),
                    "shortfall": 0.00,
                    "details": (
                        f"Split sum is {split_sum:.2f}%, "
                        f"deviates from 100%"
                    ),
                })

            # Expected net (per period, per payee, rounded individually)
            territory = regs[0].get("territory", "US")
            commission_rate = commissions.get(territory, 0.10)

            total_expected_net = 0.0
            for period_label, p_entries in entries_by_period.items():
                period_gross = sum(
                    e["stream_count"] * rates.get(e["platform"], 0)
                    for e in p_entries
                )
                for reg in regs:
                    payee_net = (
                        period_gross
                        * reg["split_pct"]
                        / 100.0
                        * (1 - commission_rate)
                    )
                    total_expected_net += round(payee_net, 2)
            total_expected_net = round(total_expected_net, 2)

            # --- payment tool call ---
            payment_result = self.tools["get_payment_history"](isrc=isrc)
            payments = payment_result.get("payments", [])
            total_paid = round(sum(p["amount"] for p in payments), 2)

            if not payments:
                discrepancies.append({
                    "isrc": isrc,
                    "track_title": title,
                    "artist": artist,
                    "discrepancy_type": "UNPAID",
                    "expected_amount": total_expected_net,
                    "paid_amount": 0.00,
                    "shortfall": total_expected_net,
                    "details": "No payment records found",
                })
            elif total_expected_net - total_paid > shortfall_threshold:
                discrepancies.append({
                    "isrc": isrc,
                    "track_title": title,
                    "artist": artist,
                    "discrepancy_type": "UNDERPAID",
                    "expected_amount": total_expected_net,
                    "paid_amount": total_paid,
                    "shortfall": round(
                        total_expected_net - total_paid, 2
                    ),
                    "details": (
                        f"Paid {total_paid:.2f} of expected "
                        f"{total_expected_net:.2f}"
                    ),
                })

        # Sort by type then ISRC
        discrepancies.sort(key=lambda x: (x["discrepancy_type"], x["isrc"]))

        # 6. Write discrepancy_report.csv
        fieldnames = [
            "isrc", "track_title", "artist", "discrepancy_type",
            "expected_amount", "paid_amount", "shortfall", "details",
        ]
        report_path = os.path.join(self.workspace, "discrepancy_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for d in discrepancies:
                row = {}
                for k in fieldnames:
                    val = d[k]
                    if k in ("expected_amount", "paid_amount", "shortfall"):
                        row[k] = f"{float(val):.2f}"
                    else:
                        row[k] = val
                writer.writerow(row)

        # 7. Write summary.json
        from collections import Counter
        type_counts = Counter(d["discrepancy_type"] for d in discrepancies)
        summary = {
            "total_tracks_analyzed": len(unique_isrcs),
            "total_discrepancies": len(discrepancies),
            "unregistered_count": type_counts.get("UNREGISTERED", 0),
            "unpaid_count": type_counts.get("UNPAID", 0),
            "underpaid_count": type_counts.get("UNDERPAID", 0),
            "split_anomaly_count": type_counts.get("SPLIT_ANOMALY", 0),
            "total_shortfall": round(
                sum(d["shortfall"] for d in discrepancies), 2
            ),
        }
        with open(os.path.join(self.workspace, "summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        # 8. Construct action string
        action = (
            f"Analysis complete. Found {len(discrepancies)} total discrepancies "
            f"across {len(unique_isrcs)} analyzed tracks. "
            f"Unregistered: {type_counts.get('UNREGISTERED', 0)}, "
            f"Unpaid: {type_counts.get('UNPAID', 0)}, "
            f"Underpaid: {type_counts.get('UNDERPAID', 0)}, "
            f"Split anomalies: {type_counts.get('SPLIT_ANOMALY', 0)}. "
            f"Total shortfall: ${summary['total_shortfall']:.2f} USD."
        )

        return self.step(action)
