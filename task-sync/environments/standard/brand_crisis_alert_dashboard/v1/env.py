import sqlite3
import os
import csv
import json
import math
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

    # ------------------------------------------------------------------ tools

    @tool(
        description="List brands with pagination. Returns brand_id, brand_name, industry, and region for each brand.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of brands per page (default 20, max 50)",
                },
            },
            "required": ["page"],
        },
    )
    def list_brands(self, page: int = 1, page_size: int = 20) -> dict:
        page_size = min(page_size, 50)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM brands")
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT brand_id, brand_name, industry, region FROM brands ORDER BY brand_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        brands = [dict(r) for r in cur.fetchall()]
        conn.close()
        return _envelope({
            "brands": brands,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })

    @tool(
        description="Get aggregated sentiment statistics for a brand. Returns the mean sentiment score, total comment count, and percentage breakdown by label (positive/negative/neutral) across all comments on the brand's posts.",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {
                    "type": "integer",
                    "description": "The brand ID to query sentiment for",
                },
            },
            "required": ["brand_id"],
        },
    )
    def get_brand_sentiment(self, brand_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.sentiment_score, c.sentiment_label
            FROM comments c
            JOIN posts p ON c.post_id = p.post_id
            WHERE p.brand_id = ?
            """,
            (brand_id,),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return json.dumps({
                "brand_id": brand_id,
                "avg_sentiment": 0.0,
                "total_comments": 0,
                "negative_pct": 0.0,
                "positive_pct": 0.0,
                "neutral_pct": 0.0,
            }, ensure_ascii=False, default=str)
        scores = [r[0] for r in rows]
        labels = [r[1] for r in rows]
        total = len(rows)
        neg = sum(1 for l in labels if l == "negative")
        pos = sum(1 for l in labels if l == "positive")
        neu = sum(1 for l in labels if l == "neutral")
        return json.dumps({
            "brand_id": brand_id,
            "avg_sentiment": round(sum(scores) / total, 4),
            "total_comments": total,
            "negative_pct": round(neg / total * 100, 2),
            "positive_pct": round(pos / total * 100, 2),
            "neutral_pct": round(neu / total * 100, 2),
        }, ensure_ascii=False, default=str)

    @tool(
        description="Get posts made by influencers that mention a specific brand. Returns post details including the influencer_id of the author.",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {
                    "type": "integer",
                    "description": "The brand ID to look up influencer posts for",
                },
            },
            "required": ["brand_id"],
        },
    )
    def get_influencer_posts(self, brand_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT post_id, brand_id, author_id AS influencer_id, platform,
                   post_date, content_snippet, engagement_count
            FROM posts
            WHERE brand_id = ? AND is_by_influencer = 1
            ORDER BY post_id
            """,
            (brand_id,),
        )
        posts = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({"brand_id": brand_id, "posts": posts}, ensure_ascii=False, default=str)

    @tool(
        description="Get detailed account information for a specific influencer, including verification status and follower count.",
        parameters={
            "type": "object",
            "properties": {
                "influencer_id": {
                    "type": "integer",
                    "description": "The influencer ID to look up",
                },
            },
            "required": ["influencer_id"],
        },
    )
    def get_influencer_info(self, influencer_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT influencer_id, handle, platform, follower_count, is_verified, niche FROM influencers WHERE influencer_id = ?",
            (influencer_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"Influencer {influencer_id} not found"})
        result = dict(row)
        result["is_verified"] = bool(result["is_verified"])
        return _envelope(result)

    @tool(
        description="Get all product mentions associated with a brand, including product name, mention type (complaint/praise/neutral/question), and severity tag (low/medium/high/critical).",
        parameters={
            "type": "object",
            "properties": {
                "brand_id": {
                    "type": "integer",
                    "description": "The brand ID to look up product mentions for",
                },
            },
            "required": ["brand_id"],
        },
    )
    def get_product_mentions(self, brand_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT mention_id, post_id, product_name, mention_type, severity_tag
            FROM product_mentions
            WHERE brand_id = ?
            ORDER BY mention_id
            """,
            (brand_id,),
        )
        mentions = [dict(r) for r in cur.fetchall()]
        conn.close()
        return json.dumps({"brand_id": brand_id, "mentions": mentions}, ensure_ascii=False, default=str)

    @tool(
        description="Get detailed information about a specific social media post, including author, platform, date, engagement count, and whether it was posted by an influencer.",
        parameters={
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "integer",
                    "description": "The post ID to look up",
                },
            },
            "required": ["post_id"],
        },
    )
    def get_post_details(self, post_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT post_id, brand_id, author_id, platform, post_date, content_snippet, engagement_count, is_by_influencer FROM posts WHERE post_id = ?",
            (post_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return _envelope({"error": f"Post {post_id} not found"})
        result = dict(row)
        result["is_by_influencer"] = bool(result["is_by_influencer"])
        return _envelope(result)

    # ----------------------------------------------------------- evaluation

    def _compute_ground_truth(self):
        """Compute the full ground-truth dashboard from DB + workspace files."""
        import glob as glob_mod
        import yaml

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # -- config files --
        with open(os.path.join(self.workspace, "crisis_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            weights = json.load(f)

        tiers = {}
        with open(os.path.join(self.workspace, "brand_tiers.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                tiers[int(row["brand_id"])] = float(row["priority_multiplier"])

        baselines = {}
        with open(os.path.join(self.workspace, "baseline_volumes.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                baselines[int(row["brand_id"])] = float(row["avg_daily_volume"])

        # -- monitoring reports --
        recent_volumes: Dict[int, Dict[str, int]] = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "monitoring_report_*.csv"))):
            with open(fp) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bid = int(row["brand_id"])
                    date = row["date"]
                    count = int(row["post_count"])
                    recent_volumes.setdefault(bid, {}).setdefault(date, 0)
                    recent_volumes[bid][date] += count

        spike_ratios = {}
        for bid, date_counts in recent_volumes.items():
            avg_daily = sum(date_counts.values()) / len(date_counts) if date_counts else 0
            bl = baselines.get(bid, 1)
            spike_ratios[bid] = (avg_daily / bl) if bl > 0 else 0.0

        # -- brand names --
        brand_names = {}
        cur.execute("SELECT brand_id, brand_name FROM brands")
        for row in cur.fetchall():
            brand_names[row[0]] = row[1]

        # -- sentiment per brand --
        brand_sentiments = {}
        cur.execute(
            "SELECT p.brand_id, AVG(c.sentiment_score) "
            "FROM comments c JOIN posts p ON c.post_id = p.post_id "
            "GROUP BY p.brand_id"
        )
        for row in cur.fetchall():
            brand_sentiments[row[0]] = round(row[1], 4)

        # -- product mentions --
        brand_mention_data: Dict[int, dict] = defaultdict(
            lambda: {"total": 0, "critical": 0, "product_critical": defaultdict(int)}
        )
        cur.execute("SELECT brand_id, product_name, severity_tag FROM product_mentions")
        for row in cur.fetchall():
            bid = row[0]
            brand_mention_data[bid]["total"] += 1
            if row[2] == "critical":
                brand_mention_data[bid]["critical"] += 1
                brand_mention_data[bid]["product_critical"][row[1]] += 1

        brand_mentions = {}
        brand_primary_products = {}
        for bid, data in brand_mention_data.items():
            brand_mentions[bid] = {"total": data["total"], "critical": data["critical"]}
            if data["product_critical"]:
                max_cnt = max(data["product_critical"].values())
                candidates = sorted(
                    [p for p, c in data["product_critical"].items() if c == max_cnt]
                )
                brand_primary_products[bid] = candidates[0]
            else:
                brand_primary_products[bid] = ""

        # -- verified influencers per brand --
        brand_verified_inf: Dict[int, int] = defaultdict(int)
        cur.execute(
            "SELECT p.brand_id, p.author_id "
            "FROM posts p "
            "JOIN influencers i ON p.author_id = i.influencer_id "
            "WHERE p.is_by_influencer = 1 AND i.is_verified = 1"
        )
        _seen: Dict[int, set] = defaultdict(set)
        for row in cur.fetchall():
            _seen[row[0]].add(row[1])
        for bid, s in _seen.items():
            brand_verified_inf[bid] = len(s)

        conn.close()

        # -- identify crisis brands & score --
        spike_thr = config["volume_spike_multiplier"]
        sent_thr = config["sentiment_threshold"]
        min_crit = config["min_critical_mentions"]

        w_vol = weights["volume_spike_weight"]
        w_sent = weights["sentiment_weight"]
        w_inf = weights["influencer_weight"]
        w_prod = weights["product_mention_weight"]

        dashboard = []
        for bid in spike_ratios:
            sr = spike_ratios.get(bid, 0)
            avg_s = brand_sentiments.get(bid, 0)
            md = brand_mentions.get(bid, {"total": 0, "critical": 0})
            if sr < spike_thr or avg_s >= sent_thr or md["critical"] < min_crit:
                continue

            verified_inf = brand_verified_inf.get(bid, 0)
            crit_ratio = md["critical"] / md["total"] if md["total"] > 0 else 0

            vol_c = min(sr, 5.0) * (w_vol / 5.0)
            sent_c = min(abs(avg_s), 1.0) * w_sent
            inf_c = min(verified_inf, 5) * (w_inf / 5.0)
            prod_c = min(crit_ratio, 1.0) * w_prod

            crisis_score = round(vol_c + sent_c + inf_c + prod_c, 2)
            tier_mult = tiers.get(bid, 1.0)
            final_score = round(crisis_score * tier_mult, 2)

            alert_lvls = config["alert_levels"]
            if final_score >= alert_lvls["CRITICAL"]:
                alert_level = "CRITICAL"
            elif final_score >= alert_lvls["HIGH"]:
                alert_level = "HIGH"
            elif final_score >= alert_lvls["MEDIUM"]:
                alert_level = "MEDIUM"
            else:
                alert_level = "LOW"

            dashboard.append({
                "brand_name": brand_names.get(bid, ""),
                "brand_id": bid,
                "crisis_score": crisis_score,
                "final_score": final_score,
                "alert_level": alert_level,
                "spike_ratio": round(sr, 2),
                "avg_sentiment": round(avg_s, 2),
                "verified_influencer_count": verified_inf,
                "critical_mention_count": md["critical"],
                "primary_product": brand_primary_products.get(bid, ""),
            })

        dashboard.sort(key=lambda x: (-x["final_score"], x["brand_name"]))
        for i, row in enumerate(dashboard):
            row["priority_rank"] = i + 1

        return dashboard

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

        total_score = 0
        max_score = 0
        eval_criteria = {}

        expected_columns = [
            "priority_rank", "brand_name", "brand_id", "crisis_score",
            "final_score", "alert_level", "spike_ratio", "avg_sentiment",
            "verified_influencer_count", "critical_mention_count", "primary_product",
        ]
        dashboard_path = os.path.join(self.workspace, "crisis_dashboard.csv")

        # ---- Criterion 1: file structure (15 pts) ----
        max_score += 15
        agent_rows = []
        if os.path.exists(dashboard_path):
            with open(dashboard_path) as f:
                reader = csv.DictReader(f)
                cols = list(reader.fieldnames) if reader.fieldnames else []
                if cols == expected_columns:
                    agent_rows = list(reader)
                    eval_criteria["dashboard_structure"] = {
                        "passed": True, "score": 15, "max_score": 15,
                    }
                    total_score += 15
                else:
                    eval_criteria["dashboard_structure"] = {
                        "passed": False, "score": 0, "max_score": 15,
                        "reason": f"Column mismatch: expected {expected_columns}, got {cols}",
                    }
        else:
            eval_criteria["dashboard_structure"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "crisis_dashboard.csv not found in workspace",
            }

        # ---- Criterion 2: brand identification (25 pts) ----
        max_score += 25
        gt_ids = set(r["brand_id"] for r in gt)
        try:
            agent_ids = set(int(r["brand_id"]) for r in agent_rows)
        except Exception:
            agent_ids = set()

        if agent_ids == gt_ids and len(gt_ids) > 0:
            eval_criteria["brand_identification"] = {
                "passed": True, "score": 25, "max_score": 25,
            }
            total_score += 25
        else:
            correct = len(gt_ids & agent_ids)
            partial = int(25 * correct / len(gt_ids)) if gt_ids else 0
            eval_criteria["brand_identification"] = {
                "passed": False, "score": partial, "max_score": 25,
                "reason": f"Expected {sorted(gt_ids)}, got {sorted(agent_ids)}",
            }
            total_score += partial

        # ---- Criterion 3: crisis scores accuracy (20 pts) ----
        max_score += 20
        gt_scores = {r["brand_id"]: (r["crisis_score"], r["final_score"]) for r in gt}
        score_matches = 0
        for row in agent_rows:
            try:
                bid = int(row["brand_id"])
                cs = round(float(row["crisis_score"]), 2)
                fs = round(float(row["final_score"]), 2)
                if bid in gt_scores:
                    gcs, gfs = gt_scores[bid]
                    if abs(cs - gcs) < 0.02 and abs(fs - gfs) < 0.02:
                        score_matches += 1
            except Exception:
                pass
        total_gt = len(gt)
        if total_gt > 0:
            partial = int(20 * score_matches / total_gt)
            passed = score_matches == total_gt
        else:
            partial, passed = 0, False
        eval_criteria["crisis_scores"] = {
            "passed": passed, "score": partial, "max_score": 20,
        }
        if not passed:
            eval_criteria["crisis_scores"]["reason"] = f"{score_matches}/{total_gt} matched"
        total_score += partial

        # ---- Criterion 4: priority ranking (15 pts) ----
        max_score += 15
        gt_order = [r["brand_id"] for r in gt]
        try:
            agent_order = [int(r["brand_id"]) for r in agent_rows]
        except Exception:
            agent_order = []

        if agent_order == gt_order and len(gt_order) > 0:
            eval_criteria["priority_ranking"] = {
                "passed": True, "score": 15, "max_score": 15,
            }
            total_score += 15
        else:
            eval_criteria["priority_ranking"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": f"Expected order {gt_order}, got {agent_order}",
            }

        # ---- Criterion 5: alert levels (10 pts) ----
        max_score += 10
        gt_alerts = {r["brand_id"]: r["alert_level"] for r in gt}
        lvl_matches = 0
        for row in agent_rows:
            try:
                bid = int(row["brand_id"])
                if bid in gt_alerts and row["alert_level"].strip() == gt_alerts[bid]:
                    lvl_matches += 1
            except Exception:
                pass
        if total_gt > 0:
            partial = int(10 * lvl_matches / total_gt)
            passed = lvl_matches == total_gt
        else:
            partial, passed = 0, False
        eval_criteria["alert_levels"] = {
            "passed": passed, "score": partial, "max_score": 10,
        }
        if not passed:
            eval_criteria["alert_levels"]["reason"] = f"{lvl_matches}/{total_gt} matched"
        total_score += partial

        # ---- Criterion 6: response summary (15 pts) ----
        max_score += 15
        summary_pts = 0
        # 6a: total count in response (5 pts)
        if str(len(gt)) in action:
            summary_pts += 5
        # 6b: top-3 brand names in response (10 pts)
        top3_names = [r["brand_name"] for r in gt[:3]]
        action_lower = action.lower()
        names_found = sum(1 for n in top3_names if n.lower() in action_lower)
        if top3_names:
            summary_pts += int(10 * names_found / len(top3_names))
        eval_criteria["response_summary"] = {
            "passed": summary_pts == 15,
            "score": summary_pts,
            "max_score": 15,
        }
        if summary_pts < 15:
            eval_criteria["response_summary"]["reason"] = (
                f"Found {names_found}/{len(top3_names)} top names, count mention: {str(len(gt)) in action}"
            )
        total_score += summary_pts

        reward = total_score / max_score if max_score > 0 else 0.0
        return reward, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ----------------------------------------------------------- verify

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as glob_mod
        import yaml

        # -- read workspace config --
        with open(os.path.join(self.workspace, "crisis_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "scoring_weights.json")) as f:
            weights = json.load(f)

        tiers: Dict[int, float] = {}
        with open(os.path.join(self.workspace, "brand_tiers.csv")) as f:
            for row in csv.DictReader(f):
                tiers[int(row["brand_id"])] = float(row["priority_multiplier"])

        baselines: Dict[int, float] = {}
        with open(os.path.join(self.workspace, "baseline_volumes.csv")) as f:
            for row in csv.DictReader(f):
                baselines[int(row["brand_id"])] = float(row["avg_daily_volume"])

        # -- read monitoring reports --
        recent_volumes: Dict[int, Dict[str, int]] = {}
        for fp in sorted(glob_mod.glob(os.path.join(self.workspace, "monitoring_report_*.csv"))):
            with open(fp) as f:
                for row in csv.DictReader(f):
                    bid = int(row["brand_id"])
                    date = row["date"]
                    count = int(row["post_count"])
                    recent_volumes.setdefault(bid, {}).setdefault(date, 0)
                    recent_volumes[bid][date] += count

        spike_ratios: Dict[int, float] = {}
        for bid, dc in recent_volumes.items():
            avg_daily = sum(dc.values()) / len(dc) if dc else 0
            bl = baselines.get(bid, 1)
            spike_ratios[bid] = (avg_daily / bl) if bl > 0 else 0.0

        # -- get all brands via tool --
        tool_calls = 0
        all_brands: Dict[int, str] = {}
        page = 1
        while True:
            res = json.loads(self.tools["list_brands"](page=page)["content"][0]["text"])
            tool_calls += 1
            for b in res["brands"]:
                all_brands[b["brand_id"]] = b["brand_name"]
            if page >= res["total_pages"]:
                break
            page += 1

        # -- identify spike brands --
        spike_thr = config["volume_spike_multiplier"]
        sent_thr = config["sentiment_threshold"]
        min_crit = config["min_critical_mentions"]

        spike_brand_ids = [bid for bid, sr in spike_ratios.items() if sr >= spike_thr]

        # -- get sentiment for spike brands --
        brand_sentiments: Dict[int, float] = {}
        for bid in spike_brand_ids:
            res = json.loads(self.tools["get_brand_sentiment"](brand_id=bid))
            tool_calls += 1
            brand_sentiments[bid] = res["avg_sentiment"]

        sentiment_brand_ids = [bid for bid in spike_brand_ids if brand_sentiments.get(bid, 0) < sent_thr]

        # -- get product mentions --
        brand_mentions: Dict[int, dict] = {}
        brand_primary_products: Dict[int, str] = {}
        for bid in sentiment_brand_ids:
            res = json.loads(self.tools["get_product_mentions"](brand_id=bid))
            tool_calls += 1
            mentions = res["mentions"]
            total = len(mentions)
            critical = sum(1 for m in mentions if m["severity_tag"] == "critical")
            brand_mentions[bid] = {"total": total, "critical": critical}
            product_critical: Dict[str, int] = {}
            for m in mentions:
                if m["severity_tag"] == "critical":
                    product_critical[m["product_name"]] = product_critical.get(m["product_name"], 0) + 1
            if product_critical:
                max_cnt = max(product_critical.values())
                candidates = sorted(p for p, c in product_critical.items() if c == max_cnt)
                brand_primary_products[bid] = candidates[0]
            else:
                brand_primary_products[bid] = ""

        crisis_brand_ids = [
            bid for bid in sentiment_brand_ids
            if brand_mentions.get(bid, {}).get("critical", 0) >= min_crit
        ]

        # -- get influencer data --
        brand_verified_inf: Dict[int, int] = {}
        for bid in crisis_brand_ids:
            res = json.loads(self.tools["get_influencer_posts"](brand_id=bid))
            tool_calls += 1
            inf_ids = set()
            for post in res["posts"]:
                if post["influencer_id"] is not None:
                    inf_ids.add(post["influencer_id"])
            verified = 0
            for inf_id in inf_ids:
                info = json.loads(self.tools["get_influencer_info"](influencer_id=inf_id)["content"][0]["text"])
                tool_calls += 1
                if info.get("is_verified"):
                    verified += 1
            brand_verified_inf[bid] = verified

        # -- compute scores --
        w_vol = weights["volume_spike_weight"]
        w_sent = weights["sentiment_weight"]
        w_inf = weights["influencer_weight"]
        w_prod = weights["product_mention_weight"]

        dashboard_rows = []
        for bid in crisis_brand_ids:
            sr = spike_ratios[bid]
            avg_s = brand_sentiments[bid]
            vi = brand_verified_inf.get(bid, 0)
            md = brand_mentions[bid]
            cr = md["critical"] / md["total"] if md["total"] > 0 else 0

            vol_c = min(sr, 5.0) * (w_vol / 5.0)
            sent_c = min(abs(avg_s), 1.0) * w_sent
            inf_c = min(vi, 5) * (w_inf / 5.0)
            prod_c = min(cr, 1.0) * w_prod

            crisis_score = round(vol_c + sent_c + inf_c + prod_c, 2)
            tier_mult = tiers.get(bid, 1.0)
            final_score = round(crisis_score * tier_mult, 2)

            alert_lvls = config["alert_levels"]
            if final_score >= alert_lvls["CRITICAL"]:
                alert_level = "CRITICAL"
            elif final_score >= alert_lvls["HIGH"]:
                alert_level = "HIGH"
            elif final_score >= alert_lvls["MEDIUM"]:
                alert_level = "MEDIUM"
            else:
                alert_level = "LOW"

            dashboard_rows.append({
                "brand_name": all_brands[bid],
                "brand_id": bid,
                "crisis_score": crisis_score,
                "final_score": final_score,
                "alert_level": alert_level,
                "spike_ratio": round(sr, 2),
                "avg_sentiment": round(avg_s, 2),
                "verified_influencer_count": vi,
                "critical_mention_count": md["critical"],
                "primary_product": brand_primary_products.get(bid, ""),
            })

        dashboard_rows.sort(key=lambda x: (-x["final_score"], x["brand_name"]))
        for i, row in enumerate(dashboard_rows):
            row["priority_rank"] = i + 1

        # -- write dashboard --
        fieldnames = [
            "priority_rank", "brand_name", "brand_id", "crisis_score",
            "final_score", "alert_level", "spike_ratio", "avg_sentiment",
            "verified_influencer_count", "critical_mention_count", "primary_product",
        ]
        with open(os.path.join(self.workspace, "crisis_dashboard.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in dashboard_rows:
                writer.writerow(row)

        # -- build action string --
        top3 = dashboard_rows[:3]
        action = f"Total crisis brands identified: {len(dashboard_rows)}. "
        action += "Top three brands by final score: "
        for i, row in enumerate(top3):
            action += (
                f"{row['brand_name']} (final score: {row['final_score']}, "
                f"alert level: {row['alert_level']})"
            )
            if i < len(top3) - 1:
                action += ", "
        action += "."

        assert tool_calls >= 15, f"Only {tool_calls} tool calls; need >= 15"
        return self.step(action)
