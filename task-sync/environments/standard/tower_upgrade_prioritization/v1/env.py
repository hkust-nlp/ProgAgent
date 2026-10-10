"""
Environment for the cell tower capacity upgrade prioritization task.
"""

import csv
import json
import math
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

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

    # ===================================================================
    # Tool methods
    # ===================================================================

    @tool(
        description=(
            "Returns a paginated list of cell towers. Each entry includes "
            "tower_id, tower_name, region, and tower_class."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Towers per page (max 20). Default 10.",
                },
            },
            "required": [],
        },
    )
    def list_towers(self, page: int = 1, page_size: int = 10) -> dict:
        page_size = max(1, min(page_size, 20))
        page = max(1, page)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0]
        rows = conn.execute(
            "SELECT tower_id, tower_name, region, tower_class "
            "FROM towers ORDER BY tower_id "
            "LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        ).fetchall()
        conn.close()
        return {
            "towers": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_towers": total,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description=(
            "Returns detailed sector information for a given tower, "
            "including sector_id, sector_label, azimuth, frequency_band, "
            "current radio-unit model, and current capacity."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "integer",
                    "description": "The tower ID.",
                },
            },
            "required": ["tower_id"],
        },
    )
    def get_tower_sectors(self, tower_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT sector_id, sector_label, azimuth_deg, frequency_band, "
            "current_ru_model, current_capacity_mbps "
            "FROM sectors WHERE tower_id = ? ORDER BY sector_id",
            (tower_id,),
        ).fetchall()
        conn.close()
        return {"tower_id": tower_id, "sectors": [dict(r) for r in rows]}

    @tool(
        description=(
            "Returns per-sector utilization statistics for a tower computed "
            "over the last 30 days of traffic data. For each sector the "
            "response includes avg_utilization_pct (mean of daily "
            "avg_volume / capacity * 100) and peak_utilization_pct (max of "
            "daily peak_volume / capacity * 100)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "integer",
                    "description": "The tower ID.",
                },
            },
            "required": ["tower_id"],
        },
    )
    def get_utilization_report(self, tower_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sectors = conn.execute(
            "SELECT sector_id, sector_label, current_capacity_mbps "
            "FROM sectors WHERE tower_id = ?",
            (tower_id,),
        ).fetchall()
        result = []
        for sec in sectors:
            sid = sec["sector_id"]
            cap = sec["current_capacity_mbps"]
            traffic = conn.execute(
                "SELECT avg_volume_mbps, peak_volume_mbps "
                "FROM traffic_daily WHERE sector_id = ?",
                (sid,),
            ).fetchall()
            if not traffic or cap == 0:
                result.append({
                    "sector_id": sid,
                    "sector_label": sec["sector_label"],
                    "avg_utilization_pct": 0.0,
                    "peak_utilization_pct": 0.0,
                })
                continue
            avg_utils = [r["avg_volume_mbps"] / cap * 100 for r in traffic]
            peak_utils = [r["peak_volume_mbps"] / cap * 100 for r in traffic]
            result.append({
                "sector_id": sid,
                "sector_label": sec["sector_label"],
                "avg_utilization_pct": round(sum(avg_utils) / len(avg_utils), 2),
                "peak_utilization_pct": round(max(peak_utils), 2),
            })
        conn.close()
        return {"tower_id": tower_id, "sectors": result}

    @tool(
        description=(
            "Returns handoff failure statistics for a tower aggregated "
            "across all months and adjacent towers. Includes an "
            "overall_failure_rate_pct and a per-adjacent-tower breakdown."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "integer",
                    "description": "The tower ID.",
                },
            },
            "required": ["tower_id"],
        },
    )
    def get_handoff_failure_report(self, tower_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT h.target_tower_id, t.tower_name AS target_tower_name, "
            "SUM(h.total_attempts) AS total_attempts, "
            "SUM(h.failed) AS total_failed "
            "FROM handoff_events h "
            "JOIN towers t ON h.target_tower_id = t.tower_id "
            "WHERE h.source_tower_id = ? "
            "GROUP BY h.target_tower_id",
            (tower_id,),
        ).fetchall()
        conn.close()
        total_att = sum(r["total_attempts"] for r in rows)
        total_fail = sum(r["total_failed"] for r in rows)
        overall = round(total_fail / total_att * 100, 2) if total_att else 0.0
        details = []
        for r in rows:
            details.append({
                "target_tower_id": r["target_tower_id"],
                "target_tower_name": r["target_tower_name"],
                "total_attempts": r["total_attempts"],
                "total_failed": r["total_failed"],
                "failure_rate_pct": (
                    round(r["total_failed"] / r["total_attempts"] * 100, 2)
                    if r["total_attempts"] else 0.0
                ),
            })
        return {
            "tower_id": tower_id,
            "overall_failure_rate_pct": overall,
            "adjacent_towers": details,
        }

    @tool(
        description=(
            "Searches for construction permits within a given radius of a "
            "tower. Returns permit details including project type, "
            "estimated new residents, and distance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tower_id": {
                    "type": "integer",
                    "description": "The tower ID to search around.",
                },
                "radius_km": {
                    "type": "number",
                    "description": "Search radius in km. Default 3.0.",
                },
            },
            "required": ["tower_id"],
        },
    )
    def get_nearby_permits(self, tower_id: int, radius_km: float = 3.0) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        tower = conn.execute(
            "SELECT latitude, longitude FROM towers WHERE tower_id = ?",
            (tower_id,),
        ).fetchone()
        if not tower:
            conn.close()
            return {"tower_id": tower_id, "permits": [], "error": "Tower not found."}
        tlat, tlon = tower["latitude"], tower["longitude"]
        permits = conn.execute(
            "SELECT permit_id, project_name, project_type, latitude, "
            "longitude, estimated_new_residents, "
            "estimated_new_commercial_sqft, status, expected_completion "
            "FROM construction_permits"
        ).fetchall()
        conn.close()
        nearby = []
        for p in permits:
            d = _haversine_km(tlat, tlon, p["latitude"], p["longitude"])
            if d <= radius_km:
                rec = dict(p)
                rec["distance_km"] = round(d, 2)
                del rec["latitude"]
                del rec["longitude"]
                nearby.append(rec)
        nearby.sort(key=lambda x: x["distance_km"])
        return {"tower_id": tower_id, "radius_km": radius_km, "permits": nearby}

    # ===================================================================
    # step
    # ===================================================================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.
        """
        eval_criteria: Dict[str, Any] = {}
        gt = self._compute_ground_truth()

        # --- C1: output file exists with correct columns (10 pts) ---
        csv_path = os.path.join(self.workspace, "upgrade_priorities.csv")
        c1_pass = False
        c1_reason = ""
        submitted_rows = []
        expected_cols = [
            "tower_id", "tower_name", "priority_rank", "priority_score",
            "avg_utilization_pct", "peak_utilization_pct",
            "handoff_failure_rate_pct", "permit_impact_score",
            "recommended_ru_model", "estimated_cost_usd",
        ]
        if os.path.isfile(csv_path):
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                cols = [c.strip() for c in (reader.fieldnames or [])]
                if set(expected_cols).issubset(set(cols)):
                    c1_pass = True
                    for row in reader:
                        submitted_rows.append(
                            {k.strip(): v.strip() for k, v in row.items()}
                        )
                else:
                    c1_reason = (
                        f"Missing columns: {set(expected_cols) - set(cols)}"
                    )
        else:
            c1_reason = "upgrade_priorities.csv not found."
        eval_criteria["output_file_format"] = {
            "passed": c1_pass,
            "score": 10 if c1_pass else 0,
            "max_score": 10,
            "reason": c1_reason if not c1_pass else "",
        }

        # --- C2: correct set of eligible towers (25 pts) ---
        gt_ids = set(r["tower_id"] for r in gt)
        sub_ids = set()
        for r in submitted_rows:
            try:
                sub_ids.add(int(r["tower_id"]))
            except (KeyError, ValueError):
                pass
        if gt_ids:
            overlap = gt_ids & sub_ids
            precision = len(overlap) / len(sub_ids) if sub_ids else 0
            recall = len(overlap) / len(gt_ids)
            f1 = (2 * precision * recall / (precision + recall)
                   if (precision + recall) else 0)
            c2_score = round(f1 * 25)
        else:
            c2_score = 25 if not sub_ids else 0
        c2_pass = c2_score == 25
        eval_criteria["eligible_towers"] = {
            "passed": c2_pass,
            "score": c2_score,
            "max_score": 25,
            "reason": "" if c2_pass else (
                f"Expected towers {sorted(gt_ids)}, got {sorted(sub_ids)}"
            ),
        }

        # --- C3: priority scores correct within tolerance (20 pts) ---
        gt_map = {r["tower_id"]: r for r in gt}
        c3_correct = 0
        c3_total = max(len(gt), 1)
        for row in submitted_rows:
            try:
                tid = int(row["tower_id"])
                sub_score = float(row["priority_score"])
            except (KeyError, ValueError):
                continue
            if tid in gt_map:
                expected = gt_map[tid]["priority_score"]
                if abs(sub_score - expected) <= 0.5:
                    c3_correct += 1
        c3_score = round(c3_correct / c3_total * 20)
        eval_criteria["priority_scores"] = {
            "passed": c3_score == 20,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_score == 20 else (
                f"{c3_correct}/{c3_total} scores within tolerance."
            ),
        }

        # --- C4: correct ranking order (15 pts) ---
        gt_ranking = [r["tower_id"] for r in gt]  # already sorted
        sub_ranking = []
        for row in submitted_rows:
            try:
                sub_ranking.append(int(row["tower_id"]))
            except (KeyError, ValueError):
                pass
        if gt_ranking and sub_ranking:
            # Kendall-tau style: fraction of pairwise order preserved
            correct_pairs = 0
            total_pairs = 0
            for i in range(len(gt_ranking)):
                for j in range(i + 1, len(gt_ranking)):
                    a, b = gt_ranking[i], gt_ranking[j]
                    if a in sub_ranking and b in sub_ranking:
                        total_pairs += 1
                        if sub_ranking.index(a) < sub_ranking.index(b):
                            correct_pairs += 1
            ratio = correct_pairs / total_pairs if total_pairs else 0
            c4_score = round(ratio * 15)
        else:
            c4_score = 0
        eval_criteria["ranking_order"] = {
            "passed": c4_score == 15,
            "score": c4_score,
            "max_score": 15,
            "reason": "" if c4_score == 15 else "Ranking mismatch.",
        }

        # --- C5: correct RU recommendations (20 pts) ---
        c5_correct = 0
        c5_total = max(len(gt), 1)
        for row in submitted_rows:
            try:
                tid = int(row["tower_id"])
                sub_ru = row.get("recommended_ru_model", "").strip()
            except (KeyError, ValueError):
                continue
            if tid in gt_map and sub_ru == gt_map[tid]["recommended_ru_model"]:
                c5_correct += 1
        c5_score = round(c5_correct / c5_total * 20)
        eval_criteria["ru_recommendations"] = {
            "passed": c5_score == 20,
            "score": c5_score,
            "max_score": 20,
            "reason": "" if c5_score == 20 else (
                f"{c5_correct}/{c5_total} correct RU recommendations."
            ),
        }

        # --- C6: response summary mentions top-3 towers (10 pts) ---
        top3_ids = [str(r["tower_id"]) for r in gt[:3]]
        top3_names = [r["tower_name"] for r in gt[:3]]
        found = 0
        for tid, tname in zip(top3_ids, top3_names):
            if tid in action or tname in action:
                found += 1
        c6_score = round(found / max(len(top3_ids), 1) * 10)
        eval_criteria["response_summary"] = {
            "passed": c6_score == 10,
            "score": c6_score,
            "max_score": 10,
            "reason": "" if c6_score == 10 else (
                "Response should mention top-3 tower IDs or names."
            ),
        }

        total_score = sum(v["score"] for v in eval_criteria.values())
        max_score = sum(v["max_score"] for v in eval_criteria.values())

        return total_score / max_score, {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ===================================================================
    # ground truth computation (used by step & verify)
    # ===================================================================

    def _load_policy(self):
        with open(os.path.join(self.workspace, "upgrade_policy.yaml")) as f:
            return yaml.safe_load(f)

    def _load_weights(self):
        with open(os.path.join(self.workspace, "priority_weights.json")) as f:
            return json.load(f)

    def _load_catalog(self):
        rows = []
        with open(os.path.join(self.workspace, "radio_unit_catalog.csv"),
                  newline="") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "model": r["model"],
                    "frequency_bands": set(r["frequency_bands"].split(";")),
                    "capacity_mbps": int(r["capacity_mbps"]),
                    "power_watts": int(r["power_watts"]),
                    "cost_usd": int(r["cost_usd"]),
                    "form_factor": r["form_factor"],
                })
        return rows

    def _load_band_compat(self):
        with open(os.path.join(self.workspace, "band_compatibility.yaml")) as f:
            return yaml.safe_load(f)

    def _load_site_assessments(self):
        """Parse all site assessment batch files from workspace."""
        assessments: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("site_assessment_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            records = []
            if fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
            elif fname.endswith(".csv"):
                with open(fpath, newline="") as f:
                    records = list(csv.DictReader(f))
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    text = f.read()
                blocks = text.strip().split("---")
                for block in blocks:
                    block = block.strip()
                    if not block:
                        continue
                    rec = {}
                    for line in block.split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k = k.strip().lower().replace(" ", "_").replace("(", "").replace(")", "")
                            rec[k] = v.strip()
                    if rec:
                        records.append(rec)
            for rec in records:
                tid = int(rec.get("tower_id", 0))
                if tid:
                    assessments[tid] = {
                        "structural_grade": str(
                            rec.get("structural_grade", "D")
                        ),
                        "power_headroom_kw": float(
                            rec.get("power_headroom_kw", 0)
                        ),
                        "max_additional_ru_slots": int(
                            rec.get("max_additional_ru_slots", 0)
                        ),
                    }
        return assessments

    def _compute_ground_truth(self) -> list:
        """Return the sorted list of eligible tower dicts."""
        policy = self._load_policy()
        weights = self._load_weights()
        catalog = self._load_catalog()
        band_compat = self._load_band_compat()
        assessments = self._load_site_assessments()

        avg_thresh = policy["utilization_thresholds"]["avg_utilization_pct"]
        peak_thresh = policy["utilization_thresholds"]["peak_utilization_pct"]
        handoff_thresh = policy["handoff_failure_threshold_pct"]
        permit_min_res = policy["permit_impact"]["min_new_residents"]
        permit_radius = policy["permit_impact"]["radius_km"]
        min_factors = policy["upgrade_eligibility"]["min_factors_triggered"]
        ok_grades = set(policy["upgrade_eligibility"]["structural_grade_required"])
        class_mult = policy["tower_class_multiplier"]

        w_avg = weights["avg_utilization_score_weight"]
        w_peak = weights["peak_utilization_score_weight"]
        w_hand = weights["handoff_failure_score_weight"]
        w_perm = weights["permit_impact_score_weight"]

        form_constraints = band_compat["form_factor_constraints"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        towers = conn.execute(
            "SELECT * FROM towers ORDER BY tower_id"
        ).fetchall()

        results = []
        for tw in towers:
            tid = tw["tower_id"]

            # -- utilization --
            sectors = conn.execute(
                "SELECT sector_id, current_capacity_mbps, frequency_band "
                "FROM sectors WHERE tower_id = ?",
                (tid,),
            ).fetchall()
            sector_avg_utils = []
            sector_peak_utils = []
            tower_bands = set()
            for sec in sectors:
                tower_bands.add(sec["frequency_band"])
                cap = sec["current_capacity_mbps"]
                traffic = conn.execute(
                    "SELECT avg_volume_mbps, peak_volume_mbps "
                    "FROM traffic_daily WHERE sector_id = ?",
                    (sec["sector_id"],),
                ).fetchall()
                if not traffic or cap == 0:
                    continue
                avg_u = sum(r["avg_volume_mbps"] for r in traffic) / len(traffic) / cap * 100
                peak_u = max(r["peak_volume_mbps"] for r in traffic) / cap * 100
                sector_avg_utils.append(avg_u)
                sector_peak_utils.append(peak_u)

            tower_avg_util = (
                sum(sector_avg_utils) / len(sector_avg_utils)
                if sector_avg_utils else 0
            )
            tower_peak_util = max(sector_peak_utils) if sector_peak_utils else 0

            # -- handoff --
            hand = conn.execute(
                "SELECT SUM(total_attempts) AS ta, SUM(failed) AS tf "
                "FROM handoff_events WHERE source_tower_id = ?",
                (tid,),
            ).fetchone()
            handoff_rate = (
                hand["tf"] / hand["ta"] * 100
                if hand["ta"] and hand["ta"] > 0 else 0
            )

            # -- permits --
            tlat = tw["latitude"]
            tlon = tw["longitude"]
            permits = conn.execute(
                "SELECT latitude, longitude, estimated_new_residents "
                "FROM construction_permits"
            ).fetchall()
            total_residents = 0
            for p in permits:
                d = _haversine_km(tlat, tlon, p["latitude"], p["longitude"])
                if d <= permit_radius:
                    total_residents += p["estimated_new_residents"]

            # -- factors triggered --
            factors = 0
            if tower_avg_util > avg_thresh:
                factors += 1
            if tower_peak_util > peak_thresh:
                factors += 1
            if handoff_rate > handoff_thresh:
                factors += 1
            if total_residents > permit_min_res:
                factors += 1

            # -- eligibility --
            sa = assessments.get(tid, {})
            grade = sa.get("structural_grade", "D")
            if factors < min_factors or grade not in ok_grades:
                continue

            # -- scoring --
            avg_score = min(100, tower_avg_util)
            peak_score = min(100, tower_peak_util)
            hand_score = min(100, round(handoff_rate / 15 * 100, 2))
            perm_score = min(100, round(total_residents / 5000 * 100, 2))

            mult = class_mult.get(tw["tower_class"], 1.0)
            priority = round(
                (avg_score * w_avg + peak_score * w_peak
                 + hand_score * w_hand + perm_score * w_perm) * mult,
                2,
            )

            # -- RU recommendation --
            ok_forms = form_constraints.get(tw["tower_class"], ["standard"])
            candidates = [
                c for c in catalog
                if tower_bands.issubset(c["frequency_bands"])
                and c["form_factor"] in ok_forms
            ]
            candidates.sort(key=lambda c: (c["cost_usd"], c["model"]))
            rec_ru = candidates[0]["model"] if candidates else "NONE"
            rec_cost = candidates[0]["cost_usd"] if candidates else 0

            results.append({
                "tower_id": tid,
                "tower_name": tw["tower_name"],
                "priority_score": priority,
                "avg_utilization_pct": round(tower_avg_util, 2),
                "peak_utilization_pct": round(tower_peak_util, 2),
                "handoff_failure_rate_pct": round(handoff_rate, 2),
                "permit_impact_score": round(perm_score, 2),
                "recommended_ru_model": rec_ru,
                "estimated_cost_usd": rec_cost,
                "tower_class": tw["tower_class"],
            })

        conn.close()

        # Sort by priority_score desc, tower_id asc as tiebreaker
        results.sort(key=lambda r: (-r["priority_score"], r["tower_id"]))
        for i, r in enumerate(results, 1):
            r["priority_rank"] = i

        return results

    # ===================================================================
    # verify
    # ===================================================================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as _csv

        # --- 1. Read workspace config files ---
        policy_path = os.path.join(self.workspace, "upgrade_policy.yaml")
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        weights_path = os.path.join(self.workspace, "priority_weights.json")
        with open(weights_path) as f:
            weights = json.load(f)

        catalog_path = os.path.join(self.workspace, "radio_unit_catalog.csv")
        catalog = []
        with open(catalog_path, newline="") as f:
            for row in _csv.DictReader(f):
                catalog.append({
                    "model": row["model"],
                    "frequency_bands": set(row["frequency_bands"].split(";")),
                    "capacity_mbps": int(row["capacity_mbps"]),
                    "cost_usd": int(row["cost_usd"]),
                    "form_factor": row["form_factor"],
                })

        compat_path = os.path.join(self.workspace, "band_compatibility.yaml")
        with open(compat_path) as f:
            band_compat = yaml.safe_load(f)

        form_constraints = band_compat["form_factor_constraints"]

        # Read site assessments
        assessments: Dict[int, dict] = {}
        for fname in sorted(os.listdir(self.workspace)):
            if not fname.startswith("site_assessment_batch_"):
                continue
            fpath = os.path.join(self.workspace, fname)
            records = []
            if fname.endswith(".json"):
                with open(fpath) as f:
                    records = json.load(f)
            elif fname.endswith(".csv"):
                with open(fpath, newline="") as f:
                    records = list(_csv.DictReader(f))
            elif fname.endswith(".yaml"):
                with open(fpath) as f:
                    records = yaml.safe_load(f)
            elif fname.endswith(".txt"):
                with open(fpath) as f:
                    text = f.read()
                blocks = text.strip().split("---")
                for block in blocks:
                    block = block.strip()
                    if not block:
                        continue
                    rec = {}
                    for line in block.split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k = k.strip().lower().replace(" ", "_").replace("(", "").replace(")", "")
                            rec[k] = v.strip()
                    if rec:
                        records.append(rec)
            for rec in records:
                tid = int(rec.get("tower_id", 0))
                if tid:
                    assessments[tid] = {
                        "structural_grade": str(rec.get("structural_grade", "D")),
                        "power_headroom_kw": float(rec.get("power_headroom_kw", 0)),
                        "max_additional_ru_slots": int(rec.get("max_additional_ru_slots", 0)),
                    }

        # Extract thresholds
        avg_thresh = policy["utilization_thresholds"]["avg_utilization_pct"]
        peak_thresh = policy["utilization_thresholds"]["peak_utilization_pct"]
        handoff_thresh = policy["handoff_failure_threshold_pct"]
        permit_min_res = policy["permit_impact"]["min_new_residents"]
        permit_radius = policy["permit_impact"]["radius_km"]
        min_factors = policy["upgrade_eligibility"]["min_factors_triggered"]
        ok_grades = set(policy["upgrade_eligibility"]["structural_grade_required"])
        class_mult = policy["tower_class_multiplier"]

        w_avg = weights["avg_utilization_score_weight"]
        w_peak = weights["peak_utilization_score_weight"]
        w_hand = weights["handoff_failure_score_weight"]
        w_perm = weights["permit_impact_score_weight"]

        # --- 2. Gather data via tools ---
        tool_call_count = 0

        # List all towers
        all_towers = []
        page = 1
        while True:
            res = self.tools["list_towers"](page=page, page_size=10)
            tool_call_count += 1
            all_towers.extend(res["towers"])
            if page >= res["total_pages"]:
                break
            page += 1

        eligible = []

        for tw in all_towers:
            tid = tw["tower_id"]

            # Utilization
            util_res = self.tools["get_utilization_report"](tower_id=tid)
            tool_call_count += 1
            sec_avg = [s["avg_utilization_pct"] for s in util_res["sectors"]]
            sec_peak = [s["peak_utilization_pct"] for s in util_res["sectors"]]
            tower_avg_util = sum(sec_avg) / len(sec_avg) if sec_avg else 0
            tower_peak_util = max(sec_peak) if sec_peak else 0

            # Handoff
            hand_res = self.tools["get_handoff_failure_report"](tower_id=tid)
            tool_call_count += 1
            handoff_rate = hand_res["overall_failure_rate_pct"]

            # Nearby permits
            perm_res = self.tools["get_nearby_permits"](
                tower_id=tid, radius_km=permit_radius
            )
            tool_call_count += 1
            total_residents = sum(
                p["estimated_new_residents"] for p in perm_res["permits"]
            )

            # Count factors triggered
            factors = 0
            if tower_avg_util > avg_thresh:
                factors += 1
            if tower_peak_util > peak_thresh:
                factors += 1
            if handoff_rate > handoff_thresh:
                factors += 1
            if total_residents > permit_min_res:
                factors += 1

            # Check eligibility
            sa = assessments.get(tid, {})
            grade = sa.get("structural_grade", "D")
            if factors < min_factors or grade not in ok_grades:
                continue

            # Get sector frequency bands for RU recommendation
            sec_res = self.tools["get_tower_sectors"](tower_id=tid)
            tool_call_count += 1
            tower_bands = set(s["frequency_band"] for s in sec_res["sectors"])

            # Scoring
            avg_score = min(100, tower_avg_util)
            peak_score = min(100, tower_peak_util)
            hand_score = min(100, round(handoff_rate / 15 * 100, 2))
            perm_score = min(100, round(total_residents / 5000 * 100, 2))

            mult = class_mult.get(tw["tower_class"], 1.0)
            priority = round(
                (avg_score * w_avg + peak_score * w_peak
                 + hand_score * w_hand + perm_score * w_perm) * mult,
                2,
            )

            # RU recommendation
            ok_forms = form_constraints.get(tw["tower_class"], ["standard"])
            candidates = [
                c for c in catalog
                if tower_bands.issubset(c["frequency_bands"])
                and c["form_factor"] in ok_forms
            ]
            candidates.sort(key=lambda c: (c["cost_usd"], c["model"]))
            rec_ru = candidates[0]["model"] if candidates else "NONE"
            rec_cost = candidates[0]["cost_usd"] if candidates else 0

            eligible.append({
                "tower_id": tid,
                "tower_name": tw["tower_name"],
                "priority_score": priority,
                "avg_utilization_pct": round(tower_avg_util, 2),
                "peak_utilization_pct": round(tower_peak_util, 2),
                "handoff_failure_rate_pct": round(handoff_rate, 2),
                "permit_impact_score": round(perm_score, 2),
                "recommended_ru_model": rec_ru,
                "estimated_cost_usd": rec_cost,
            })

        # Sort
        eligible.sort(key=lambda r: (-r["priority_score"], r["tower_id"]))
        for i, r in enumerate(eligible, 1):
            r["priority_rank"] = i

        # --- 3. Write output CSV ---
        out_path = os.path.join(self.workspace, "upgrade_priorities.csv")
        cols = [
            "tower_id", "tower_name", "priority_rank", "priority_score",
            "avg_utilization_pct", "peak_utilization_pct",
            "handoff_failure_rate_pct", "permit_impact_score",
            "recommended_ru_model", "estimated_cost_usd",
        ]
        with open(out_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(eligible)

        # --- 4. Build action string ---
        lines = ["Upgrade Priority Analysis Complete.", ""]
        if len(eligible) >= 3:
            lines.append("Top 3 towers requiring upgrade:")
            for r in eligible[:3]:
                lines.append(
                    f"  #{r['priority_rank']} Tower {r['tower_id']} "
                    f"({r['tower_name']}) - Priority Score: "
                    f"{r['priority_score']:.2f}, Recommended RU: "
                    f"{r['recommended_ru_model']}"
                )
        elif eligible:
            lines.append("Towers requiring upgrade:")
            for r in eligible:
                lines.append(
                    f"  #{r['priority_rank']} Tower {r['tower_id']} "
                    f"({r['tower_name']}) - Priority Score: "
                    f"{r['priority_score']:.2f}, Recommended RU: "
                    f"{r['recommended_ru_model']}"
                )
        else:
            lines.append("No towers meet the upgrade eligibility criteria.")

        lines.append("")
        lines.append(f"Total eligible towers: {len(eligible)}")
        lines.append(f"Results saved to upgrade_priorities.csv")
        lines.append(f"Total tool calls made: {tool_call_count}")

        action = "\n".join(lines)
        return self.step(action)
