"""Brand reputation monitoring – task environment."""

from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import yaml
import re


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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="Lists brands under monitoring, paginated. Returns brand_id, brand_name, industry, and region for each brand.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of results per page (default 20, max 50)",
                },
            },
            "required": ["page"],
        },
    )
    def list_brands(self, page: int, page_size: int = 20):
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM brands").fetchone()[0]
        rows = c.execute(
            "SELECT id, name, industry, region FROM brands ORDER BY id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        brands = [
            {"brand_id": r[0], "brand_name": r[1], "industry": r[2], "region": r[3]}
            for r in rows
        ]
        return {"brands": brands, "page": page, "page_size": page_size,
                "total": total, "has_more": offset + page_size < total}

    @tool(
        description="Retrieves full details for a single brand by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
            },
            "required": ["brand_id"],
        },
    )
    def get_brand_details(self, brand_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, name, industry, region, stock_ticker, employee_count FROM brands WHERE id=?",
            (brand_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Brand {brand_id} not found"}
        return {"brand_id": row[0], "brand_name": row[1], "industry": row[2],
                "region": row[3], "stock_ticker": row[4], "employee_count": row[5]}

    @tool(
        description="Returns daily social-media metrics (mention_count, engagement_score) for a brand across all tracked platforms and dates.",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
            },
            "required": ["brand_id"],
        },
    )
    def get_social_media_metrics(self, brand_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = c.execute(
            "SELECT date, platform, mention_count, engagement_score "
            "FROM social_media_metrics WHERE brand_id=? ORDER BY date, platform",
            (brand_id,),
        ).fetchall()
        conn.close()
        metrics = [
            {"date": r[0], "platform": r[1], "mention_count": r[2], "engagement_score": r[3]}
            for r in rows
        ]
        return {"brand_id": brand_id, "metrics": metrics}

    @tool(
        description="Searches news headlines for a specific brand, paginated. Returns headline text, source, date, and category.",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
                "page": {"type": "integer", "description": "Page number (1-indexed, default 1)"},
                "page_size": {"type": "integer", "description": "Results per page (default 20, max 50)"},
            },
            "required": ["brand_id"],
        },
    )
    def search_headlines(self, brand_id: int, page: int = 1, page_size: int = 20):
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM news_headlines WHERE brand_id=?", (brand_id,)).fetchone()[0]
        rows = c.execute(
            "SELECT id, headline, source, published_date, category "
            "FROM news_headlines WHERE brand_id=? ORDER BY id LIMIT ? OFFSET ?",
            (brand_id, page_size, offset),
        ).fetchall()
        conn.close()
        headlines = [
            {"headline_id": r[0], "headline": r[1], "source": r[2],
             "published_date": r[3], "category": r[4]}
            for r in rows
        ]
        return {"brand_id": brand_id, "headlines": headlines,
                "page": page, "total": total, "has_more": offset + page_size < total}

    @tool(
        description="Lists support tickets for a brand, paginated. Returns ticket_id, subject, category, created_date, status, and customer_tier (body text is not included; use get_ticket_content for full text).",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
                "page": {"type": "integer", "description": "Page number (1-indexed, default 1)"},
                "page_size": {"type": "integer", "description": "Results per page (default 20, max 50)"},
            },
            "required": ["brand_id"],
        },
    )
    def get_support_tickets(self, brand_id: int, page: int = 1, page_size: int = 20):
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM support_tickets WHERE brand_id=?", (brand_id,)).fetchone()[0]
        rows = c.execute(
            "SELECT id, subject, category, created_date, status, customer_tier "
            "FROM support_tickets WHERE brand_id=? ORDER BY id LIMIT ? OFFSET ?",
            (brand_id, page_size, offset),
        ).fetchall()
        conn.close()
        tickets = [
            {"ticket_id": r[0], "subject": r[1], "category": r[2],
             "created_date": r[3], "status": r[4], "customer_tier": r[5]}
            for r in rows
        ]
        return {"brand_id": brand_id, "tickets": tickets,
                "page": page, "total": total, "has_more": offset + page_size < total}

    @tool(
        description="Retrieves the full content of a single support ticket, including the body text.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "integer", "description": "The ticket identifier"},
            },
            "required": ["ticket_id"],
        },
    )
    def get_ticket_content(self, ticket_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, brand_id, subject, body, category, created_date, status, customer_tier "
            "FROM support_tickets WHERE id=?",
            (ticket_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Ticket {ticket_id} not found"}
        return {"ticket_id": row[0], "brand_id": row[1], "subject": row[2],
                "body": row[3], "category": row[4], "created_date": row[5],
                "status": row[6], "customer_tier": row[7]}

    @tool(
        description="Lists executive communications for a brand, paginated. Returns comm_id, comm_type, title, date, and spokesperson (summary text is not included; use get_comm_content for details).",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {"type": "integer", "description": "The brand identifier"},
                "page": {"type": "integer", "description": "Page number (1-indexed, default 1)"},
                "page_size": {"type": "integer", "description": "Results per page (default 20, max 50)"},
            },
            "required": ["brand_id"],
        },
    )
    def get_executive_comms(self, brand_id: int, page: int = 1, page_size: int = 20):
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        total = c.execute(
            "SELECT COUNT(*) FROM executive_communications WHERE brand_id=?", (brand_id,),
        ).fetchone()[0]
        rows = c.execute(
            "SELECT id, comm_type, title, date, spokesperson "
            "FROM executive_communications WHERE brand_id=? ORDER BY id LIMIT ? OFFSET ?",
            (brand_id, page_size, offset),
        ).fetchall()
        conn.close()
        comms = [
            {"comm_id": r[0], "comm_type": r[1], "title": r[2],
             "date": r[3], "spokesperson": r[4]}
            for r in rows
        ]
        return {"brand_id": brand_id, "communications": comms,
                "page": page, "total": total, "has_more": offset + page_size < total}

    @tool(
        description="Retrieves the full content of a single executive communication, including the summary text.",
        parameters={
            "type": "object",
            "properties": {
                "comm_id": {"type": "integer", "description": "The communication identifier"},
            },
            "required": ["comm_id"],
        },
    )
    def get_comm_content(self, comm_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute(
            "SELECT id, brand_id, comm_type, title, summary, date, spokesperson "
            "FROM executive_communications WHERE id=?",
            (comm_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Communication {comm_id} not found"}
        return {"comm_id": row[0], "brand_id": row[1], "comm_type": row[2],
                "title": row[3], "summary": row[4], "date": row[5],
                "spokesperson": row[6]}

    # ------------------------------------------------------------------
    # Internal helpers for ground-truth computation
    # ------------------------------------------------------------------

    def _read_workspace_configs(self):
        """Read all workspace configuration and data files, return structured dicts."""
        ws = self.workspace

        with open(os.path.join(ws, "anomaly_config.yaml")) as f:
            anomaly_config = yaml.safe_load(f)
        with open(os.path.join(ws, "sentiment_rules.json")) as f:
            sentiment_rules = json.load(f)
        with open(os.path.join(ws, "priority_matrix.json")) as f:
            priority_matrix = json.load(f)

        # Brand tiers
        brand_tiers = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("brand_tier_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname), newline="") as f:
                    for row in csv.DictReader(f):
                        brand_tiers[int(row["brand_id"])] = row["monitoring_tier"]

        # Social baselines
        baselines = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("social_baseline_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    data = json.load(f)
                    for bid_str, stats in data.items():
                        baselines[int(bid_str)] = stats

        # Ticket severity overrides
        ticket_overrides = {}
        block_pattern = re.compile(
            r"=== Brand:[^=]*?\(ID:\s*(\d+)\s*\)\s*===\s*(.*?)(?=(?:\n=== Brand:)|\Z)",
            re.DOTALL,
        )
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("ticket_notes_") and fname.endswith(".txt"):
                with open(os.path.join(ws, fname)) as f:
                    content = f.read()
                for m in block_pattern.finditer(content):
                    bid = int(m.group(1))
                    sev_match = re.search(r"Overall ticket severity:\s*(\w+)", m.group(2))
                    if sev_match:
                        ticket_overrides[bid] = sev_match.group(1)

        # Exec watchlists
        exec_watchlists = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("exec_watchlist_") and fname.endswith(".yaml"):
                with open(os.path.join(ws, fname)) as f:
                    data = yaml.safe_load(f)
                    if data:
                        for entry in data:
                            exec_watchlists[entry["brand_id"]] = entry

        return {
            "anomaly_config": anomaly_config,
            "sentiment_rules": sentiment_rules,
            "priority_matrix": priority_matrix,
            "brand_tiers": brand_tiers,
            "baselines": baselines,
            "ticket_overrides": ticket_overrides,
            "exec_watchlists": exec_watchlists,
        }

    def _compute_ground_truth(self):
        """Compute the expected alert queue from DB + workspace files."""
        cfg = self._read_workspace_configs()
        pm = cfg["priority_matrix"]
        sr = cfg["sentiment_rules"]
        z_threshold = cfg["anomaly_config"]["z_score_threshold"]

        neg_kw = [k.lower() for k in sr["negative_keywords"]]
        crit_kw = [k.lower() for k in sr["critical_keywords"]]
        crisis_kw = [k.lower() for k in sr["crisis_keywords"]]
        weights = pm["weights"]
        scaling = pm["signal_scaling"]
        tier_mults = pm["tier_multipliers"]
        sev_mults = pm["severity_override_multipliers"]
        risk_mults = pm["risk_assessment_multipliers"]

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        brands = c.execute("SELECT id, name FROM brands ORDER BY id").fetchall()

        alerts = []
        for brand_id, brand_name in brands:
            # --- Social anomaly ---
            rows = c.execute(
                "SELECT date, SUM(mention_count) FROM social_media_metrics "
                "WHERE brand_id=? GROUP BY date", (brand_id,),
            ).fetchall()
            daily_vals = [r[1] for r in rows]
            current_avg = sum(daily_vals) / len(daily_vals) if daily_vals else 0
            bl = cfg["baselines"].get(brand_id, {"mean": current_avg, "std": 1.0})
            z_score = (current_avg - bl["mean"]) / bl["std"] if bl["std"] > 0 else 0.0
            anomaly_raw = max(0.0, z_score)

            # --- Headline sentiment ---
            hrows = c.execute(
                "SELECT headline FROM news_headlines WHERE brand_id=?", (brand_id,),
            ).fetchall()
            neg_h, crit_h = 0, 0
            for (h,) in hrows:
                hl = h.lower()
                if any(kw in hl for kw in crit_kw):
                    crit_h += 1
                elif any(kw in hl for kw in neg_kw):
                    neg_h += 1
            headline_raw = (neg_h + 2 * crit_h) / max(1, len(hrows))

            # --- Ticket sentiment ---
            trows = c.execute(
                "SELECT subject, body FROM support_tickets WHERE brand_id=?", (brand_id,),
            ).fetchall()
            neg_t = 0
            for subj, body in trows:
                text = (subj + " " + body).lower()
                if any(kw in text for kw in neg_kw):
                    neg_t += 1
            ticket_base = neg_t / max(1, len(trows))
            override = cfg["ticket_overrides"].get(brand_id, "normal")
            ticket_raw = ticket_base * sev_mults.get(override, 1.0)

            # --- Exec comms risk ---
            erows = c.execute(
                "SELECT spokesperson, summary FROM executive_communications WHERE brand_id=?",
                (brand_id,),
            ).fetchall()
            wl = cfg["exec_watchlists"].get(brand_id, {})
            watched = wl.get("watched_executives", [])
            exec_flag = 0
            for spk, summ in erows:
                if spk in watched and any(kw in summ.lower() for kw in crisis_kw):
                    exec_flag = 1
                    break
            risk_level = wl.get("risk_assessment", "medium")
            exec_raw = exec_flag * risk_mults.get(risk_level, 1.0)

            # --- Combined severity ---
            raw_severity = (
                weights["social_anomaly"] * anomaly_raw * scaling["social_anomaly"]
                + weights["headline_sentiment"] * headline_raw * scaling["headline_sentiment"]
                + weights["ticket_sentiment"] * ticket_raw * scaling["ticket_sentiment"]
                + weights["executive_comms"] * exec_raw * scaling["executive_comms"]
            )
            tier = cfg["brand_tiers"].get(brand_id, "silver")
            severity = round(raw_severity * tier_mults.get(tier, 1.0), 2)

            if severity >= pm["alert_threshold"]:
                alerts.append({
                    "rank": 0,
                    "brand_id": brand_id,
                    "brand_name": brand_name,
                    "monitoring_tier": tier,
                    "severity_score": severity,
                    "social_zscore": round(z_score, 2),
                    "headline_risk": round(headline_raw, 4),
                    "ticket_negativity": round(ticket_raw, 4),
                    "exec_risk_flag": exec_flag,
                })

        conn.close()

        alerts.sort(key=lambda a: (-a["severity_score"], a["brand_id"]))
        for i, a in enumerate(alerts):
            a["rank"] = i + 1

        return alerts

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------

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
        expected_ids = {a["brand_id"] for a in expected}
        expected_map = {a["brand_id"]: a for a in expected}

        eval_criteria: Dict[str, Any] = {}

        # --- 1. alert_queue.csv exists with correct columns (10 pts) ---
        csv_path = os.path.join(self.workspace, "alert_queue.csv")
        required_cols = ["rank", "brand_id", "brand_name", "monitoring_tier",
                         "severity_score", "social_zscore", "headline_risk",
                         "ticket_negativity", "exec_risk_flag"]
        actual_alerts = []
        csv_ok = False
        if os.path.isfile(csv_path):
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                    if all(c in cols for c in required_cols):
                        csv_ok = True
                        for row in reader:
                            actual_alerts.append(row)
            except Exception:
                pass
        eval_criteria["alert_queue_format"] = {
            "passed": csv_ok,
            "score": 10 if csv_ok else 0,
            "max_score": 10,
            "reason": "" if csv_ok else "alert_queue.csv missing or has wrong columns",
        }

        # Parse actual alerts
        actual_parsed = []
        for row in actual_alerts:
            try:
                actual_parsed.append({
                    "brand_id": int(row["brand_id"]),
                    "brand_name": row["brand_name"].strip(),
                    "severity_score": float(row["severity_score"]),
                    "social_zscore": float(row["social_zscore"]),
                    "headline_risk": float(row["headline_risk"]),
                    "ticket_negativity": float(row["ticket_negativity"]),
                    "exec_risk_flag": int(row["exec_risk_flag"]),
                    "monitoring_tier": row["monitoring_tier"].strip(),
                })
            except (KeyError, ValueError):
                continue
        actual_ids = {a["brand_id"] for a in actual_parsed}
        actual_map = {a["brand_id"]: a for a in actual_parsed}

        # --- 2. Correct brands identified (20 pts) ---
        if expected_ids or actual_ids:
            jaccard = len(expected_ids & actual_ids) / len(expected_ids | actual_ids)
        else:
            jaccard = 1.0
        brand_score = round(jaccard * 20)
        eval_criteria["correct_brands"] = {
            "passed": expected_ids == actual_ids,
            "score": brand_score,
            "max_score": 20,
            "reason": "" if expected_ids == actual_ids else f"Expected {len(expected_ids)} brands, got {len(actual_ids)}; overlap {len(expected_ids & actual_ids)}",
        }

        # --- 3. Correct severity scores (20 pts) ---
        common = expected_ids & actual_ids
        sev_correct = 0
        for bid in common:
            if abs(expected_map[bid]["severity_score"] - actual_map[bid]["severity_score"]) <= 1.0:
                sev_correct += 1
        sev_score = round(sev_correct / max(1, len(expected_ids)) * 20)
        eval_criteria["correct_severity_scores"] = {
            "passed": sev_correct == len(expected_ids),
            "score": sev_score,
            "max_score": 20,
            "reason": "" if sev_correct == len(expected_ids) else f"{sev_correct}/{len(expected_ids)} scores within tolerance",
        }

        # --- 4. Correct ranking order (15 pts) ---
        actual_order = [a["brand_id"] for a in actual_parsed]
        expected_order = [a["brand_id"] for a in expected]
        if actual_order == expected_order:
            rank_pts = 15
        elif len(actual_order) > 0 and len(expected_order) > 0:
            # Count pairwise correct orderings among common brands
            common_expected = [b for b in expected_order if b in actual_ids]
            common_actual = [b for b in actual_order if b in expected_ids]
            if len(common_expected) > 1:
                pairs_total = 0
                pairs_correct = 0
                for i in range(len(common_expected)):
                    for j in range(i + 1, len(common_expected)):
                        pairs_total += 1
                        bi, bj = common_expected[i], common_expected[j]
                        if bi in common_actual and bj in common_actual:
                            if common_actual.index(bi) < common_actual.index(bj):
                                pairs_correct += 1
                rank_pts = round(pairs_correct / max(1, pairs_total) * 15)
            else:
                rank_pts = 15 if set(common_expected) == set(common_actual) else 0
        else:
            rank_pts = 0
        eval_criteria["correct_ranking"] = {
            "passed": actual_order == expected_order,
            "score": rank_pts,
            "max_score": 15,
        }

        # --- 5. Correct signal values (social_zscore, headline_risk, ticket_negativity, exec_risk_flag) (15 pts) ---
        signal_correct = 0
        signal_total = 0
        for bid in common:
            ea = expected_map[bid]
            aa = actual_map[bid]
            for key, tol in [("social_zscore", 0.5), ("headline_risk", 0.05),
                             ("ticket_negativity", 0.05), ("exec_risk_flag", 0.01)]:
                signal_total += 1
                if abs(ea[key] - aa[key]) <= tol:
                    signal_correct += 1
        sig_pts = round(signal_correct / max(1, signal_total) * 15)
        eval_criteria["correct_signal_values"] = {
            "passed": signal_correct == signal_total,
            "score": sig_pts,
            "max_score": 15,
            "reason": "" if signal_correct == signal_total else f"{signal_correct}/{signal_total} signal values correct",
        }

        # --- 6. brand_risk_summary.json valid (10 pts) ---
        summary_path = os.path.join(self.workspace, "brand_risk_summary.json")
        summary_ok = False
        if os.path.isfile(summary_path):
            try:
                with open(summary_path) as f:
                    sdata = json.load(f)
                if "total_alerts" in sdata and "alerts" in sdata:
                    if sdata["total_alerts"] == len(expected):
                        summary_ok = True
            except Exception:
                pass
        eval_criteria["brand_risk_summary"] = {
            "passed": summary_ok,
            "score": 10 if summary_ok else 0,
            "max_score": 10,
            "reason": "" if summary_ok else "brand_risk_summary.json missing, malformed, or wrong total_alerts count",
        }

        # --- 7. Action string contains correct count and priority list (10 pts) ---
        action_pts = 0
        # Check "Total alerts: N"
        count_match = re.search(r"Total alerts:\s*(\d+)", action)
        if count_match and int(count_match.group(1)) == len(expected):
            action_pts += 5
        # Check "Priority order: brand1, brand2, ..."
        order_match = re.search(r"Priority order:\s*(.+)", action)
        if order_match and expected:
            listed_names = [n.strip() for n in order_match.group(1).split(",")]
            expected_names = [a["brand_name"] for a in expected]
            if listed_names == expected_names:
                action_pts += 5
            elif set(listed_names) == set(expected_names):
                action_pts += 2
        elif not expected:
            action_pts += 5  # no alerts expected
        eval_criteria["action_string"] = {
            "passed": action_pts == 10,
            "score": action_pts,
            "max_score": 10,
        }

        total_score = sum(v["score"] for v in eval_criteria.values())
        max_score = sum(v["max_score"] for v in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------

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
        ws = self.workspace

        # ------ 1. Read workspace config files ------
        with open(os.path.join(ws, "anomaly_config.yaml")) as f:
            anomaly_config = yaml.safe_load(f)
        with open(os.path.join(ws, "sentiment_rules.json")) as f:
            sentiment_rules = json.load(f)
        with open(os.path.join(ws, "priority_matrix.json")) as f:
            priority_matrix = json.load(f)

        neg_kw = [k.lower() for k in sentiment_rules["negative_keywords"]]
        crit_kw = [k.lower() for k in sentiment_rules["critical_keywords"]]
        crisis_kw = [k.lower() for k in sentiment_rules["crisis_keywords"]]
        weights = priority_matrix["weights"]
        scaling = priority_matrix["signal_scaling"]
        tier_mults = priority_matrix["tier_multipliers"]
        sev_mults = priority_matrix["severity_override_multipliers"]
        risk_mults = priority_matrix["risk_assessment_multipliers"]

        # ------ 2. Read brand tiers from workspace CSVs ------
        brand_tiers = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("brand_tier_") and fname.endswith(".csv"):
                with open(os.path.join(ws, fname), newline="") as f:
                    for row in csv.DictReader(f):
                        brand_tiers[int(row["brand_id"])] = row["monitoring_tier"]

        # ------ 3. Read social baselines from workspace JSONs ------
        baselines = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("social_baseline_") and fname.endswith(".json"):
                with open(os.path.join(ws, fname)) as f:
                    data = json.load(f)
                    for bid_str, stats in data.items():
                        baselines[int(bid_str)] = stats

        # ------ 4. Read ticket severity overrides from workspace TXTs ------
        ticket_overrides = {}
        block_pattern = re.compile(
            r"=== Brand:[^=]*?\(ID:\s*(\d+)\s*\)\s*===\s*(.*?)(?=(?:\n=== Brand:)|\Z)",
            re.DOTALL,
        )
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("ticket_notes_") and fname.endswith(".txt"):
                with open(os.path.join(ws, fname)) as f:
                    content = f.read()
                for m in block_pattern.finditer(content):
                    bid = int(m.group(1))
                    sev_match = re.search(r"Overall ticket severity:\s*(\w+)", m.group(2))
                    if sev_match:
                        ticket_overrides[bid] = sev_match.group(1)

        # ------ 5. Read exec watchlists from workspace YAMLs ------
        exec_watchlists = {}
        for fname in sorted(os.listdir(ws)):
            if fname.startswith("exec_watchlist_") and fname.endswith(".yaml"):
                with open(os.path.join(ws, fname)) as f:
                    data = yaml.safe_load(f)
                    if data:
                        for entry in data:
                            exec_watchlists[entry["brand_id"]] = entry

        # ------ 6. Retrieve all brands via tool ------
        all_brands = []
        page = 1
        while True:
            result = self.tools["list_brands"](page=page, page_size=50)
            all_brands.extend(result["brands"])
            if not result["has_more"]:
                break
            page += 1

        # ------ 7. For each brand compute signals ------
        alerts = []
        for brand in all_brands:
            bid = brand["brand_id"]

            # --- Social anomaly ---
            sm = self.tools["get_social_media_metrics"](brand_id=bid)
            daily_totals: Dict[str, int] = {}
            for m in sm["metrics"]:
                daily_totals[m["date"]] = daily_totals.get(m["date"], 0) + m["mention_count"]
            daily_vals = list(daily_totals.values())
            current_avg = sum(daily_vals) / len(daily_vals) if daily_vals else 0.0
            bl = baselines.get(bid, {"mean": current_avg, "std": 1.0})
            z_score = (current_avg - bl["mean"]) / bl["std"] if bl["std"] > 0 else 0.0
            anomaly_raw = max(0.0, z_score)

            # --- Headline sentiment ---
            all_headlines = []
            hpage = 1
            while True:
                hr = self.tools["search_headlines"](brand_id=bid, page=hpage, page_size=50)
                all_headlines.extend(hr["headlines"])
                if not hr["has_more"]:
                    break
                hpage += 1
            neg_h, crit_h = 0, 0
            for h in all_headlines:
                hl = h["headline"].lower()
                if any(kw in hl for kw in crit_kw):
                    crit_h += 1
                elif any(kw in hl for kw in neg_kw):
                    neg_h += 1
            headline_raw = (neg_h + 2 * crit_h) / max(1, len(all_headlines))

            # --- Ticket sentiment ---
            all_tickets = []
            tpage = 1
            while True:
                tr = self.tools["get_support_tickets"](brand_id=bid, page=tpage, page_size=50)
                all_tickets.extend(tr["tickets"])
                if not tr["has_more"]:
                    break
                tpage += 1
            neg_t = 0
            for t in all_tickets:
                tc = self.tools["get_ticket_content"](ticket_id=t["ticket_id"])
                text = (tc["subject"] + " " + tc["body"]).lower()
                if any(kw in text for kw in neg_kw):
                    neg_t += 1
            ticket_base = neg_t / max(1, len(all_tickets))
            override = ticket_overrides.get(bid, "normal")
            ticket_raw = ticket_base * sev_mults.get(override, 1.0)

            # --- Exec comms risk ---
            all_comms = []
            epage = 1
            while True:
                er = self.tools["get_executive_comms"](brand_id=bid, page=epage, page_size=50)
                all_comms.extend(er["communications"])
                if not er["has_more"]:
                    break
                epage += 1
            wl = exec_watchlists.get(bid, {})
            watched = wl.get("watched_executives", [])
            exec_flag = 0
            for cm in all_comms:
                if cm["spokesperson"] in watched:
                    detail = self.tools["get_comm_content"](comm_id=cm["comm_id"])
                    if any(kw in detail["summary"].lower() for kw in crisis_kw):
                        exec_flag = 1
                        break
            risk_level = wl.get("risk_assessment", "medium")
            exec_raw = exec_flag * risk_mults.get(risk_level, 1.0)

            # --- Combined severity ---
            raw_severity = (
                weights["social_anomaly"] * anomaly_raw * scaling["social_anomaly"]
                + weights["headline_sentiment"] * headline_raw * scaling["headline_sentiment"]
                + weights["ticket_sentiment"] * ticket_raw * scaling["ticket_sentiment"]
                + weights["executive_comms"] * exec_raw * scaling["executive_comms"]
            )
            tier = brand_tiers.get(bid, "silver")
            severity = round(raw_severity * tier_mults.get(tier, 1.0), 2)

            if severity >= priority_matrix["alert_threshold"]:
                alerts.append({
                    "brand_id": bid,
                    "brand_name": brand["brand_name"],
                    "monitoring_tier": tier,
                    "severity_score": severity,
                    "social_zscore": round(z_score, 2),
                    "headline_risk": round(headline_raw, 4),
                    "ticket_negativity": round(ticket_raw, 4),
                    "exec_risk_flag": exec_flag,
                })

        # ------ 8. Sort and rank ------
        alerts.sort(key=lambda a: (-a["severity_score"], a["brand_id"]))
        for i, a in enumerate(alerts):
            a["rank"] = i + 1

        # ------ 9. Write alert_queue.csv ------
        csv_path = os.path.join(ws, "alert_queue.csv")
        fieldnames = ["rank", "brand_id", "brand_name", "monitoring_tier",
                       "severity_score", "social_zscore", "headline_risk",
                       "ticket_negativity", "exec_risk_flag"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in alerts:
                writer.writerow(a)

        # ------ 10. Write brand_risk_summary.json ------
        summary_path = os.path.join(ws, "brand_risk_summary.json")
        summary_data = {
            "total_alerts": len(alerts),
            "alerts": alerts,
        }
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)

        # ------ 11. Construct action string ------
        brand_list = ", ".join(a["brand_name"] for a in alerts)
        action = f"Total alerts: {len(alerts)}\nPriority order: {brand_list}"

        return self.step(action)
