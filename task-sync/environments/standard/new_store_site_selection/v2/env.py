#!/usr/bin/env python3
"""Environment for retail site-selection task."""

import csv
import json
import math
import os
import re
import sqlite3
from typing import Any, Dict, List, Tuple

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

    # ===================================================================
    # Tool methods
    # ===================================================================

    @tool(
        description=(
            "Lists all zones in the study area with basic demographic overview. "
            "Returns paginated results with zone_id, zone_name, population, and "
            "median_household_income for quick filtering."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of zones to return per page (default 20).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of zones to skip for pagination (default 0).",
                },
            },
            "required": [],
        },
    )
    def list_zones(self, limit: int = 20, offset: int = 0) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT zone_id, zone_name, population, median_household_income "
            "FROM zone_demographics ORDER BY zone_id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        zones = [dict(r) for r in cur.fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM zone_demographics").fetchone()[0]
        conn.close()
        return {"zones": zones, "total": total, "limit": limit, "offset": offset}

    @tool(
        description=(
            "Returns full demographic details for a single zone, including "
            "median_age, household_count, employment_rate, and population_growth_rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone identifier, e.g. 'Z001'.",
                },
            },
            "required": ["zone_id"],
        },
    )
    def get_zone_details(self, zone_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM zone_demographics WHERE zone_id = ?", (zone_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Zone {zone_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Returns candidate sites located in a given zone. "
            "Results are paginated and include site_id, site_name, zone_id, "
            "area_sqft, and site_type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "zone_id": {
                    "type": "string",
                    "description": "The zone identifier, e.g. 'Z001'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per page (default 20).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip (default 0).",
                },
            },
            "required": ["zone_id"],
        },
    )
    def get_sites_in_zone(self, zone_id: str, limit: int = 20, offset: int = 0) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT site_id, site_name, zone_id, area_sqft, site_type "
            "FROM candidate_sites WHERE zone_id = ? ORDER BY site_id LIMIT ? OFFSET ?",
            (zone_id, limit, offset),
        )
        sites = [dict(r) for r in cur.fetchall()]
        total = conn.execute(
            "SELECT COUNT(*) FROM candidate_sites WHERE zone_id = ?", (zone_id,)
        ).fetchone()[0]
        conn.close()
        return {"sites": sites, "total": total, "limit": limit, "offset": offset}

    @tool(
        description=(
            "Returns complete details for a single candidate site including "
            "coordinates, area, site_type, parking_spaces, and frontage_meters."
        ),
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The site identifier, e.g. 'S001'.",
                },
            },
            "required": ["site_id"],
        },
    )
    def get_site_details(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM candidate_sites WHERE site_id = ?", (site_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Site {site_id} not found."}
        return dict(row)

    @tool(
        description=(
            "Finds competitor stores within a given radius (in kilometres) of the "
            "specified site. Returns each competitor's id, brand_name, category, "
            "distance_km, store_size_sqft, and estimated_monthly_revenue."
        ),
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The candidate site identifier, e.g. 'S001'.",
                },
                "radius_km": {
                    "type": "number",
                    "description": "Search radius in kilometres.",
                },
            },
            "required": ["site_id", "radius_km"],
        },
    )
    def get_nearby_competitors(self, site_id: str, radius_km: float) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        site = conn.execute(
            "SELECT latitude, longitude FROM candidate_sites WHERE site_id = ?",
            (site_id,),
        ).fetchone()
        if site is None:
            conn.close()
            return {"error": f"Site {site_id} not found."}
        s_lat, s_lon = site["latitude"], site["longitude"]
        comps = conn.execute("SELECT * FROM competitors").fetchall()
        conn.close()
        nearby = []
        for c in comps:
            d = _haversine(s_lat, s_lon, c["latitude"], c["longitude"])
            if d <= radius_km:
                nearby.append({
                    "competitor_id": c["competitor_id"],
                    "brand_name": c["brand_name"],
                    "category": c["category"],
                    "distance_km": round(d, 3),
                    "store_size_sqft": c["store_size_sqft"],
                    "estimated_monthly_revenue": c["estimated_monthly_revenue"],
                })
        nearby.sort(key=lambda x: x["distance_km"])
        return {"site_id": site_id, "radius_km": radius_km, "competitors": nearby}

    @tool(
        description=(
            "Returns the commercial lease listing for a candidate site, including "
            "monthly_rent_per_sqft, lease_term_months, security_deposit_months, "
            "escalation_rate_pct, and available_from date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The candidate site identifier, e.g. 'S001'.",
                },
            },
            "required": ["site_id"],
        },
    )
    def get_lease_info(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM lease_listings WHERE site_id = ?", (site_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"No lease listing found for site {site_id}."}
        return dict(row)

    @tool(
        description=(
            "Returns aggregated traffic statistics for a candidate site: "
            "average weekday and weekend pedestrian and vehicle counts."
        ),
        parameters={
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "The candidate site identifier, e.g. 'S001'.",
                },
            },
            "required": ["site_id"],
        },
    )
    def get_traffic_stats(self, site_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT day_type, avg_pedestrian_count, avg_vehicle_count "
            "FROM traffic_measurements WHERE site_id = ? ORDER BY day_type",
            (site_id,),
        ).fetchall()
        conn.close()
        if not rows:
            return {"error": f"No traffic data for site {site_id}."}
        result = {"site_id": site_id}
        for r in rows:
            prefix = r["day_type"]  # 'weekday' or 'weekend'
            result[f"{prefix}_pedestrian"] = r["avg_pedestrian_count"]
            result[f"{prefix}_vehicle"] = r["avg_vehicle_count"]
        return result

    # ===================================================================
    # Scoring helpers (used by step & verify)
    # ===================================================================

    def _load_configs(self):
        ws = self.workspace
        with open(os.path.join(ws, "eligibility_rules.json")) as f:
            elig = json.load(f)
        with open(os.path.join(ws, "scoring_config.yaml")) as f:
            scoring = yaml.safe_load(f)
        with open(os.path.join(ws, "category_threat_levels.json")) as f:
            threat = json.load(f)
        footfall = {}
        with open(os.path.join(ws, "footfall_model.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                footfall[row["parameter"]] = float(row["value"])
        return elig, scoring, threat, footfall

    def _load_accessibility_ratings(self):
        """Parse all site_inspection_batch_*.txt files → {site_id: rating}."""
        ratings = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_inspection_batch_") and fname.endswith(".txt"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    text = f.read()
                # Extract SITE: Sxxx blocks
                current_site = None
                for line in text.split("\n"):
                    m = re.match(r"^SITE:\s+(S\d+)", line)
                    if m:
                        current_site = m.group(1)
                    m2 = re.match(r"^Accessibility Rating:\s*(\d+)", line)
                    if m2 and current_site:
                        ratings[current_site] = int(m2.group(1))
        return ratings

    def _load_saturation_indices(self):
        """Parse all market_analysis_region_*.md files → {zone_id: saturation}."""
        indices = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("market_analysis_region_") and fname.endswith(".md"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    text = f.read()
                current_zone = None
                for line in text.split("\n"):
                    m = re.match(r"^###\s+(Z\d+)", line)
                    if m:
                        current_zone = m.group(1)
                    m2 = re.search(r"Market Saturation Index\s*\|\s*(\d+)", line)
                    if m2 and current_zone:
                        indices[current_zone] = int(m2.group(1))
                        current_zone = None
        return indices

    def _load_peak_multipliers(self):
        """Parse all traffic_report_sector_*.csv files → {site_id: multiplier}."""
        mults = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("traffic_report_sector_") and fname.endswith(".csv"):
                path = os.path.join(self.workspace, fname)
                with open(path) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        mults[row["site_id"]] = float(row["peak_hour_multiplier"])
        return mults

    def _compute_ground_truth(self):
        """Compute the full ground-truth ranking from DB + workspace files."""
        elig, scoring, threat_levels, footfall = self._load_configs()
        access_ratings = self._load_accessibility_ratings()
        saturation_idx = self._load_saturation_indices()
        peak_mults = self._load_peak_multipliers()

        w = scoring["weights"]
        ds = scoring["demographic_scoring"]
        ts = scoring["traffic_scoring"]
        cs = scoring["competition_scoring"]
        ls = scoring["lease_scoring"]
        acs = scoring["accessibility_scoring"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # 1. Eligible zones
        zones = conn.execute("SELECT * FROM zone_demographics").fetchall()
        eligible_zone_ids = set()
        zone_info = {}
        for z in zones:
            if (z["population"] >= elig["min_zone_population"]
                    and z["median_household_income"] >= elig["min_median_income"]):
                eligible_zone_ids.add(z["zone_id"])
                zone_info[z["zone_id"]] = dict(z)

        # 2. Candidate sites in eligible zones
        sites = conn.execute("SELECT * FROM candidate_sites").fetchall()
        eligible_sites = []
        for s in sites:
            if s["zone_id"] not in eligible_zone_ids:
                continue
            if s["area_sqft"] < elig["min_site_area_sqft"]:
                continue
            eligible_sites.append(dict(s))

        # 3. Lease filter
        lease_ok = []
        for s in eligible_sites:
            lease = conn.execute(
                "SELECT * FROM lease_listings WHERE site_id = ?",
                (s["site_id"],),
            ).fetchone()
            if lease is None:
                continue
            if lease["monthly_rent_per_sqft"] > elig["max_monthly_rent_per_sqft"]:
                continue
            s["lease"] = dict(lease)
            lease_ok.append(s)

        # 4. Competitor filter
        comps_all = [dict(c) for c in conn.execute("SELECT * FROM competitors").fetchall()]
        comp_ok = []
        for s in lease_ok:
            nearby = []
            for c in comps_all:
                d = _haversine(s["latitude"], s["longitude"],
                               c["latitude"], c["longitude"])
                if d <= elig["competitor_check_radius_km"]:
                    nearby.append(c)
            if len(nearby) > elig["max_competitors_in_radius"]:
                continue
            s["nearby_competitors"] = nearby
            comp_ok.append(s)

        # 5. Get traffic
        final_sites = []
        for s in comp_ok:
            traffic = conn.execute(
                "SELECT * FROM traffic_measurements WHERE site_id = ?",
                (s["site_id"],),
            ).fetchall()
            traffic_dict = {}
            for t in traffic:
                traffic_dict[t["day_type"]] = {
                    "pedestrian": t["avg_pedestrian_count"],
                    "vehicle": t["avg_vehicle_count"],
                }
            s["traffic"] = traffic_dict
            final_sites.append(s)
        conn.close()

        # 6. Compute scores
        results = []
        for s in final_sites:
            sid = s["site_id"]
            zid = s["zone_id"]
            z = zone_info[zid]

            # Demographic score
            pop_norm = min(z["population"] / ds["population_scale"], 1.0) * 100
            inc_norm = min(z["median_household_income"] / ds["income_scale"], 1.0) * 100
            growth_norm = min(max(z["population_growth_rate"], 0) / ds["growth_scale"], 1.0) * 100
            demo_score = (pop_norm * ds["population_weight"]
                          + inc_norm * ds["income_weight"]
                          + growth_norm * ds["growth_weight"])

            # Traffic score
            t = s["traffic"]
            wd_ped = t.get("weekday", {}).get("pedestrian", 0)
            we_ped = t.get("weekend", {}).get("pedestrian", 0)
            wd_veh = t.get("weekday", {}).get("vehicle", 0)
            we_veh = t.get("weekend", {}).get("vehicle", 0)
            avg_daily_ped = (wd_ped * 5 + we_ped * 2) / 7.0
            avg_daily_veh = (wd_veh * 5 + we_veh * 2) / 7.0
            traffic_score = min(100.0,
                                (avg_daily_ped * ts["pedestrian_weight"]
                                 + avg_daily_veh * ts["vehicle_weight"])
                                / ts["divisor"])

            # Competition score
            total_threat = sum(
                threat_levels.get(c["category"], 1.0)
                for c in s["nearby_competitors"]
            )
            raw_comp = max(0.0, cs["base_score"] - total_threat * cs["penalty_per_threat_point"])
            sat = saturation_idx.get(zid, 50)
            adj_comp = raw_comp * (1.0 - sat / cs["saturation_divisor"])

            # Lease score
            rent = s["lease"]["monthly_rent_per_sqft"]
            rent_score = max(0.0, (1.0 - rent / ls["max_rent_reference"]) * 100)
            term_bonus = (ls["term_bonus_points"]
                          if s["lease"]["lease_term_months"] >= ls["term_bonus_threshold_months"]
                          else 0)
            lease_score = min(ls["score_cap"], rent_score + term_bonus)

            # Accessibility score
            rating = access_ratings.get(sid, acs["default_rating"])
            access_score = rating * acs["multiplier"]

            # Composite
            composite = (demo_score * w["demographic"]
                         + traffic_score * w["traffic"]
                         + adj_comp * w["competition"]
                         + lease_score * w["lease"]
                         + access_score * w["accessibility"])
            composite = round(composite, 2)

            # Projected annual footfall
            comp_th_high = footfall["competition_threshold_high"]
            comp_th_low = footfall["competition_threshold_low"]
            if adj_comp >= comp_th_high:
                comp_adj = footfall["competition_adj_low"]
            elif adj_comp >= comp_th_low:
                comp_adj = footfall["competition_adj_medium"]
            else:
                comp_adj = footfall["competition_adj_high"]

            peak_boost = peak_mults.get(sid, footfall["default_peak_boost"])
            projected = (
                (avg_daily_ped * footfall["base_capture_rate"] * comp_adj
                 + avg_daily_veh * footfall["vehicle_conversion_rate"])
                * footfall["operating_days"]
                * footfall["seasonal_factor"]
                * (1.0 + peak_boost * footfall["peak_boost_weight"])
            )
            projected = round(projected)

            results.append({
                "site_id": sid,
                "site_name": s["site_name"],
                "zone_id": zid,
                "zone_name": z["zone_name"],
                "composite_score": composite,
                "projected_annual_footfall": projected,
            })

        # Sort: composite desc, footfall desc, site_id asc
        results.sort(key=lambda x: (-x["composite_score"],
                                     -x["projected_annual_footfall"],
                                     x["site_id"]))
        for i, r in enumerate(results, 1):
            r["rank"] = i
        return results

    # ===================================================================
    # step
    # ===================================================================

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
        criteria = {}

        # ---- 1. Output file exists with correct columns (10 pts) ----
        csv_path = os.path.join(self.workspace, "site_rankings.csv")
        file_ok = False
        parsed_rows = []
        expected_cols = ["rank", "site_id", "site_name", "zone_id",
                         "zone_name", "composite_score", "projected_annual_footfall"]
        if os.path.isfile(csv_path):
            try:
                with open(csv_path) as f:
                    reader = csv.DictReader(f)
                    cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    if all(c in cols for c in expected_cols):
                        for row in reader:
                            parsed_rows.append({k.strip(): v.strip() for k, v in row.items()})
                        file_ok = True
            except Exception:
                pass
        criteria["output_file_format"] = {
            "passed": file_ok,
            "score": 10 if file_ok else 0,
            "max_score": 10,
            "reason": "" if file_ok else "site_rankings.csv missing or has wrong columns",
        }

        # ---- 2. Correct eligible sites (20 pts) ----
        gt_ids = {r["site_id"] for r in gt}
        agent_ids = {r["site_id"] for r in parsed_rows}
        if gt_ids or agent_ids:
            jaccard = len(gt_ids & agent_ids) / len(gt_ids | agent_ids) if (gt_ids | agent_ids) else 0
        else:
            jaccard = 1.0
        site_score = round(jaccard * 20, 2)
        criteria["eligible_sites"] = {
            "passed": jaccard == 1.0,
            "score": site_score,
            "max_score": 20,
            "reason": ("" if jaccard == 1.0
                       else f"Jaccard={jaccard:.2f}; expected {len(gt_ids)} sites, got {len(agent_ids)}"),
        }

        # ---- 3. Ranking order (20 pts) ----
        gt_order = [r["site_id"] for r in gt]
        agent_order = [r["site_id"] for r in parsed_rows]
        if len(agent_order) >= 2 and len(gt_order) >= 2:
            # Kendall-tau style: fraction of pairwise comparisons that match
            # restricted to common sites
            common = [s for s in agent_order if s in gt_ids]
            gt_rank_map = {sid: i for i, sid in enumerate(gt_order)}
            concordant = 0
            total_pairs = 0
            for i in range(len(common)):
                for j in range(i + 1, len(common)):
                    total_pairs += 1
                    agent_before = common.index(common[i]) < common.index(common[j])
                    gt_before = gt_rank_map.get(common[i], 999) < gt_rank_map.get(common[j], 999)
                    if agent_before == gt_before:
                        concordant += 1
            rank_ratio = concordant / total_pairs if total_pairs > 0 else 0
        elif len(agent_order) == 1 and agent_order == gt_order:
            rank_ratio = 1.0
        else:
            rank_ratio = 0.0
        rank_score = round(rank_ratio * 20, 2)
        criteria["ranking_order"] = {
            "passed": rank_ratio == 1.0,
            "score": rank_score,
            "max_score": 20,
            "reason": ("" if rank_ratio == 1.0
                       else f"Pairwise concordance={rank_ratio:.2f}"),
        }

        # ---- 4. Composite scores accuracy (15 pts) ----
        gt_scores = {r["site_id"]: r["composite_score"] for r in gt}
        correct_scores = 0
        total_scores = max(len(gt_scores), 1)
        for row in parsed_rows:
            sid = row.get("site_id", "")
            try:
                agent_cs = float(row.get("composite_score", ""))
            except (ValueError, TypeError):
                continue
            if sid in gt_scores:
                if abs(agent_cs - gt_scores[sid]) <= max(0.01 * abs(gt_scores[sid]), 0.05):
                    correct_scores += 1
        cs_ratio = correct_scores / total_scores
        cs_score = round(cs_ratio * 15, 2)
        criteria["composite_scores"] = {
            "passed": cs_ratio == 1.0,
            "score": cs_score,
            "max_score": 15,
            "reason": ("" if cs_ratio == 1.0
                       else f"{correct_scores}/{total_scores} scores within tolerance"),
        }

        # ---- 5. Footfall accuracy (15 pts) ----
        gt_ff = {r["site_id"]: r["projected_annual_footfall"] for r in gt}
        correct_ff = 0
        total_ff = max(len(gt_ff), 1)
        for row in parsed_rows:
            sid = row.get("site_id", "")
            try:
                agent_ff = float(row.get("projected_annual_footfall", ""))
            except (ValueError, TypeError):
                continue
            if sid in gt_ff:
                expected = gt_ff[sid]
                if expected == 0:
                    if agent_ff == 0:
                        correct_ff += 1
                elif abs(agent_ff - expected) / abs(expected) <= 0.05:
                    correct_ff += 1
        ff_ratio = correct_ff / total_ff
        ff_score = round(ff_ratio * 15, 2)
        criteria["footfall_accuracy"] = {
            "passed": ff_ratio == 1.0,
            "score": ff_score,
            "max_score": 15,
            "reason": ("" if ff_ratio == 1.0
                       else f"{correct_ff}/{total_ff} footfall values within 5%"),
        }

        # ---- 6. Top-5 mentioned in response (10 pts) ----
        top5_ids = [r["site_id"] for r in gt[:5]]
        top5_names = [r["site_name"] for r in gt[:5]]
        mentioned = 0
        action_lower = action.lower() if action else ""
        for sid, sname in zip(top5_ids, top5_names):
            if sid.lower() in action_lower or sname.lower() in action_lower:
                mentioned += 1
        top5_score = round(mentioned / max(len(top5_ids), 1) * 10, 2)
        criteria["top5_in_response"] = {
            "passed": mentioned == len(top5_ids),
            "score": top5_score,
            "max_score": 10,
            "reason": ("" if mentioned == len(top5_ids)
                       else f"{mentioned}/{len(top5_ids)} top-5 sites mentioned"),
        }

        # ---- 7. Format compliance (10 pts) ----
        fmt_ok = True
        fmt_reasons = []
        for row in parsed_rows:
            cs_str = row.get("composite_score", "")
            # Must have exactly 2 decimal places
            if not re.match(r"^-?\d+\.\d{2}$", cs_str):
                fmt_ok = False
                fmt_reasons.append(f"composite_score '{cs_str}' not 2-decimal format")
                break
            ff_str = row.get("projected_annual_footfall", "")
            if not re.match(r"^-?\d+$", ff_str):
                fmt_ok = False
                fmt_reasons.append(f"projected_annual_footfall '{ff_str}' not integer")
                break
        if not parsed_rows:
            fmt_ok = False
            fmt_reasons.append("No rows to check")
        criteria["format_compliance"] = {
            "passed": fmt_ok,
            "score": 10 if fmt_ok else 0,
            "max_score": 10,
            "reason": "" if fmt_ok else "; ".join(fmt_reasons),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ===================================================================
    # verify
    # ===================================================================

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
        import csv as _csv

        ws = self.workspace
        tool_calls = 0

        # 1. Load config files from workspace
        with open(os.path.join(ws, "eligibility_rules.json")) as f:
            elig = json.load(f)
        with open(os.path.join(ws, "scoring_config.yaml")) as f:
            scoring = yaml.safe_load(f)
        with open(os.path.join(ws, "category_threat_levels.json")) as f:
            threat_levels = json.load(f)
        footfall_params = {}
        with open(os.path.join(ws, "footfall_model.csv")) as f:
            reader = _csv.DictReader(f)
            for row in reader:
                footfall_params[row["parameter"]] = float(row["value"])

        # Load accessibility ratings from inspection files
        access_ratings = self._load_accessibility_ratings()
        saturation_indices = self._load_saturation_indices()
        peak_multipliers = self._load_peak_multipliers()

        w = scoring["weights"]
        ds = scoring["demographic_scoring"]
        ts = scoring["traffic_scoring"]
        cs = scoring["competition_scoring"]
        ls = scoring["lease_scoring"]
        acs = scoring["accessibility_scoring"]

        # 2. List all zones (paginated)
        all_zones = []
        offset = 0
        while True:
            result = self.tools["list_zones"](limit=20, offset=offset)
            tool_calls += 1
            if not result["zones"]:
                break
            all_zones.extend(result["zones"])
            if offset + 20 >= result["total"]:
                break
            offset += 20

        # 3. Filter eligible zones by population and income
        eligible_zone_ids = []
        for z in all_zones:
            if (z["population"] >= elig["min_zone_population"]
                    and z["median_household_income"] >= elig["min_median_income"]):
                eligible_zone_ids.append(z["zone_id"])

        # 4. Get sites in eligible zones
        candidate_sites = []
        for zid in eligible_zone_ids:
            off = 0
            while True:
                result = self.tools["get_sites_in_zone"](zone_id=zid, limit=20, offset=off)
                tool_calls += 1
                if not result["sites"]:
                    break
                candidate_sites.extend(result["sites"])
                if off + 20 >= result["total"]:
                    break
                off += 20

        # 5. Filter by area, get full details
        area_eligible = []
        for s in candidate_sites:
            if s["area_sqft"] < elig["min_site_area_sqft"]:
                continue
            details = self.tools["get_site_details"](site_id=s["site_id"])
            tool_calls += 1
            area_eligible.append(details)

        # 6. Lease filter
        lease_eligible = []
        for s in area_eligible:
            lease = self.tools["get_lease_info"](site_id=s["site_id"])
            tool_calls += 1
            if "error" in lease:
                continue
            if lease["monthly_rent_per_sqft"] > elig["max_monthly_rent_per_sqft"]:
                continue
            s["lease"] = lease
            lease_eligible.append(s)

        # 7. Competitor filter
        comp_eligible = []
        for s in lease_eligible:
            comps = self.tools["get_nearby_competitors"](
                site_id=s["site_id"],
                radius_km=elig["competitor_check_radius_km"],
            )
            tool_calls += 1
            if len(comps["competitors"]) > elig["max_competitors_in_radius"]:
                continue
            s["nearby_competitors"] = comps["competitors"]
            comp_eligible.append(s)

        # 8. Traffic stats
        for s in comp_eligible:
            traffic = self.tools["get_traffic_stats"](site_id=s["site_id"])
            tool_calls += 1
            s["traffic"] = traffic

        # 9. Get zone details for scoring (growth rate)
        zone_details_cache = {}
        for s in comp_eligible:
            zid = s["zone_id"]
            if zid not in zone_details_cache:
                zone_details_cache[zid] = self.tools["get_zone_details"](zone_id=zid)
                tool_calls += 1

        # 10. Compute scores
        results = []
        for s in comp_eligible:
            sid = s["site_id"]
            zid = s["zone_id"]
            z = zone_details_cache[zid]

            # Demographic score
            pop_norm = min(z["population"] / ds["population_scale"], 1.0) * 100
            inc_norm = min(z["median_household_income"] / ds["income_scale"], 1.0) * 100
            growth_norm = min(max(z["population_growth_rate"], 0) / ds["growth_scale"], 1.0) * 100
            demo_score = (pop_norm * ds["population_weight"]
                          + inc_norm * ds["income_weight"]
                          + growth_norm * ds["growth_weight"])

            # Traffic score
            wd_ped = s["traffic"].get("weekday_pedestrian", 0)
            we_ped = s["traffic"].get("weekend_pedestrian", 0)
            wd_veh = s["traffic"].get("weekday_vehicle", 0)
            we_veh = s["traffic"].get("weekend_vehicle", 0)
            avg_daily_ped = (wd_ped * 5 + we_ped * 2) / 7.0
            avg_daily_veh = (wd_veh * 5 + we_veh * 2) / 7.0
            traffic_score = min(100.0,
                                (avg_daily_ped * ts["pedestrian_weight"]
                                 + avg_daily_veh * ts["vehicle_weight"])
                                / ts["divisor"])

            # Competition score
            total_threat = sum(
                threat_levels.get(c["category"], 1.0)
                for c in s["nearby_competitors"]
            )
            raw_comp = max(0.0, cs["base_score"] - total_threat * cs["penalty_per_threat_point"])
            sat = saturation_indices.get(zid, 50)
            adj_comp = raw_comp * (1.0 - sat / cs["saturation_divisor"])

            # Lease score
            rent = s["lease"]["monthly_rent_per_sqft"]
            rent_score = max(0.0, (1.0 - rent / ls["max_rent_reference"]) * 100)
            term_bonus = (ls["term_bonus_points"]
                          if s["lease"]["lease_term_months"] >= ls["term_bonus_threshold_months"]
                          else 0)
            lease_score = min(float(ls["score_cap"]), rent_score + term_bonus)

            # Accessibility score
            rating = access_ratings.get(sid, acs["default_rating"])
            access_score = rating * acs["multiplier"]

            # Composite
            composite = (demo_score * w["demographic"]
                         + traffic_score * w["traffic"]
                         + adj_comp * w["competition"]
                         + lease_score * w["lease"]
                         + access_score * w["accessibility"])
            composite = round(composite, 2)

            # Projected annual footfall
            comp_th_high = footfall_params["competition_threshold_high"]
            comp_th_low = footfall_params["competition_threshold_low"]
            if adj_comp >= comp_th_high:
                f_comp_adj = footfall_params["competition_adj_low"]
            elif adj_comp >= comp_th_low:
                f_comp_adj = footfall_params["competition_adj_medium"]
            else:
                f_comp_adj = footfall_params["competition_adj_high"]

            peak_boost = peak_multipliers.get(sid, footfall_params["default_peak_boost"])
            projected = (
                (avg_daily_ped * footfall_params["base_capture_rate"] * f_comp_adj
                 + avg_daily_veh * footfall_params["vehicle_conversion_rate"])
                * footfall_params["operating_days"]
                * footfall_params["seasonal_factor"]
                * (1.0 + peak_boost * footfall_params["peak_boost_weight"])
            )
            projected = round(projected)

            results.append({
                "rank": 0,
                "site_id": sid,
                "site_name": s["site_name"],
                "zone_id": zid,
                "zone_name": z["zone_name"],
                "composite_score": composite,
                "projected_annual_footfall": projected,
            })

        # Sort: composite desc, footfall desc, site_id asc
        results.sort(key=lambda x: (-x["composite_score"],
                                     -x["projected_annual_footfall"],
                                     x["site_id"]))
        for i, r in enumerate(results, 1):
            r["rank"] = i

        # 11. Write site_rankings.csv
        csv_path = os.path.join(ws, "site_rankings.csv")
        fieldnames = ["rank", "site_id", "site_name", "zone_id",
                       "zone_name", "composite_score", "projected_annual_footfall"]
        with open(csv_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "rank": r["rank"],
                    "site_id": r["site_id"],
                    "site_name": r["site_name"],
                    "zone_id": r["zone_id"],
                    "zone_name": r["zone_name"],
                    "composite_score": f"{r['composite_score']:.2f}",
                    "projected_annual_footfall": r["projected_annual_footfall"],
                })

        # 12. Build action string with top-5 summary
        top5 = results[:5]
        action_lines = ["Retail Site Selection - Final Ranked Shortlist", ""]
        action_lines.append(f"Total eligible sites evaluated: {len(results)}")
        action_lines.append("")
        action_lines.append("Top 5 Recommended Locations:")
        action_lines.append("")
        for r in top5:
            action_lines.append(
                f"Rank {r['rank']}: {r['site_id']} - {r['site_name']} "
                f"(Zone: {r['zone_id']} {r['zone_name']}) | "
                f"Composite Score: {r['composite_score']:.2f} | "
                f"Projected Annual Footfall: {r['projected_annual_footfall']:,}"
            )
        action_lines.append("")
        action_lines.append(
            "The complete ranked shortlist has been saved to site_rankings.csv "
            "with columns: rank, site_id, site_name, zone_id, zone_name, "
            "composite_score, projected_annual_footfall."
        )
        action = "\n".join(action_lines)

        assert tool_calls >= 15, f"Only {tool_calls} tool calls made; need >= 15"
        return self.step(action)


# ===================================================================
# Haversine helper
# ===================================================================

def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
