import sqlite3
import os
import json
import csv
import math
from typing import Tuple, Dict, List, Any

# --- Decorator ---
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description=(
            "List podcasts with pagination. Returns a page of podcast records "
            "including podcast_id, name, genre, host, network, launch_date, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_podcasts(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM podcasts")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM podcasts ORDER BY podcast_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_podcasts": total,
            "total_pages": math.ceil(total / page_size),
            "podcasts": rows,
        }

    @tool(
        description=(
            "Get all episodes for a given podcast, optionally filtered by period. "
            "Each record includes episode_id, episode_number, title, air_date, "
            "duration_seconds, num_segments, and period."
        ),
        parameters={
            "type": "object",
            "properties": {
                "podcast_id": {
                    "type": "integer",
                    "description": "The podcast ID.",
                },
                "period": {
                    "type": "string",
                    "description": "Optional period filter, e.g. '2025-Q3'.",
                },
            },
            "required": ["podcast_id"],
        },
    )
    def get_episodes(self, podcast_id: int, period: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if period:
            cur.execute(
                "SELECT * FROM episodes WHERE podcast_id=? AND period=? ORDER BY episode_number",
                (podcast_id, period),
            )
        else:
            cur.execute(
                "SELECT * FROM episodes WHERE podcast_id=? ORDER BY episode_number",
                (podcast_id,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"podcast_id": podcast_id, "episodes": rows}

    @tool(
        description=(
            "Get listener retention data for a specific episode. Returns "
            "episode_id, initial_listeners, final_listeners, and retention_rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "episode_id": {
                    "type": "integer",
                    "description": "The episode ID.",
                },
            },
            "required": ["episode_id"],
        },
    )
    def get_episode_retention(self, episode_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM listener_retention WHERE episode_id=?", (episode_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"No retention data for episode_id={episode_id}"}

    @tool(
        description=(
            "Get all ad placements for a specific episode. Each record includes "
            "ad_id, ad_position_seconds, ad_duration_seconds, ad_type, advertiser, "
            "and revenue_per_mille."
        ),
        parameters={
            "type": "object",
            "properties": {
                "episode_id": {
                    "type": "integer",
                    "description": "The episode ID.",
                },
            },
            "required": ["episode_id"],
        },
    )
    def get_episode_ad_placements(self, episode_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM ad_placements WHERE episode_id=? ORDER BY ad_position_seconds",
            (episode_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"episode_id": episode_id, "ad_placements": rows}

    @tool(
        description=(
            "Get listener demographic breakdown for a podcast in a given period. "
            "Returns age_group and listener_count for each demographic bucket."
        ),
        parameters={
            "type": "object",
            "properties": {
                "podcast_id": {
                    "type": "integer",
                    "description": "The podcast ID.",
                },
                "period": {
                    "type": "string",
                    "description": "Period identifier, e.g. '2025-Q3' or '2025-Q4'.",
                },
            },
            "required": ["podcast_id", "period"],
        },
    )
    def get_podcast_demographics(self, podcast_id: int, period: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT age_group, listener_count FROM listener_demographics "
            "WHERE podcast_id=? AND period=? ORDER BY age_group",
            (podcast_id, period),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"podcast_id": podcast_id, "period": period, "demographics": rows}

    @tool(
        description=(
            "Get competitor show data for a specific genre. Returns show_name, "
            "network, avg_retention_rate, and monthly_listeners for each competitor."
        ),
        parameters={
            "type": "object",
            "properties": {
                "genre": {
                    "type": "string",
                    "description": "The genre to query, e.g. 'True Crime'.",
                },
            },
            "required": ["genre"],
        },
    )
    def get_competitor_shows(self, genre: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM competitor_shows WHERE genre=? ORDER BY avg_retention_rate DESC",
            (genre,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"genre": genre, "competitors": rows}

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the full ground-truth from the database and workspace files."""
        import yaml

        # --- Load config files from workspace ---
        with open(os.path.join(self.workspace, "retention_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "scoring_rubric.json")) as f:
            rubric = json.load(f)
        with open(os.path.join(self.workspace, "ad_rate_adjustments.json")) as f:
            ad_rate_adj = json.load(f)

        baseline_period = config["baseline_period"]
        current_period = config["current_period"]
        threshold = config["retention_drop_threshold_pct"]
        weights = config["priority_weights"]
        demo_shift_threshold = config["demographic_shift_threshold_pct"]
        max_rev_segs = config["max_revision_segments_per_podcast"]
        norms = rubric["normalization"]

        # --- Load demographic baseline ---
        demo_baseline = {}
        with open(os.path.join(self.workspace, "demographic_baseline.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                demo_baseline[(row["genre"], row["age_group"])] = float(row["baseline_pct"])

        # --- Query database ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # All podcasts
        cur.execute("SELECT * FROM podcasts ORDER BY podcast_id")
        podcasts = [dict(r) for r in cur.fetchall()]

        # Compute average retention per podcast per period
        podcast_retention = {}  # podcast_id -> {period -> avg_retention}
        podcast_episodes = {}   # podcast_id -> {period -> [episode_ids]}
        for p in podcasts:
            pid = p["podcast_id"]
            podcast_retention[pid] = {}
            podcast_episodes[pid] = {}
            for period in [baseline_period, current_period]:
                cur.execute(
                    """SELECT e.episode_id, lr.retention_rate
                       FROM episodes e
                       JOIN listener_retention lr ON e.episode_id = lr.episode_id
                       WHERE e.podcast_id=? AND e.period=?""",
                    (pid, period),
                )
                rows = cur.fetchall()
                if rows:
                    rates = [r["retention_rate"] for r in rows]
                    podcast_retention[pid][period] = sum(rates) / len(rates)
                    podcast_episodes[pid][period] = [r["episode_id"] for r in rows]
                else:
                    podcast_retention[pid][period] = None
                    podcast_episodes[pid][period] = []

        # Identify flagged podcasts (>threshold% retention drop)
        flagged = {}
        for p in podcasts:
            pid = p["podcast_id"]
            bl = podcast_retention[pid].get(baseline_period)
            cr = podcast_retention[pid].get(current_period)
            if bl and cr and bl > 0:
                drop_pct = (bl - cr) / bl * 100
                if drop_pct > threshold:
                    flagged[pid] = {
                        "podcast_name": p["name"],
                        "genre": p["genre"],
                        "retention_drop_pct": round(drop_pct, 2),
                        "baseline_retention": bl,
                        "current_retention": cr,
                    }

        # For each flagged podcast, compute metrics
        results = []
        for pid, info in flagged.items():
            genre = info["genre"]

            # --- Flagged episode count (current period) ---
            flagged_ep_count = len(podcast_episodes[pid].get(current_period, []))

            # --- Competitor gap ---
            cur.execute(
                "SELECT avg_retention_rate FROM competitor_shows WHERE genre=?",
                (genre,),
            )
            comp_rates = [r["avg_retention_rate"] for r in cur.fetchall()]
            comp_avg = sum(comp_rates) / len(comp_rates) if comp_rates else 0.0
            competitor_gap = max(comp_avg - info["current_retention"], 0.0)

            # --- Demographic shift ---
            demo_shift = 0.0
            cur.execute(
                "SELECT age_group, listener_count FROM listener_demographics "
                "WHERE podcast_id=? AND period=?",
                (pid, current_period),
            )
            demo_current_rows = cur.fetchall()
            total_current = sum(r["listener_count"] for r in demo_current_rows)
            if total_current > 0:
                for r in demo_current_rows:
                    actual_pct = r["listener_count"] / total_current
                    baseline_pct = demo_baseline.get((genre, r["age_group"]), 0.2)
                    demo_shift += abs(actual_pct - baseline_pct)
            demo_shift_pct = demo_shift * 100
            demo_flag = "yes" if demo_shift_pct > demo_shift_threshold else "no"

            # --- Ad revenue impact ---
            # Compare average per-episode ad revenue: baseline vs current
            def _ep_ad_revenue(episode_ids):
                if not episode_ids:
                    return 0.0
                total_rev = 0.0
                for eid in episode_ids:
                    cur.execute(
                        "SELECT ad_position_seconds, revenue_per_mille FROM ad_placements WHERE episode_id=?",
                        (eid,),
                    )
                    ads = cur.fetchall()
                    cur.execute(
                        "SELECT initial_listeners FROM listener_retention WHERE episode_id=?",
                        (eid,),
                    )
                    ret_row = cur.fetchone()
                    init_l = ret_row["initial_listeners"] if ret_row else 0
                    genre_mult = ad_rate_adj.get(genre, 1.0)
                    for a in ads:
                        total_rev += a["revenue_per_mille"] * genre_mult * init_l / 1000.0
                return total_rev / len(episode_ids)

            bl_rev = _ep_ad_revenue(podcast_episodes[pid].get(baseline_period, []))
            cr_rev = _ep_ad_revenue(podcast_episodes[pid].get(current_period, []))
            if bl_rev > 0:
                ad_impact = max((bl_rev - cr_rev) / bl_rev, 0.0)
            else:
                ad_impact = 0.0
            ad_impact = min(ad_impact, 1.0)

            # --- Normalize and compute priority score ---
            def _normalize(val, key):
                lo = norms[key]["min"]
                hi = norms[key]["max"]
                if hi == lo:
                    return 0.0
                return min(max((val - lo) / (hi - lo), 0.0), 1.0)

            n_drop = _normalize(info["retention_drop_pct"], "retention_drop_pct")
            n_gap = _normalize(competitor_gap, "competitor_gap")
            n_demo = _normalize(demo_shift_pct, "demographic_shift_pct")
            n_ad = _normalize(ad_impact, "ad_revenue_impact")

            priority_score = round(
                (weights["retention_drop"] * n_drop
                 + weights["competitor_gap"] * n_gap
                 + weights["demographic_shift"] * n_demo
                 + weights["ad_revenue_impact"] * n_ad) * 100,
                2,
            )

            # --- Top revision segments ---
            top_segs = self._find_worst_segments(pid, current_period, max_rev_segs)

            results.append({
                "podcast_name": info["podcast_name"],
                "genre": genre,
                "retention_drop_pct": info["retention_drop_pct"],
                "priority_score": priority_score,
                "flagged_episode_count": flagged_ep_count,
                "top_revision_segments": top_segs,
                "demographic_shift_flag": demo_flag,
            })

        conn.close()

        # Sort by priority_score desc, tie-break retention_drop_pct desc
        results.sort(key=lambda x: (-x["priority_score"], -x["retention_drop_pct"]))
        return results

    def _find_worst_segments(self, podcast_id, period, max_segments):
        """Find segments with worst drop-off from workspace CSV files."""
        import glob
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT episode_id, episode_number FROM episodes WHERE podcast_id=? AND period=?",
            (podcast_id, period),
        )
        ep_rows = cur.fetchall()
        conn.close()
        ep_ids = {r[0] for r in ep_rows}
        ep_num_map = {r[0]: r[1] for r in ep_rows}

        # Read segment files
        seg_files = sorted(glob.glob(os.path.join(self.workspace, "episode_segments_batch_*.csv")))
        candidates = []
        for sf in seg_files:
            with open(sf) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    eid = int(row["episode_id"])
                    if eid in ep_ids:
                        start_l = int(row["listeners_at_start"])
                        end_l = int(row["listeners_at_end"])
                        if start_l > 0:
                            drop_rate = (start_l - end_l) / start_l
                        else:
                            drop_rate = 0.0
                        candidates.append({
                            "episode_number": ep_num_map[eid],
                            "segment_index": int(row["segment_index"]),
                            "content_type": row["content_type"],
                            "drop_rate": drop_rate,
                        })

        # Sort by drop_rate descending, pick top max_segments
        candidates.sort(key=lambda x: -x["drop_rate"])
        top = candidates[:max_segments]
        # Format: "Ep3:Seg2-interview; Ep5:Seg4-monologue"
        parts = []
        for s in top:
            parts.append(f"Ep{s['episode_number']}:Seg{s['segment_index']}-{s['content_type']}")
        return "; ".join(parts)

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
        gt_names = {r["podcast_name"] for r in gt}
        gt_map = {r["podcast_name"]: r for r in gt}

        criteria = {}

        # ------------------------------------------------------------------
        # C1: priority_report.csv exists with correct columns (10 pts)
        # ------------------------------------------------------------------
        report_path = os.path.join(self.workspace, "priority_report.csv")
        expected_cols = [
            "podcast_name", "genre", "retention_drop_pct", "priority_score",
            "flagged_episode_count", "top_revision_segments", "demographic_shift_flag",
        ]
        report_rows = []
        c1_pass = False
        if os.path.exists(report_path):
            with open(report_path) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and set(expected_cols).issubset(set(reader.fieldnames)):
                    report_rows = list(reader)
                    c1_pass = True
        criteria["file_format"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": "" if c1_pass else "priority_report.csv missing or wrong columns",
        }

        if not c1_pass:
            # Cannot evaluate further
            for cname, mx in [("flagged_podcasts", 20), ("retention_values", 15),
                              ("priority_scores", 15), ("sorting", 10),
                              ("revision_segments", 15), ("demographic_flags", 15)]:
                criteria[cname] = {"passed": False, "score": 0, "max_score": mx,
                                   "reason": "No valid report to check."}
            total = sum(c["score"] for c in criteria.values())
            mx = sum(c["max_score"] for c in criteria.values())
            return total / mx, {"eval_criteria": criteria, "total_score": total, "max_score": mx}

        reported_names = {r["podcast_name"] for r in report_rows}
        reported_map = {r["podcast_name"]: r for r in report_rows}

        # ------------------------------------------------------------------
        # C2: Correct flagged podcasts (20 pts) – Jaccard
        # ------------------------------------------------------------------
        if gt_names or reported_names:
            inter = gt_names & reported_names
            union = gt_names | reported_names
            jaccard = len(inter) / len(union) if union else 0.0
        else:
            jaccard = 1.0
        c2_score = round(jaccard * 20, 2)
        criteria["flagged_podcasts"] = {
            "passed": c2_score >= 19.0,
            "score": c2_score,
            "max_score": 20,
            "reason": "" if c2_score >= 19.0 else f"Jaccard={jaccard:.3f}, expected={len(gt_names)}, got={len(reported_names)}",
        }

        # ------------------------------------------------------------------
        # C3: Correct retention_drop_pct values (15 pts)
        # ------------------------------------------------------------------
        common = gt_names & reported_names
        if common:
            matches = 0
            for name in common:
                try:
                    reported_val = float(reported_map[name]["retention_drop_pct"])
                    gt_val = gt_map[name]["retention_drop_pct"]
                    if abs(reported_val - gt_val) <= 1.0:
                        matches += 1
                except (ValueError, KeyError):
                    pass
            c3_ratio = matches / len(common)
        else:
            c3_ratio = 0.0
        c3_score = round(c3_ratio * 15, 2)
        criteria["retention_values"] = {
            "passed": c3_score >= 14.0,
            "score": c3_score,
            "max_score": 15,
            "reason": "" if c3_score >= 14.0 else f"{matches}/{len(common)} within tolerance",
        }

        # ------------------------------------------------------------------
        # C4: Correct priority_score values (15 pts)
        # ------------------------------------------------------------------
        if common:
            matches4 = 0
            for name in common:
                try:
                    reported_val = float(reported_map[name]["priority_score"])
                    gt_val = gt_map[name]["priority_score"]
                    if abs(reported_val - gt_val) <= 3.0:
                        matches4 += 1
                except (ValueError, KeyError):
                    pass
            c4_ratio = matches4 / len(common)
        else:
            c4_ratio = 0.0
        c4_score = round(c4_ratio * 15, 2)
        criteria["priority_scores"] = {
            "passed": c4_score >= 14.0,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_score >= 14.0 else f"{matches4}/{len(common)} within tolerance",
        }

        # ------------------------------------------------------------------
        # C5: Correct sorting (10 pts)
        # ------------------------------------------------------------------
        reported_scores = []
        for r in report_rows:
            try:
                reported_scores.append(float(r["priority_score"]))
            except (ValueError, KeyError):
                reported_scores.append(-1)
        is_sorted = all(reported_scores[i] >= reported_scores[i + 1] for i in range(len(reported_scores) - 1))
        c5_score = 10 if is_sorted else 0
        criteria["sorting"] = {
            "passed": is_sorted,
            "score": c5_score,
            "max_score": 10,
            "reason": "" if is_sorted else "Not sorted by priority_score descending",
        }

        # ------------------------------------------------------------------
        # C6: Correct revision segments (15 pts)
        # ------------------------------------------------------------------
        if common:
            seg_matches = 0
            for name in common:
                gt_segs = set(gt_map[name]["top_revision_segments"].split("; ")) if gt_map[name]["top_revision_segments"] else set()
                reported_segs_raw = reported_map[name].get("top_revision_segments", "")
                reported_segs = set(reported_segs_raw.split("; ")) if reported_segs_raw else set()
                if gt_segs and reported_segs:
                    overlap = len(gt_segs & reported_segs) / len(gt_segs)
                    seg_matches += overlap
                elif not gt_segs and not reported_segs:
                    seg_matches += 1
            c6_ratio = seg_matches / len(common)
        else:
            c6_ratio = 0.0
        c6_score = round(c6_ratio * 15, 2)
        criteria["revision_segments"] = {
            "passed": c6_score >= 12.0,
            "score": c6_score,
            "max_score": 15,
            "reason": "" if c6_score >= 12.0 else f"Segment overlap ratio={c6_ratio:.3f}",
        }

        # ------------------------------------------------------------------
        # C7: Correct demographic_shift_flag (15 pts)
        # ------------------------------------------------------------------
        if common:
            demo_matches = 0
            for name in common:
                gt_flag = gt_map[name]["demographic_shift_flag"]
                reported_flag = reported_map[name].get("demographic_shift_flag", "").strip().lower()
                if reported_flag == gt_flag:
                    demo_matches += 1
            c7_ratio = demo_matches / len(common)
        else:
            c7_ratio = 0.0
        c7_score = round(c7_ratio * 15, 2)
        criteria["demographic_flags"] = {
            "passed": c7_score >= 14.0,
            "score": c7_score,
            "max_score": 15,
            "reason": "" if c7_score >= 14.0 else f"{demo_matches}/{len(common)} correct",
        }

        total = sum(c["score"] for c in criteria.values())
        mx = sum(c["max_score"] for c in criteria.values())
        return total / mx, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": mx,
        }

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import yaml

        # --- Load workspace config files ---
        with open(os.path.join(self.workspace, "retention_config.yaml")) as f:
            config = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "scoring_rubric.json")) as f:
            rubric = json.load(f)
        with open(os.path.join(self.workspace, "ad_rate_adjustments.json")) as f:
            ad_rate_adj = json.load(f)

        baseline_period = config["baseline_period"]
        current_period = config["current_period"]
        threshold = config["retention_drop_threshold_pct"]
        pw = config["priority_weights"]
        demo_shift_threshold = config["demographic_shift_threshold_pct"]
        max_rev_segs = config["max_revision_segments_per_podcast"]
        norms = rubric["normalization"]

        # Load demographic baseline
        demo_baseline = {}
        with open(os.path.join(self.workspace, "demographic_baseline.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                demo_baseline[(row["genre"], row["age_group"])] = float(row["baseline_pct"])

        tool_calls = 0

        # --- Step 1: List all podcasts ---
        all_podcasts = []
        page = 1
        while True:
            result = self.tools["list_podcasts"](page=page, page_size=20)
            tool_calls += 1
            all_podcasts.extend(result["podcasts"])
            if page >= result["total_pages"]:
                break
            page += 1

        # --- Step 2: For each podcast, get episodes and retention for both periods ---
        podcast_data = {}
        for p in all_podcasts:
            pid = p["podcast_id"]
            podcast_data[pid] = {
                "name": p["name"],
                "genre": p["genre"],
                "episodes": {},
            }
            for period in [baseline_period, current_period]:
                ep_result = self.tools["get_episodes"](podcast_id=pid, period=period)
                tool_calls += 1
                eps = ep_result["episodes"]
                ret_data = []
                for ep in eps:
                    ret = self.tools["get_episode_retention"](episode_id=ep["episode_id"])
                    tool_calls += 1
                    ret_data.append(ret)
                podcast_data[pid]["episodes"][period] = {
                    "episode_list": eps,
                    "retention": ret_data,
                }

        # --- Step 3: Compute retention drop and flag podcasts ---
        flagged = {}
        for pid, pdata in podcast_data.items():
            bl_rets = pdata["episodes"].get(baseline_period, {}).get("retention", [])
            cr_rets = pdata["episodes"].get(current_period, {}).get("retention", [])
            if bl_rets and cr_rets:
                bl_avg = sum(r["retention_rate"] for r in bl_rets) / len(bl_rets)
                cr_avg = sum(r["retention_rate"] for r in cr_rets) / len(cr_rets)
                if bl_avg > 0:
                    drop_pct = (bl_avg - cr_avg) / bl_avg * 100
                    if drop_pct > threshold:
                        flagged[pid] = {
                            "podcast_name": pdata["name"],
                            "genre": pdata["genre"],
                            "retention_drop_pct": round(drop_pct, 2),
                            "current_retention": cr_avg,
                        }

        # --- Step 4: For flagged podcasts, gather extra data ---
        # Read all segment files from workspace
        import glob as _glob
        seg_files = sorted(_glob.glob(os.path.join(self.workspace, "episode_segments_batch_*.csv")))
        all_segs = []
        for sf in seg_files:
            with open(sf) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    all_segs.append(row)

        results = []
        genres_seen = set()
        competitor_cache = {}

        for pid, finfo in flagged.items():
            genre = finfo["genre"]

            # Current period episodes
            current_eps = podcast_data[pid]["episodes"][current_period]["episode_list"]
            flagged_ep_count = len(current_eps)
            current_ep_ids = {ep["episode_id"] for ep in current_eps}

            # Competitor gap
            if genre not in competitor_cache:
                comp_result = self.tools["get_competitor_shows"](genre=genre)
                tool_calls += 1
                competitor_cache[genre] = comp_result["competitors"]
            comps = competitor_cache[genre]
            if comps:
                comp_avg = sum(c["avg_retention_rate"] for c in comps) / len(comps)
            else:
                comp_avg = 0.0
            competitor_gap = max(comp_avg - finfo["current_retention"], 0.0)

            # Demographics
            demo_result = self.tools["get_podcast_demographics"](
                podcast_id=pid, period=current_period
            )
            tool_calls += 1
            demo_rows = demo_result["demographics"]
            total_listeners = sum(d["listener_count"] for d in demo_rows)
            demo_shift = 0.0
            if total_listeners > 0:
                for d in demo_rows:
                    actual_pct = d["listener_count"] / total_listeners
                    baseline_pct = demo_baseline.get((genre, d["age_group"]), 0.2)
                    demo_shift += abs(actual_pct - baseline_pct)
            demo_shift_pct = demo_shift * 100
            demo_flag = "yes" if demo_shift_pct > demo_shift_threshold else "no"

            # Ad revenue impact
            baseline_eps = podcast_data[pid]["episodes"][baseline_period]["episode_list"]
            bl_ep_ids = [ep["episode_id"] for ep in baseline_eps]
            cr_ep_ids = [ep["episode_id"] for ep in current_eps]

            def _avg_ad_rev(ep_ids_list):
                if not ep_ids_list:
                    return 0.0
                total = 0.0
                for eid in ep_ids_list:
                    ad_result = self.tools["get_episode_ad_placements"](episode_id=eid)
                    nonlocal tool_calls
                    tool_calls += 1
                    ads = ad_result["ad_placements"]
                    ret = self.tools["get_episode_retention"](episode_id=eid)
                    tool_calls += 1
                    init_l = ret.get("initial_listeners", 0)
                    genre_mult = ad_rate_adj.get(genre, 1.0)
                    for a in ads:
                        total += a["revenue_per_mille"] * genre_mult * init_l / 1000.0
                return total / len(ep_ids_list)

            bl_rev = _avg_ad_rev(bl_ep_ids)
            cr_rev = _avg_ad_rev(cr_ep_ids)
            if bl_rev > 0:
                ad_impact = max((bl_rev - cr_rev) / bl_rev, 0.0)
            else:
                ad_impact = 0.0
            ad_impact = min(ad_impact, 1.0)

            # Normalize
            def _normalize(val, key):
                lo = norms[key]["min"]
                hi = norms[key]["max"]
                if hi == lo:
                    return 0.0
                return min(max((val - lo) / (hi - lo), 0.0), 1.0)

            n_drop = _normalize(finfo["retention_drop_pct"], "retention_drop_pct")
            n_gap = _normalize(competitor_gap, "competitor_gap")
            n_demo = _normalize(demo_shift_pct, "demographic_shift_pct")
            n_ad = _normalize(ad_impact, "ad_revenue_impact")

            priority_score = round(
                (pw["retention_drop"] * n_drop
                 + pw["competitor_gap"] * n_gap
                 + pw["demographic_shift"] * n_demo
                 + pw["ad_revenue_impact"] * n_ad) * 100,
                2,
            )

            # Find worst segments from workspace files
            ep_num_map = {ep["episode_id"]: ep["episode_number"] for ep in current_eps}
            candidates = []
            for seg in all_segs:
                eid = int(seg["episode_id"])
                if eid in current_ep_ids:
                    s_start = int(seg["listeners_at_start"])
                    s_end = int(seg["listeners_at_end"])
                    if s_start > 0:
                        drop_rate = (s_start - s_end) / s_start
                    else:
                        drop_rate = 0.0
                    candidates.append({
                        "episode_number": ep_num_map[eid],
                        "segment_index": int(seg["segment_index"]),
                        "content_type": seg["content_type"],
                        "drop_rate": drop_rate,
                    })
            candidates.sort(key=lambda x: -x["drop_rate"])
            top = candidates[:max_rev_segs]
            seg_str = "; ".join(
                f"Ep{s['episode_number']}:Seg{s['segment_index']}-{s['content_type']}"
                for s in top
            )

            results.append({
                "podcast_name": finfo["podcast_name"],
                "genre": genre,
                "retention_drop_pct": finfo["retention_drop_pct"],
                "priority_score": priority_score,
                "flagged_episode_count": flagged_ep_count,
                "top_revision_segments": seg_str,
                "demographic_shift_flag": demo_flag,
            })

        # Sort
        results.sort(key=lambda x: (-x["priority_score"], -x["retention_drop_pct"]))

        # Write priority_report.csv
        out_path = os.path.join(self.workspace, "priority_report.csv")
        fieldnames = [
            "podcast_name", "genre", "retention_drop_pct", "priority_score",
            "flagged_episode_count", "top_revision_segments", "demographic_shift_flag",
        ]
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "podcast_name": r["podcast_name"],
                    "genre": r["genre"],
                    "retention_drop_pct": f"{r['retention_drop_pct']:.2f}",
                    "priority_score": f"{r['priority_score']:.2f}",
                    "flagged_episode_count": r["flagged_episode_count"],
                    "top_revision_segments": r["top_revision_segments"],
                    "demographic_shift_flag": r["demographic_shift_flag"],
                })

        # Build action string
        summary_lines = [f"Identified {len(results)} podcasts with >15% retention drop."]
        summary_lines.append("Priority report saved to priority_report.csv.")
        for r in results[:5]:
            summary_lines.append(
                f"  - {r['podcast_name']} ({r['genre']}): "
                f"drop={r['retention_drop_pct']:.2f}%, score={r['priority_score']:.2f}"
            )
        if len(results) > 5:
            summary_lines.append(f"  ... and {len(results) - 5} more.")
        action = "\n".join(summary_lines)

        print(f"verify() used {tool_calls} tool calls")
        return self.step(action)
