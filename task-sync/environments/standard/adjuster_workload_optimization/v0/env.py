import os
import re
import csv
import json
import math
import sqlite3
import yaml
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

    # ══════════════════════════════════════════════════════════════════════
    #  TOOLS
    # ══════════════════════════════════════════════════════════════════════

    @tool(
        description="Retrieve a paginated list of pending insurance claims. Returns claim ID, severity score, claim type, territory ID, filing date, and estimated value for claims awaiting assignment.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of claims per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def get_pending_claims(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM claims WHERE status='pending'")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT claim_id, severity_score, claim_type, territory_id, date_filed, estimated_value "
            "FROM claims WHERE status='pending' ORDER BY claim_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"claims": rows, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="Retrieve a paginated list of active adjusters. Returns adjuster ID, name, certification level, base territory ID, and maximum caseload.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of adjusters per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_active_adjusters(self, page: int, page_size: int) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM adjusters WHERE active=1")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT adjuster_id, name, certification_level, base_territory_id, max_caseload "
            "FROM adjusters WHERE active=1 ORDER BY adjuster_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"adjusters": rows, "total": total, "page": page, "page_size": page_size}

    @tool(
        description="Retrieve all specialties and proficiency scores for a given adjuster.",
        parameters={
            "type": "object",
            "properties": {
                "adjuster_id": {
                    "type": "string",
                    "description": "The adjuster's unique identifier (e.g. 'A0001').",
                },
            },
            "required": ["adjuster_id"],
        },
    )
    def get_adjuster_specialties(self, adjuster_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT claim_type, proficiency_score FROM adjuster_specialties "
            "WHERE adjuster_id=? ORDER BY claim_type",
            (adjuster_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"adjuster_id": adjuster_id, "specialties": rows}

    @tool(
        description="Retrieve settlement history records for a given adjuster, listing average settlement days and total cases handled per claim type.",
        parameters={
            "type": "object",
            "properties": {
                "adjuster_id": {
                    "type": "string",
                    "description": "The adjuster's unique identifier.",
                },
            },
            "required": ["adjuster_id"],
        },
    )
    def get_adjuster_history(self, adjuster_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT claim_type, avg_settlement_days, total_cases_handled "
            "FROM settlement_history WHERE adjuster_id=? ORDER BY claim_type",
            (adjuster_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"adjuster_id": adjuster_id, "records": rows}

    @tool(
        description="Retrieve all travel times FROM a given origin territory to every other territory. Returns a list of destination territory IDs with travel hours.",
        parameters={
            "type": "object",
            "properties": {
                "territory_id": {
                    "type": "string",
                    "description": "Origin territory identifier (e.g. 'T0001').",
                },
            },
            "required": ["territory_id"],
        },
    )
    def get_travel_times_from(self, territory_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT to_territory_id, travel_hours FROM travel_times "
            "WHERE from_territory_id=? ORDER BY to_territory_id",
            (territory_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"territory_id": territory_id, "travel_times": rows}

    @tool(
        description="Retrieve the travel time between two specific territories.",
        parameters={
            "type": "object",
            "properties": {
                "from_territory_id": {
                    "type": "string",
                    "description": "Origin territory identifier.",
                },
                "to_territory_id": {
                    "type": "string",
                    "description": "Destination territory identifier.",
                },
            },
            "required": ["from_territory_id", "to_territory_id"],
        },
    )
    def get_travel_time(self, from_territory_id: str, to_territory_id: str) -> dict:
        if from_territory_id == to_territory_id:
            return {"from_territory_id": from_territory_id,
                    "to_territory_id": to_territory_id,
                    "travel_hours": 0.0}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT travel_hours FROM travel_times "
            "WHERE from_territory_id=? AND to_territory_id=?",
            (from_territory_id, to_territory_id),
        )
        row = cur.fetchone()
        conn.close()
        hours = dict(row)["travel_hours"] if row else None
        return {"from_territory_id": from_territory_id,
                "to_territory_id": to_territory_id,
                "travel_hours": hours}

    # ══════════════════════════════════════════════════════════════════════
    #  SHARED HELPERS
    # ══════════════════════════════════════════════════════════════════════

    CERT_RANK = {"junior": 1, "standard": 2, "senior": 3, "expert": 4}

    @staticmethod
    def _load_workspace_config(workspace: str):
        """Load all fixed + scalable workspace config into a single bundle."""
        with open(os.path.join(workspace, "severity_tiers.json")) as f:
            tiers_raw = json.load(f)["tiers"]
        tier_map = {}
        for t in tiers_raw:
            for s in range(t["min_score"], t["max_score"] + 1):
                tier_map[s] = t["name"]

        cert_reqs = {}
        with open(os.path.join(workspace, "certification_requirements.csv")) as f:
            for row in csv.DictReader(f):
                cert_reqs[row["severity_tier"]] = row["min_certification"]

        with open(os.path.join(workspace, "assignment_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        # supplementary claim data
        supplementary = {}
        for fname in sorted(os.listdir(workspace)):
            if fname.startswith("claims_supplementary_") and fname.endswith(".csv"):
                with open(os.path.join(workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        supplementary[row["claim_id"]] = {
                            "priority_flag": row["priority_flag"],
                            "customer_tier": row["customer_tier"],
                        }

        # caseload
        caseload = {}
        for fname in sorted(os.listdir(workspace)):
            if fname.startswith("caseload_snapshot_") and fname.endswith(".json"):
                with open(os.path.join(workspace, fname)) as f:
                    data = json.load(f)
                    for entry in data["adjusters"]:
                        caseload[entry["adjuster_id"]] = entry["current_active_cases"]

        # territory regions
        territory_regions = {}
        for fname in sorted(os.listdir(workspace)):
            if fname.startswith("territory_zones_") and fname.endswith(".yaml"):
                with open(os.path.join(workspace, fname)) as f:
                    data = yaml.safe_load(f)
                    for t in data["territories"]:
                        territory_regions[t["territory_id"]] = t["region"]

        return {
            "tier_map": tier_map,
            "cert_reqs": cert_reqs,
            "policy": policy,
            "supplementary": supplementary,
            "caseload": caseload,
            "territory_regions": territory_regions,
        }

    @staticmethod
    def _compute_assignments(
        pending_claims: list,
        active_adjusters: list,
        adjuster_specs: dict,
        adjuster_history: dict,
        travel_data: dict,
        caseload: dict,
        territory_regions: dict,
        supplementary: dict,
        policy: dict,
        tier_map: dict,
        cert_reqs: dict,
    ) -> list:
        """
        Deterministic greedy assignment algorithm.

        Args:
            pending_claims: list of claim dicts (claim_id, severity_score, claim_type, territory_id, date_filed, estimated_value)
            active_adjusters: list of adjuster dicts (adjuster_id, name, certification_level, base_territory_id, max_caseload)
            adjuster_specs: {adjuster_id: [{claim_type, proficiency_score}]}
            adjuster_history: {adjuster_id: {claim_type: avg_settlement_days}}
            travel_data: nested dict {from_tid: {to_tid: hours}} OR {claim_tid: {adj_base_tid: hours}}
            caseload: {adjuster_id: current_active_cases}
            territory_regions: {territory_id: region}
            supplementary: {claim_id: {priority_flag, customer_tier}}
            policy, tier_map, cert_reqs: config dicts
        Returns:
            list of assignment dicts
        """
        CERT_RANK = {"junior": 1, "standard": 2, "senior": 3, "expert": 4}
        w = policy["scoring_weights"]
        p = policy["parameters"]
        b = policy["bonuses"]

        w_prof = w["proficiency"]
        w_prox = w["proximity"]
        w_cap  = w["capacity"]
        w_hist = w["history"]
        max_travel   = p["max_travel_hours"]
        max_sett     = p["max_settlement_days"]
        min_prof     = p["min_proficiency"]
        default_sett = p["default_settlement_days"]
        region_bonus = b["same_region_bonus"]
        urg_mult     = b["urgency_multiplier"]
        plat_bonus   = b["platinum_bonus"]

        # sort claims: severity desc, date_filed asc, claim_id asc
        sorted_claims = sorted(
            pending_claims,
            key=lambda c: (-c["severity_score"], c["date_filed"], c["claim_id"]),
        )

        # build lookup structures
        adj_by_id = {a["adjuster_id"]: a for a in active_adjusters}
        spec_lookup = {}
        for aid, specs in adjuster_specs.items():
            for s in specs:
                spec_lookup[(aid, s["claim_type"])] = s["proficiency_score"]

        # track batch caseload additions
        batch_assigned = {a["adjuster_id"]: 0 for a in active_adjusters}

        assignments = []
        for claim in sorted_claims:
            cid = claim["claim_id"]
            sev = claim["severity_score"]
            ctype = claim["claim_type"]
            ctid = claim["territory_id"]
            tier = tier_map.get(sev, "low")
            min_cert = cert_reqs.get(tier, "junior")
            min_cert_rank = CERT_RANK.get(min_cert, 1)

            supp = supplementary.get(cid, {"priority_flag": "normal", "customer_tier": "bronze"})
            pf = supp["priority_flag"]
            ct_tier = supp["customer_tier"]

            claim_region = territory_regions.get(ctid, "")

            best_score = -1e9
            best_aid = None
            best_info = None

            for adj in active_adjusters:
                aid = adj["adjuster_id"]
                cert = adj["certification_level"]
                base_tid = adj["base_territory_id"]
                max_cl = adj["max_caseload"]

                # eligibility
                if CERT_RANK.get(cert, 0) < min_cert_rank:
                    continue
                prof = spec_lookup.get((aid, ctype))
                if prof is None or prof < min_prof:
                    continue

                remaining = max_cl - caseload.get(aid, 0) - batch_assigned.get(aid, 0)
                if remaining <= 0:
                    continue

                # travel time (from adjuster base to claim territory, as the prompt states)
                if ctid == base_tid:
                    travel_h = 0.0
                else:
                    travel_h = None
                    if base_tid in travel_data and ctid in travel_data[base_tid]:
                        travel_h = travel_data[base_tid][ctid]
                    elif ctid in travel_data and base_tid in travel_data[ctid]:
                        travel_h = travel_data[ctid][base_tid]
                    if travel_h is None or travel_h > max_travel:
                        continue

                # history
                hist_days = adjuster_history.get(aid, {}).get(ctype, default_sett)

                # score
                score = (
                    w_prof * (prof / 100.0)
                    + w_prox * max(0.0, 1.0 - travel_h / max_travel)
                    + w_cap  * (remaining / max_cl)
                    + w_hist * (1.0 - min(hist_days, max_sett) / max_sett)
                )

                adj_region = territory_regions.get(base_tid, "")
                if adj_region and adj_region == claim_region:
                    score += region_bonus

                if pf == "urgent" and base_tid == ctid:
                    score *= urg_mult

                if ct_tier == "platinum" and cert in ("senior", "expert"):
                    score += plat_bonus

                score = round(score, 4)

                if score > best_score or (score == best_score and (best_aid is None or aid < best_aid)):
                    best_score = score
                    best_aid = aid
                    best_info = {
                        "claim_id": cid,
                        "adjuster_id": aid,
                        "adjuster_name": adj["name"],
                        "claim_type": ctype,
                        "severity_score": sev,
                        "severity_tier": tier,
                        "assignment_score": score,
                        "priority_flag": pf,
                        "estimated_settlement_days": round(hist_days, 1),
                    }

            if best_aid is not None:
                assignments.append(best_info)
                batch_assigned[best_aid] = batch_assigned.get(best_aid, 0) + 1

        return assignments

    # ══════════════════════════════════════════════════════════════════════
    #  STEP (evaluation)
    # ══════════════════════════════════════════════════════════════════════

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
        cfg = self._load_workspace_config(self.workspace)

        # ── ground-truth from DB ─────────────────────────────────────────
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        pending = [dict(r) for r in conn.execute(
            "SELECT claim_id, severity_score, claim_type, territory_id, date_filed, estimated_value "
            "FROM claims WHERE status='pending' ORDER BY claim_id"
        ).fetchall()]

        active_adjs = [dict(r) for r in conn.execute(
            "SELECT adjuster_id, name, certification_level, base_territory_id, max_caseload "
            "FROM adjusters WHERE active=1 ORDER BY adjuster_id"
        ).fetchall()]

        # specialties
        adj_specs = {}
        for row in conn.execute(
            "SELECT adjuster_id, claim_type, proficiency_score FROM adjuster_specialties"
        ).fetchall():
            r = dict(row)
            adj_specs.setdefault(r["adjuster_id"], []).append(
                {"claim_type": r["claim_type"], "proficiency_score": r["proficiency_score"]}
            )

        # history
        adj_hist = {}
        for row in conn.execute(
            "SELECT adjuster_id, claim_type, avg_settlement_days FROM settlement_history"
        ).fetchall():
            r = dict(row)
            adj_hist.setdefault(r["adjuster_id"], {})[r["claim_type"]] = r["avg_settlement_days"]

        # travel – build nested dict {from: {to: hours}}
        travel_data = {}
        for row in conn.execute(
            "SELECT from_territory_id, to_territory_id, travel_hours FROM travel_times"
        ).fetchall():
            r = dict(row)
            travel_data.setdefault(r["from_territory_id"], {})[r["to_territory_id"]] = r["travel_hours"]

        conn.close()

        gt_assignments = self._compute_assignments(
            pending, active_adjs, adj_specs, adj_hist, travel_data,
            cfg["caseload"], cfg["territory_regions"], cfg["supplementary"],
            cfg["policy"], cfg["tier_map"], cfg["cert_reqs"],
        )
        gt_map = {a["claim_id"]: a for a in gt_assignments}

        # ── parse agent CSV ──────────────────────────────────────────────
        schedule_path = os.path.join(self.workspace, "daily_assignment_schedule.csv")
        criteria = {}

        # Criterion 1: file structure (10 pts)
        expected_cols = [
            "claim_id", "adjuster_id", "adjuster_name", "claim_type",
            "severity_score", "severity_tier", "assignment_score",
            "priority_flag", "estimated_settlement_days",
        ]
        agent_rows = []
        file_ok = False
        try:
            with open(schedule_path) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and set(expected_cols).issubset(set(reader.fieldnames)):
                    file_ok = True
                    for row in reader:
                        agent_rows.append(row)
        except Exception:
            pass

        criteria["file_structure"] = {
            "passed": file_ok,
            "score": 10 if file_ok else 0,
            "max_score": 10,
            "reason": "" if file_ok else "Schedule file missing or has incorrect columns.",
        }

        # Criterion 2: correct number of assignments (10 pts)
        expected_count = len(gt_assignments)
        actual_count = len(agent_rows)
        count_ok = actual_count == expected_count
        criteria["assignment_count"] = {
            "passed": count_ok,
            "score": 10 if count_ok else 0,
            "max_score": 10,
            "reason": "" if count_ok else f"Expected {expected_count} assignments, got {actual_count}.",
        }

        # Criterion 3: correct claim-adjuster pairings (25 pts)
        agent_map = {}
        for r in agent_rows:
            agent_map[r.get("claim_id", "")] = r.get("adjuster_id", "")
        correct_pairs = 0
        for cid, gt_a in gt_map.items():
            if agent_map.get(cid) == gt_a["adjuster_id"]:
                correct_pairs += 1
        pair_frac = correct_pairs / max(len(gt_map), 1)
        pair_score = round(pair_frac * 25)
        criteria["pairings"] = {
            "passed": pair_score == 25,
            "score": pair_score,
            "max_score": 25,
            "reason": "" if pair_score == 25 else f"{correct_pairs}/{len(gt_map)} pairings correct.",
        }

        # Criterion 4: certification compliance (15 pts)
        cert_ok = True
        cert_reason = ""
        CERT_RANK = self.CERT_RANK
        adj_cert_map = {a["adjuster_id"]: a["certification_level"] for a in active_adjs}
        for r in agent_rows:
            aid = r.get("adjuster_id", "")
            tier = r.get("severity_tier", "")
            min_cert = cfg["cert_reqs"].get(tier, "junior")
            actual_cert = adj_cert_map.get(aid, "junior")
            if CERT_RANK.get(actual_cert, 0) < CERT_RANK.get(min_cert, 0):
                cert_ok = False
                cert_reason = f"Adjuster {aid} ({actual_cert}) assigned to {tier}-tier claim."
                break
        criteria["certification_compliance"] = {
            "passed": cert_ok,
            "score": 15 if cert_ok else 0,
            "max_score": 15,
            "reason": cert_reason,
        }

        # Criterion 5: caseload compliance (10 pts)
        load_ok = True
        load_reason = ""
        batch_counts = {}
        for r in agent_rows:
            aid = r.get("adjuster_id", "")
            batch_counts[aid] = batch_counts.get(aid, 0) + 1
        adj_maxcl = {a["adjuster_id"]: a["max_caseload"] for a in active_adjs}
        for aid, cnt in batch_counts.items():
            existing = cfg["caseload"].get(aid, 0)
            if existing + cnt > adj_maxcl.get(aid, 0):
                load_ok = False
                load_reason = f"Adjuster {aid} exceeds max caseload ({existing}+{cnt} > {adj_maxcl.get(aid,0)})."
                break
        criteria["caseload_compliance"] = {
            "passed": load_ok,
            "score": 10 if load_ok else 0,
            "max_score": 10,
            "reason": load_reason,
        }

        # Criterion 6: assignment score accuracy (15 pts)
        score_matches = 0
        score_total = max(len(gt_assignments), 1)
        for r in agent_rows:
            cid = r.get("claim_id", "")
            try:
                agent_score = float(r.get("assignment_score", -999))
            except (ValueError, TypeError):
                continue
            gt_a = gt_map.get(cid)
            if gt_a and abs(agent_score - gt_a["assignment_score"]) < 0.002:
                score_matches += 1
        score_frac = score_matches / score_total
        score_pts = round(score_frac * 15)
        criteria["score_accuracy"] = {
            "passed": score_pts == 15,
            "score": score_pts,
            "max_score": 15,
            "reason": "" if score_pts == 15 else f"{score_matches}/{score_total} scores within tolerance.",
        }

        # Criterion 7: response summary (15 pts)
        summary_pts = 0
        summary_reason = []

        gt_total_assignments = len(gt_assignments)
        gt_assigned_ids = set(a["claim_id"] for a in gt_assignments)
        gt_unassigned = [c["claim_id"] for c in pending if c["claim_id"] not in gt_assigned_ids]
        gt_avg_score = (
            round(sum(a["assignment_score"] for a in gt_assignments) / max(len(gt_assignments), 1), 4)
            if gt_assignments else 0.0
        )

        # check total assignment count in response
        if re.search(r'\b' + str(gt_total_assignments) + r'\b', action):
            summary_pts += 5
        else:
            summary_reason.append(f"Expected total assignments {gt_total_assignments} not found in response.")

        # check average score (4 decimal places)
        avg_str = f"{gt_avg_score:.4f}"
        if avg_str in action:
            summary_pts += 5
        else:
            summary_reason.append(f"Expected average score {avg_str} not found in response.")

        # check unassigned info
        if len(gt_unassigned) == 0:
            if re.search(r'(no\s+(claims?\s+)?(were\s+)?unassigned|0\s+unassigned|all\s+.*assigned)', action, re.IGNORECASE):
                summary_pts += 5
            else:
                summary_reason.append("Expected indication that all claims were assigned.")
        else:
            found_unassigned = all(uid in action for uid in gt_unassigned)
            if found_unassigned:
                summary_pts += 5
            else:
                summary_reason.append(f"Expected unassigned claim IDs {gt_unassigned} in response.")

        criteria["response_summary"] = {
            "passed": summary_pts == 15,
            "score": summary_pts,
            "max_score": 15,
            "reason": "; ".join(summary_reason) if summary_reason else "",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ══════════════════════════════════════════════════════════════════════
    #  VERIFY
    # ══════════════════════════════════════════════════════════════════════

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
        import json as _json
        import yaml as _yaml

        # ── Read workspace config files ──────────────────────────────────
        with open(os.path.join(self.workspace, "severity_tiers.json")) as f:
            tiers_raw = _json.load(f)["tiers"]
        tier_map = {}
        for t in tiers_raw:
            for s in range(t["min_score"], t["max_score"] + 1):
                tier_map[s] = t["name"]

        cert_reqs = {}
        with open(os.path.join(self.workspace, "certification_requirements.csv")) as f:
            for row in _csv.DictReader(f):
                cert_reqs[row["severity_tier"]] = row["min_certification"]

        with open(os.path.join(self.workspace, "assignment_policy.yaml")) as f:
            policy = _yaml.safe_load(f)

        # read rules (not strictly needed for computation, but confirms we use it)
        with open(os.path.join(self.workspace, "assignment_rules.txt")) as f:
            _ = f.read()

        # supplementary
        supplementary = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("claims_supplementary_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in _csv.DictReader(f):
                        supplementary[row["claim_id"]] = {
                            "priority_flag": row["priority_flag"],
                            "customer_tier": row["customer_tier"],
                        }

        # caseload
        caseload = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("caseload_snapshot_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = _json.load(f)
                    for entry in data["adjusters"]:
                        caseload[entry["adjuster_id"]] = entry["current_active_cases"]

        # territory regions
        territory_regions = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("territory_zones_") and fname.endswith(".yaml"):
                with open(os.path.join(self.workspace, fname)) as f:
                    data = _yaml.safe_load(f)
                    for t in data["territories"]:
                        territory_regions[t["territory_id"]] = t["region"]

        # ── Gather data via tools ────────────────────────────────────────

        # pending claims (paginated)
        pending_claims = []
        page = 1
        while True:
            res = self.tools["get_pending_claims"](page=page, page_size=10)
            pending_claims.extend(res["claims"])
            if len(res["claims"]) < 10 or page * 10 >= res["total"]:
                break
            page += 1

        # active adjusters (paginated)
        active_adjusters = []
        page = 1
        while True:
            res = self.tools["list_active_adjusters"](page=page, page_size=10)
            active_adjusters.extend(res["adjusters"])
            if len(res["claims" if "claims" in res else "adjusters"]) < 10 or page * 10 >= res["total"]:
                break
            page += 1

        # specialties per adjuster
        adj_specs = {}
        for adj in active_adjusters:
            res = self.tools["get_adjuster_specialties"](adjuster_id=adj["adjuster_id"])
            adj_specs[adj["adjuster_id"]] = res["specialties"]

        # history per adjuster
        adj_hist = {}
        for adj in active_adjusters:
            res = self.tools["get_adjuster_history"](adjuster_id=adj["adjuster_id"])
            adj_hist[adj["adjuster_id"]] = {
                r["claim_type"]: r["avg_settlement_days"] for r in res["records"]
            }

        # Travel is directed from the adjuster base to the claim territory.
        # Include claim origins for the existing reverse-route fallback.
        claim_territories = (
            {c["territory_id"] for c in pending_claims}
            | {a["base_territory_id"] for a in active_adjusters}
        )
        travel_data = {}
        for tid in sorted(claim_territories):
            res = self.tools["get_travel_times_from"](territory_id=tid)
            travel_data[tid] = {r["to_territory_id"]: r["travel_hours"] for r in res["travel_times"]}

        # ── Compute assignments ──────────────────────────────────────────
        assignments = self._compute_assignments(
            pending_claims, active_adjusters, adj_specs, adj_hist, travel_data,
            caseload, territory_regions, supplementary,
            policy, tier_map, cert_reqs,
        )

        # ── Write deliverable ────────────────────────────────────────────
        schedule_path = os.path.join(self.workspace, "daily_assignment_schedule.csv")
        fieldnames = [
            "claim_id", "adjuster_id", "adjuster_name", "claim_type",
            "severity_score", "severity_tier", "assignment_score",
            "priority_flag", "estimated_settlement_days",
        ]
        with open(schedule_path, "w", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(assignments)

        # ── Build action string ──────────────────────────────────────────
        assigned_ids = set(a["claim_id"] for a in assignments)
        unassigned = [c["claim_id"] for c in pending_claims if c["claim_id"] not in assigned_ids]
        avg_score = (
            round(sum(a["assignment_score"] for a in assignments) / max(len(assignments), 1), 4)
            if assignments else 0.0
        )

        action_parts = [
            f"Total assignments: {len(assignments)}",
            f"Average assignment score: {avg_score:.4f}",
        ]
        if unassigned:
            action_parts.append(f"Unassigned claims ({len(unassigned)}): {', '.join(sorted(unassigned))}")
        else:
            action_parts.append("All claims were assigned; 0 unassigned.")

        action = "\n".join(action_parts)
        return self.step(action)
