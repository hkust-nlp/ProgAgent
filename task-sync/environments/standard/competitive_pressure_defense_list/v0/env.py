"""
Environment for competitive-pressure analysis task.
Provides tools and evaluation logic.
"""

import csv
import json
import math
import os
import sqlite3
from typing import Any, Dict, List, Tuple


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
    #  Tool methods                                                        #
    # ================================================================== #

    @tool(
        description=(
            "Returns a paginated list of customer accounts. "
            "Each page contains up to 15 accounts with their id, name, tier, "
            "region, and annual_revenue."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
            },
            "required": ["page"],
        },
    )
    def list_accounts(self, page: int) -> dict:
        page_size = 15
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM accounts")
        total = cur.fetchone()[0]
        total_pages = max(1, math.ceil(total / page_size))
        offset = (max(1, page) - 1) * page_size
        cur.execute(
            "SELECT account_id, name, tier, region, annual_revenue "
            "FROM accounts ORDER BY account_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "total_pages": total_pages,
            "total_accounts": total,
            "accounts": rows,
        }

    @tool(
        description=(
            "Returns all deals in the pipeline for a given account, including "
            "competitor_id, competitor_name, stage, deal_value, probability, "
            "and last_activity date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "integer",
                    "description": "The account ID to look up.",
                },
            },
            "required": ["account_id"],
        },
    )
    def get_account_deals(self, account_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT d.deal_id, d.competitor_id, c.name AS competitor_name, "
            "d.stage, d.deal_value, d.probability, d.last_activity "
            "FROM deal_pipeline d "
            "JOIN competitors c ON d.competitor_id = c.competitor_id "
            "WHERE d.account_id = ? "
            "ORDER BY d.deal_id",
            (account_id,),
        )
        deals = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"account_id": account_id, "deals": deals}

    @tool(
        description=(
            "Returns the search-ranking trend for a competitor. For each keyword "
            "the competitor is tracked on, returns the average rank in the early "
            "period and in the recent period (last N days). A competitor whose "
            "recent average rank is lower (closer to 1) than the early average "
            "is rising in search results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "competitor_id": {
                    "type": "integer",
                    "description": "The competitor ID.",
                },
                "recent_days": {
                    "type": "integer",
                    "description": "Number of most-recent days to treat as the recent window.",
                },
            },
            "required": ["competitor_id", "recent_days"],
        },
    )
    def get_search_ranking_trend(self, competitor_id: int, recent_days: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        # Find the date boundary
        cur.execute(
            "SELECT DISTINCT search_date FROM search_rankings "
            "WHERE competitor_id = ? ORDER BY search_date DESC",
            (competitor_id,),
        )
        all_dates = [r[0] for r in cur.fetchall()]
        if not all_dates:
            conn.close()
            return {"competitor_id": competitor_id, "keywords": []}

        recent_dates = set(all_dates[: recent_days])
        early_dates = set(all_dates[recent_days:])

        cur.execute(
            "SELECT keyword, rank_position, search_date "
            "FROM search_rankings WHERE competitor_id = ? "
            "ORDER BY keyword, search_date",
            (competitor_id,),
        )
        rows = cur.fetchall()
        conn.close()

        from collections import defaultdict
        kw_early: dict = defaultdict(list)
        kw_recent: dict = defaultdict(list)
        for kw, rank, dt in rows:
            if dt in recent_dates:
                kw_recent[kw].append(rank)
            elif dt in early_dates:
                kw_early[kw].append(rank)

        keywords_out = []
        all_keywords = sorted(set(list(kw_early.keys()) + list(kw_recent.keys())))
        for kw in all_keywords:
            e = kw_early.get(kw, [])
            r = kw_recent.get(kw, [])
            early_avg = round(sum(e) / len(e), 2) if e else None
            recent_avg = round(sum(r) / len(r), 2) if r else None
            keywords_out.append({
                "keyword": kw,
                "early_avg_rank": early_avg,
                "recent_avg_rank": recent_avg,
            })

        return {"competitor_id": competitor_id, "keywords": keywords_out}

    @tool(
        description=(
            "Returns pricing comparison data for a competitor. For each product "
            "the competitor offers, returns the average of our_price and the "
            "average competitor_price over the most recent observations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "competitor_id": {
                    "type": "integer",
                    "description": "The competitor ID.",
                },
            },
            "required": ["competitor_id"],
        },
    )
    def get_competitor_pricing(self, competitor_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT product_name, "
            "AVG(our_price) AS avg_our_price, "
            "AVG(competitor_price) AS avg_competitor_price "
            "FROM pricing_feeds WHERE competitor_id = ? "
            "GROUP BY product_name ORDER BY product_name",
            (competitor_id,),
        )
        products = []
        for pname, our_avg, comp_avg in cur.fetchall():
            products.append({
                "product": pname,
                "avg_our_price": round(our_avg, 2),
                "avg_competitor_price": round(comp_avg, 2),
            })
        conn.close()
        return {"competitor_id": competitor_id, "products": products}

    @tool(
        description=(
            "Returns social-media activity metrics for a competitor. For each "
            "platform, returns average daily posts in the early period and in "
            "the recent period (last N days)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "competitor_id": {
                    "type": "integer",
                    "description": "The competitor ID.",
                },
                "recent_days": {
                    "type": "integer",
                    "description": "Number of most-recent days for the recent window.",
                },
            },
            "required": ["competitor_id", "recent_days"],
        },
    )
    def get_social_media_metrics(self, competitor_id: int, recent_days: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT post_date FROM social_media "
            "WHERE competitor_id = ? ORDER BY post_date DESC",
            (competitor_id,),
        )
        all_dates = [r[0] for r in cur.fetchall()]
        if not all_dates:
            conn.close()
            return {"competitor_id": competitor_id, "platforms": []}

        recent_dates = set(all_dates[:recent_days])
        early_dates = set(all_dates[recent_days:])

        cur.execute(
            "SELECT platform, daily_posts, post_date "
            "FROM social_media WHERE competitor_id = ? "
            "ORDER BY platform, post_date",
            (competitor_id,),
        )
        rows = cur.fetchall()
        conn.close()

        from collections import defaultdict
        plat_early: dict = defaultdict(list)
        plat_recent: dict = defaultdict(list)
        for plat, posts, dt in rows:
            if dt in recent_dates:
                plat_recent[plat].append(posts)
            elif dt in early_dates:
                plat_early[plat].append(posts)

        platforms_out = []
        all_plats = sorted(set(list(plat_early.keys()) + list(plat_recent.keys())))
        for plat in all_plats:
            e = plat_early.get(plat, [])
            r = plat_recent.get(plat, [])
            early_avg = round(sum(e) / len(e), 2) if e else 0.0
            recent_avg = round(sum(r) / len(r), 2) if r else 0.0
            platforms_out.append({
                "platform": plat,
                "early_avg_daily_posts": early_avg,
                "recent_avg_daily_posts": recent_avg,
            })

        return {"competitor_id": competitor_id, "platforms": platforms_out}

    @tool(
        description=(
            "Returns basic information about a competitor: id, name, domain, "
            "market_focus, and founded_year."
        ),
        parameters={
            "type": "object",
            "properties": {
                "competitor_id": {
                    "type": "integer",
                    "description": "The competitor ID.",
                },
            },
            "required": ["competitor_id"],
        },
    )
    def get_competitor_info(self, competitor_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM competitors WHERE competitor_id = ?",
            (competitor_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Competitor {competitor_id} not found"}

    # ================================================================== #
    #  Evaluation                                                          #
    # ================================================================== #

    def _compute_ground_truth(self):
        """Compute the full ground-truth defense list."""
        import yaml as _yaml

        # --- Load workspace configs ---
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            scoring_cfg = _yaml.safe_load(f)
        weights = scoring_cfg["weights"]
        recent_days = scoring_cfg["recent_window_days"]

        with open(os.path.join(self.workspace, "pressure_thresholds.json")) as f:
            thresholds = json.load(f)

        stage_risk_map: Dict[str, float] = {}
        with open(os.path.join(self.workspace, "pipeline_stage_risks.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                stage_risk_map[row["stage"]] = float(row["risk_factor"])

        # Parse defense playbook for actions
        action_map: Dict[str, str] = {}
        with open(os.path.join(self.workspace, "defense_playbook.md")) as f:
            content = f.read()
        for level in ["HIGH", "MEDIUM", "LOW"]:
            marker = f"## {level} Pressure"
            idx = content.find(marker)
            if idx >= 0:
                after = content[idx + len(marker):]
                for line in after.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("Recommended action:"):
                        action_map[level] = line.split(":", 1)[1].strip()
                        break

        # --- Load intel modifiers from workspace files ---
        intel_modifiers: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("field_intel_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    report = json.load(f)
                for entry in report["entries"]:
                    intel_modifiers[entry["account_id"]] = entry["intel_modifier"]

        # --- Database queries for ground truth ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # All accounts
        accounts = [
            dict(r) for r in conn.execute(
                "SELECT * FROM accounts ORDER BY account_id"
            ).fetchall()
        ]

        # All deals grouped by account
        deals_by_account: Dict[int, list] = {}
        for r in conn.execute(
            "SELECT d.*, c.name AS competitor_name "
            "FROM deal_pipeline d "
            "JOIN competitors c ON d.competitor_id = c.competitor_id"
        ).fetchall():
            d = dict(r)
            deals_by_account.setdefault(d["account_id"], []).append(d)

        # Search ranking trends per competitor
        all_search_dates = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT search_date FROM search_rankings ORDER BY search_date DESC"
            ).fetchall()
        ]
        recent_search = set(all_search_dates[:recent_days])
        early_search = set(all_search_dates[recent_days:])

        search_scores_by_comp: Dict[int, float] = {}
        for r in conn.execute(
            "SELECT competitor_id, keyword, rank_position, search_date "
            "FROM search_rankings"
        ).fetchall():
            comp_id, kw, rank, dt = r
            if comp_id not in search_scores_by_comp:
                search_scores_by_comp[comp_id] = {}

        # Recompute properly
        from collections import defaultdict
        comp_kw_early: dict = defaultdict(lambda: defaultdict(list))
        comp_kw_recent: dict = defaultdict(lambda: defaultdict(list))
        for r in conn.execute(
            "SELECT competitor_id, keyword, rank_position, search_date "
            "FROM search_rankings"
        ).fetchall():
            comp_id, kw, rank, dt = r
            if dt in recent_search:
                comp_kw_recent[comp_id][kw].append(rank)
            elif dt in early_search:
                comp_kw_early[comp_id][kw].append(rank)

        def _comp_search_score(comp_id: int) -> float:
            """Max rank-improvement ratio across keywords. Higher = more threatening."""
            best = 0.0
            all_kws = set(list(comp_kw_early[comp_id].keys()) + list(comp_kw_recent[comp_id].keys()))
            for kw in all_kws:
                e = comp_kw_early[comp_id].get(kw, [])
                r = comp_kw_recent[comp_id].get(kw, [])
                if e and r:
                    early_avg = sum(e) / len(e)
                    recent_avg = sum(r) / len(r)
                    if early_avg > 0:
                        improvement = (early_avg - recent_avg) / early_avg
                        best = max(best, max(0.0, improvement))
            return min(best, 1.0)

        # Pricing scores per competitor
        def _comp_pricing_score(comp_id: int) -> float:
            """Max undercut ratio across products. Higher = more threatening."""
            rows = conn.execute(
                "SELECT product_name, AVG(our_price) AS aop, AVG(competitor_price) AS acp "
                "FROM pricing_feeds WHERE competitor_id = ? GROUP BY product_name",
                (comp_id,),
            ).fetchall()
            best = 0.0
            for _, our_avg, comp_avg in rows:
                if our_avg > 0:
                    undercut = (our_avg - comp_avg) / our_avg
                    best = max(best, max(0.0, undercut))
            return min(best, 1.0)

        # Social scores per competitor
        all_social_dates = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT post_date FROM social_media ORDER BY post_date DESC"
            ).fetchall()
        ]
        recent_social = set(all_social_dates[:recent_days])
        early_social = set(all_social_dates[recent_days:])

        comp_plat_early: dict = defaultdict(lambda: defaultdict(list))
        comp_plat_recent: dict = defaultdict(lambda: defaultdict(list))
        for r in conn.execute(
            "SELECT competitor_id, platform, daily_posts, post_date FROM social_media"
        ).fetchall():
            comp_id, plat, posts, dt = r
            if dt in recent_social:
                comp_plat_recent[comp_id][plat].append(posts)
            elif dt in early_social:
                comp_plat_early[comp_id][plat].append(posts)

        def _comp_social_score(comp_id: int) -> float:
            """Max surge ratio across platforms. Higher = more threatening."""
            best = 0.0
            all_plats = set(
                list(comp_plat_early[comp_id].keys()) +
                list(comp_plat_recent[comp_id].keys())
            )
            for plat in all_plats:
                e = comp_plat_early[comp_id].get(plat, [])
                r = comp_plat_recent[comp_id].get(plat, [])
                early_avg = sum(e) / len(e) if e else 0.0
                recent_avg = sum(r) / len(r) if r else 0.0
                denom = max(early_avg, 1.0)
                surge = (recent_avg - early_avg) / denom
                best = max(best, max(0.0, surge))
            return min(best, 1.0)

        # --- Build defense list ---
        defense_list = []
        for acc in accounts:
            aid = acc["account_id"]
            deals = deals_by_account.get(aid, [])

            if not deals:
                # No pipeline activity → score components from pipeline are 0
                pipeline_score = 0.0
                competitors_in_play: list = []
            else:
                pipeline_score = max(
                    stage_risk_map.get(d["stage"], 0.0) for d in deals
                )
                competitors_in_play = list({d["competitor_id"] for d in deals})

            # Competitor-level scores (max across all competitors for this account)
            max_search = 0.0
            max_pricing = 0.0
            max_social = 0.0
            primary_comp_id = None
            primary_comp_score = -1.0

            for cid in competitors_in_play:
                ss = _comp_search_score(cid)
                ps = _comp_pricing_score(cid)
                so = _comp_social_score(cid)
                max_search = max(max_search, ss)
                max_pricing = max(max_pricing, ps)
                max_social = max(max_social, so)
                combined = ss + ps + so
                if combined > primary_comp_score:
                    primary_comp_score = combined
                    primary_comp_id = cid

            composite = (
                weights["search_ranking"] * max_search
                + weights["pricing_undercut"] * max_pricing
                + weights["social_media_surge"] * max_social
                + weights["pipeline_risk"] * pipeline_score
            )

            intel_mod = intel_modifiers.get(aid, 1.0)
            adjusted = composite * intel_mod

            # Classify
            if adjusted >= thresholds["HIGH"]:
                level = "HIGH"
            elif adjusted >= thresholds["MEDIUM"]:
                level = "MEDIUM"
            else:
                level = "LOW"

            # Primary competitor name
            primary_comp_name = ""
            if primary_comp_id is not None:
                r = conn.execute(
                    "SELECT name FROM competitors WHERE competitor_id = ?",
                    (primary_comp_id,),
                ).fetchone()
                if r:
                    primary_comp_name = r[0]

            defense_list.append({
                "account_id": aid,
                "account_name": acc["name"],
                "tier": acc["tier"],
                "pressure_score": round(adjusted, 4),
                "pressure_level": level,
                "primary_competitor": primary_comp_name,
                "recommended_action": action_map.get(level, ""),
            })

        conn.close()

        # Sort by pressure_score descending, then account_id ascending as tie-breaker
        defense_list.sort(key=lambda x: (-x["pressure_score"], x["account_id"]))

        # Assign rank
        for i, entry in enumerate(defense_list, 1):
            entry["rank"] = i

        return defense_list, thresholds

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
        gt_list, thresholds = self._compute_ground_truth()
        gt_high = [e for e in gt_list if e["pressure_level"] == "HIGH"]
        gt_medium = [e for e in gt_list if e["pressure_level"] == "MEDIUM"]
        gt_low = [e for e in gt_list if e["pressure_level"] == "LOW"]
        gt_top5 = gt_list[:5]

        criteria: Dict[str, Dict[str, Any]] = {}

        # ---- Criterion 1: defense_list.csv exists with correct columns (15 pts) ----
        csv_path = os.path.join(self.workspace, "defense_list.csv")
        expected_cols = [
            "rank", "account_id", "account_name", "tier",
            "pressure_score", "pressure_level", "primary_competitor",
            "recommended_action",
        ]
        if os.path.isfile(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                actual_cols = [c.strip() for c in (reader.fieldnames or [])]
            cols_ok = actual_cols == expected_cols
            criteria["csv_structure"] = {
                "passed": cols_ok,
                "score": 15 if cols_ok else 0,
                "max_score": 15,
                "reason": "" if cols_ok else f"Expected columns {expected_cols}, got {actual_cols}",
            }
        else:
            criteria["csv_structure"] = {
                "passed": False,
                "score": 0,
                "max_score": 15,
                "reason": "defense_list.csv not found in workspace",
            }

        # ---- Criterion 2: pressure scores accuracy (25 pts) ----
        score_match = 0
        total_accounts = len(gt_list)
        if os.path.isfile(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                submitted: Dict[int, dict] = {}
                for row in reader:
                    try:
                        aid = int(row.get("account_id", "").strip())
                        submitted[aid] = row
                    except (ValueError, KeyError):
                        pass
            for entry in gt_list:
                aid = entry["account_id"]
                if aid in submitted:
                    try:
                        sub_score = float(submitted[aid].get("pressure_score", "").strip())
                        if abs(sub_score - entry["pressure_score"]) < 0.02:
                            score_match += 1
                    except (ValueError, TypeError):
                        pass
        pct_match = score_match / total_accounts if total_accounts else 0
        pts_scores = round(25 * pct_match)
        criteria["pressure_scores"] = {
            "passed": pct_match >= 0.9,
            "score": pts_scores,
            "max_score": 25,
            "reason": "" if pct_match >= 0.9 else f"Only {score_match}/{total_accounts} scores within tolerance",
        }

        # ---- Criterion 3: pressure levels correct (15 pts) ----
        level_match = 0
        if os.path.isfile(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                submitted_levels: Dict[int, str] = {}
                for row in reader:
                    try:
                        aid = int(row.get("account_id", "").strip())
                        submitted_levels[aid] = row.get("pressure_level", "").strip()
                    except (ValueError, KeyError):
                        pass
            for entry in gt_list:
                aid = entry["account_id"]
                if submitted_levels.get(aid) == entry["pressure_level"]:
                    level_match += 1
        pct_level = level_match / total_accounts if total_accounts else 0
        pts_levels = round(15 * pct_level)
        criteria["pressure_levels"] = {
            "passed": pct_level >= 0.9,
            "score": pts_levels,
            "max_score": 15,
            "reason": "" if pct_level >= 0.9 else f"Only {level_match}/{total_accounts} levels correct",
        }

        # ---- Criterion 4: sorted by pressure_score desc (10 pts) ----
        sort_ok = False
        if os.path.isfile(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                scores_in_order = []
                for row in reader:
                    try:
                        scores_in_order.append(float(row.get("pressure_score", "0").strip()))
                    except ValueError:
                        scores_in_order.append(0.0)
            if scores_in_order:
                sort_ok = all(
                    scores_in_order[i] >= scores_in_order[i + 1]
                    for i in range(len(scores_in_order) - 1)
                )
        criteria["sort_order"] = {
            "passed": sort_ok,
            "score": 10 if sort_ok else 0,
            "max_score": 10,
        }

        # ---- Criterion 5: recommended actions correct (10 pts) ----
        action_match = 0
        if os.path.isfile(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                submitted_actions: Dict[int, str] = {}
                for row in reader:
                    try:
                        aid = int(row.get("account_id", "").strip())
                        submitted_actions[aid] = row.get("recommended_action", "").strip()
                    except (ValueError, KeyError):
                        pass
            for entry in gt_list:
                aid = entry["account_id"]
                if submitted_actions.get(aid) == entry["recommended_action"]:
                    action_match += 1
        pct_action = action_match / total_accounts if total_accounts else 0
        pts_actions = round(10 * pct_action)
        criteria["recommended_actions"] = {
            "passed": pct_action >= 0.9,
            "score": pts_actions,
            "max_score": 10,
            "reason": "" if pct_action >= 0.9 else f"Only {action_match}/{total_accounts} actions correct",
        }

        # ---- Criterion 6: response states correct HIGH count (10 pts) ----
        high_count_ok = False
        expected_high = len(gt_high)
        if str(expected_high) in action:
            # Check for a pattern like "N accounts" or "HIGH: N" near the number
            high_count_ok = True
        criteria["high_count_in_response"] = {
            "passed": high_count_ok,
            "score": 10 if high_count_ok else 0,
            "max_score": 10,
            "reason": "" if high_count_ok else f"Expected HIGH count {expected_high} not found in response",
        }

        # ---- Criterion 7: response lists correct top 5 account names (15 pts) ----
        top5_names = {e["account_name"] for e in gt_top5}
        found = sum(1 for name in top5_names if name in action)
        pct_top5 = found / len(top5_names) if top5_names else 0
        pts_top5 = round(15 * pct_top5)
        criteria["top5_in_response"] = {
            "passed": pct_top5 >= 0.8,
            "score": pts_top5,
            "max_score": 15,
            "reason": "" if pct_top5 >= 0.8 else f"Only {found}/{len(top5_names)} top-5 names found in response",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

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
        import yaml as _yaml
        from collections import defaultdict

        tool_call_count = 0

        def _call(name, **kwargs):
            nonlocal tool_call_count
            tool_call_count += 1
            return self.tools[name](**kwargs)

        # ---- Step 1: Read workspace config files ----
        with open(os.path.join(self.workspace, "scoring_config.yaml")) as f:
            scoring_cfg = _yaml.safe_load(f)
        weights = scoring_cfg["weights"]
        recent_days = scoring_cfg["recent_window_days"]

        with open(os.path.join(self.workspace, "pressure_thresholds.json")) as f:
            thresholds = json.load(f)

        stage_risk_map: Dict[str, float] = {}
        with open(os.path.join(self.workspace, "pipeline_stage_risks.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                stage_risk_map[row["stage"]] = float(row["risk_factor"])

        action_map: Dict[str, str] = {}
        with open(os.path.join(self.workspace, "defense_playbook.md")) as f:
            content = f.read()
        for level in ["HIGH", "MEDIUM", "LOW"]:
            marker = f"## {level} Pressure"
            idx = content.find(marker)
            if idx >= 0:
                after = content[idx + len(marker):]
                for line in after.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("Recommended action:"):
                        action_map[level] = line.split(":", 1)[1].strip()
                        break

        # ---- Step 2: Read intel modifiers from workspace files ----
        intel_modifiers: Dict[int, float] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("field_intel_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    report = json.load(f)
                for entry in report["entries"]:
                    intel_modifiers[entry["account_id"]] = entry["intel_modifier"]

        # ---- Step 3: Get all accounts via tool ----
        all_accounts = []
        page = 1
        while True:
            result = _call("list_accounts", page=page)
            all_accounts.extend(result["accounts"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ---- Step 4: Get deals for each account ----
        deals_by_account: Dict[int, list] = {}
        for acc in all_accounts:
            result = _call("get_account_deals", account_id=acc["account_id"])
            if result["deals"]:
                deals_by_account[acc["account_id"]] = result["deals"]

        # ---- Step 5: Collect unique competitor IDs and fetch metrics ----
        all_comp_ids = set()
        for deals in deals_by_account.values():
            for d in deals:
                all_comp_ids.add(d["competitor_id"])

        comp_search_scores: Dict[int, float] = {}
        comp_pricing_scores: Dict[int, float] = {}
        comp_social_scores: Dict[int, float] = {}

        for cid in sorted(all_comp_ids):
            # Search ranking trend
            trend = _call("get_search_ranking_trend", competitor_id=cid, recent_days=recent_days)
            best_search = 0.0
            for kw_data in trend["keywords"]:
                e = kw_data["early_avg_rank"]
                r = kw_data["recent_avg_rank"]
                if e is not None and r is not None and e > 0:
                    improvement = (e - r) / e
                    best_search = max(best_search, max(0.0, improvement))
            comp_search_scores[cid] = min(best_search, 1.0)

            # Pricing
            pricing = _call("get_competitor_pricing", competitor_id=cid)
            best_pricing = 0.0
            for prod in pricing["products"]:
                our_p = prod["avg_our_price"]
                comp_p = prod["avg_competitor_price"]
                if our_p > 0:
                    undercut = (our_p - comp_p) / our_p
                    best_pricing = max(best_pricing, max(0.0, undercut))
            comp_pricing_scores[cid] = min(best_pricing, 1.0)

            # Social media
            social = _call("get_social_media_metrics", competitor_id=cid, recent_days=recent_days)
            best_social = 0.0
            for plat_data in social["platforms"]:
                early_avg = plat_data["early_avg_daily_posts"]
                recent_avg = plat_data["recent_avg_daily_posts"]
                denom = max(early_avg, 1.0)
                surge = (recent_avg - early_avg) / denom
                best_social = max(best_social, max(0.0, surge))
            comp_social_scores[cid] = min(best_social, 1.0)

        # ---- Step 6: Compute scores for each account ----
        defense_list = []
        for acc in all_accounts:
            aid = acc["account_id"]
            deals = deals_by_account.get(aid, [])

            if not deals:
                pipeline_score = 0.0
                comp_ids_for_acc: list = []
            else:
                pipeline_score = max(
                    stage_risk_map.get(d["stage"], 0.0) for d in deals
                )
                comp_ids_for_acc = list({d["competitor_id"] for d in deals})

            max_search = 0.0
            max_pricing = 0.0
            max_social = 0.0
            primary_comp_id = None
            primary_comp_score = -1.0

            for cid in comp_ids_for_acc:
                ss = comp_search_scores.get(cid, 0.0)
                ps = comp_pricing_scores.get(cid, 0.0)
                so = comp_social_scores.get(cid, 0.0)
                max_search = max(max_search, ss)
                max_pricing = max(max_pricing, ps)
                max_social = max(max_social, so)
                combined = ss + ps + so
                if combined > primary_comp_score:
                    primary_comp_score = combined
                    primary_comp_id = cid

            composite = (
                weights["search_ranking"] * max_search
                + weights["pricing_undercut"] * max_pricing
                + weights["social_media_surge"] * max_social
                + weights["pipeline_risk"] * pipeline_score
            )

            intel_mod = intel_modifiers.get(aid, 1.0)
            adjusted = composite * intel_mod

            if adjusted >= thresholds["HIGH"]:
                level = "HIGH"
            elif adjusted >= thresholds["MEDIUM"]:
                level = "MEDIUM"
            else:
                level = "LOW"

            # Get primary competitor name
            primary_comp_name = ""
            if primary_comp_id is not None:
                # Find it from deals data
                for d in deals:
                    if d["competitor_id"] == primary_comp_id:
                        primary_comp_name = d["competitor_name"]
                        break

            defense_list.append({
                "account_id": aid,
                "account_name": acc["name"],
                "tier": acc["tier"],
                "pressure_score": round(adjusted, 4),
                "pressure_level": level,
                "primary_competitor": primary_comp_name,
                "recommended_action": action_map.get(level, ""),
            })

        # Sort by pressure_score desc, account_id asc as tie-breaker
        defense_list.sort(key=lambda x: (-x["pressure_score"], x["account_id"]))

        # Assign rank
        for i, entry in enumerate(defense_list, 1):
            entry["rank"] = i

        # ---- Step 7: Write defense_list.csv ----
        csv_path = os.path.join(self.workspace, "defense_list.csv")
        fieldnames = [
            "rank", "account_id", "account_name", "tier",
            "pressure_score", "pressure_level", "primary_competitor",
            "recommended_action",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in defense_list:
                writer.writerow(entry)

        # ---- Step 8: Build action string ----
        high_accounts = [e for e in defense_list if e["pressure_level"] == "HIGH"]
        medium_accounts = [e for e in defense_list if e["pressure_level"] == "MEDIUM"]
        low_accounts = [e for e in defense_list if e["pressure_level"] == "LOW"]
        top5 = defense_list[:5]

        action_parts = [
            f"Competitive Pressure Analysis Complete.",
            f"",
            f"Total accounts analyzed: {len(defense_list)}",
            f"HIGH pressure accounts: {len(high_accounts)}",
            f"MEDIUM pressure accounts: {len(medium_accounts)}",
            f"LOW pressure accounts: {len(low_accounts)}",
            f"",
            f"Top 5 accounts by competitive pressure:",
        ]
        for e in top5:
            action_parts.append(
                f"  {e['rank']}. {e['account_name']} (ID: {e['account_id']}) - "
                f"Score: {e['pressure_score']}, Level: {e['pressure_level']}, "
                f"Primary Competitor: {e['primary_competitor']}"
            )

        action_parts.append("")
        action_parts.append("The full defense list has been saved to defense_list.csv.")

        action_str = "\n".join(action_parts)

        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls made; need at least 15"
        )

        return self.step(action_str)
