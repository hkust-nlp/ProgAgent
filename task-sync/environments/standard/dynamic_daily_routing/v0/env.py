"""
env.py - Task environment for technician schedule optimization.
"""
from typing import Tuple, Dict, List, Any
import sqlite3
import os
import json
import csv
import re
import math
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

    # ======================== TOOLS ========================

    @tool(
        description="List all service zones in the dispatch area.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_zones(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT from_zone FROM traffic_conditions ORDER BY from_zone"
        ).fetchall()
        conn.close()
        zones = sorted(set(r[0] for r in rows))
        return {"zones": zones, "count": len(zones)}

    @tool(
        description=(
            "List technicians with optional status filter. "
            "Returns paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status, e.g. 'available'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1 (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 10, max 50).",
                },
            },
            "required": [],
        },
    )
    def list_technicians(self, status=None, page=1, page_size=10):
        page = max(1, int(page))
        page_size = max(1, min(50, int(page_size)))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM technicians"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        total = conn.execute(
            query.replace("SELECT *", "SELECT COUNT(*)"), params
        ).fetchone()[0]
        query += " ORDER BY tech_id LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        technicians = [
            {
                "tech_id": r["tech_id"],
                "name": r["name"],
                "skill_level": r["skill_level"],
                "van_id": r["van_id"],
                "shift_start": r["shift_start"],
                "shift_end": r["shift_end"],
                "home_zone": r["home_zone"],
                "status": r["status"],
            }
            for r in rows
        ]
        return {"technicians": technicians, "page": page,
                "page_size": page_size, "total": total}

    @tool(
        description=(
            "List pending jobs with optional filters for status, priority tier, "
            "and zone. Returns paginated results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status, e.g. 'pending'.",
                },
                "priority_tier": {
                    "type": "string",
                    "description": "Filter by priority tier, e.g. 'P1'.",
                },
                "zone": {
                    "type": "string",
                    "description": "Filter by zone name.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1 (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 10, max 50).",
                },
            },
            "required": [],
        },
    )
    def list_jobs(self, status=None, priority_tier=None, zone=None,
                  page=1, page_size=10):
        page = max(1, int(page))
        page_size = max(1, min(50, int(page_size)))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if priority_tier:
            clauses.append("priority_tier = ?")
            params.append(priority_tier)
        if zone:
            clauses.append("zone = ?")
            params.append(zone)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM jobs{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM jobs{where} ORDER BY job_id LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        conn.close()
        jobs = [
            {
                "job_id": r["job_id"],
                "customer_name": r["customer_name"],
                "address": r["address"],
                "zone": r["zone"],
                "job_type": r["job_type"],
                "priority_tier": r["priority_tier"],
                "estimated_duration_min": r["estimated_duration_min"],
                "window_start": r["window_start"],
                "window_end": r["window_end"],
                "required_skill_level": r["required_skill_level"],
                "status": r["status"],
            }
            for r in rows
        ]
        return {"jobs": jobs, "page": page, "page_size": page_size,
                "total": total}

    @tool(
        description="Get full details of a single technician by ID.",
        parameters={
            "type": "object",
            "properties": {
                "tech_id": {
                    "type": "string",
                    "description": "Technician identifier, e.g. 'TECH_001'.",
                },
            },
            "required": ["tech_id"],
        },
    )
    def get_technician(self, tech_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM technicians WHERE tech_id = ?", (tech_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Technician '{tech_id}' not found."}
        return dict(row)

    @tool(
        description="Get full details of a single job by ID.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job identifier, e.g. 'JOB_001'.",
                },
            },
            "required": ["job_id"],
        },
    )
    def get_job_details(self, job_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"Job '{job_id}' not found."}
        return dict(row)

    @tool(
        description=(
            "List all parts currently carried in a specific service van, "
            "with quantities."
        ),
        parameters={
            "type": "object",
            "properties": {
                "van_id": {
                    "type": "string",
                    "description": "Van identifier, e.g. 'VAN_001'.",
                },
            },
            "required": ["van_id"],
        },
    )
    def get_van_inventory(self, van_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT pi.part_id, pc.part_name, pi.quantity "
            "FROM parts_inventory pi "
            "JOIN parts_catalog pc ON pi.part_id = pc.part_id "
            "WHERE pi.van_id = ? ORDER BY pi.part_id",
            (van_id,),
        ).fetchall()
        conn.close()
        parts = [{"part_id": r["part_id"], "part_name": r["part_name"],
                   "quantity": r["quantity"]} for r in rows]
        return {"van_id": van_id, "parts": parts}

    @tool(
        description="Get the list of parts required to complete a specific job.",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job identifier, e.g. 'JOB_001'.",
                },
            },
            "required": ["job_id"],
        },
    )
    def get_job_required_parts(self, job_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT jp.part_id, pc.part_name, jp.quantity_needed "
            "FROM job_parts jp "
            "JOIN parts_catalog pc ON jp.part_id = pc.part_id "
            "WHERE jp.job_id = ? ORDER BY jp.part_id",
            (job_id,),
        ).fetchall()
        conn.close()
        parts = [{"part_id": r["part_id"], "part_name": r["part_name"],
                   "quantity_needed": r["quantity_needed"]} for r in rows]
        return {"job_id": job_id, "parts": parts}

    @tool(
        description=(
            "Get real-time traffic information for traveling between two zones, "
            "including base travel time, congestion factor, and road condition."
        ),
        parameters={
            "type": "object",
            "properties": {
                "from_zone": {
                    "type": "string",
                    "description": "Origin zone name.",
                },
                "to_zone": {
                    "type": "string",
                    "description": "Destination zone name.",
                },
            },
            "required": ["from_zone", "to_zone"],
        },
    )
    def get_travel_info(self, from_zone: str, to_zone: str):
        if from_zone == to_zone:
            return {
                "from_zone": from_zone,
                "to_zone": to_zone,
                "base_travel_min": 5.0,
                "congestion_factor": 1.0,
                "road_condition": "good",
                "note": "Intra-zone travel estimate",
            }
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM traffic_conditions "
            "WHERE from_zone = ? AND to_zone = ?",
            (from_zone, to_zone),
        ).fetchone()
        conn.close()
        if not row:
            return {"error": f"No traffic data for {from_zone} -> {to_zone}."}
        return {
            "from_zone": row["from_zone"],
            "to_zone": row["to_zone"],
            "base_travel_min": row["base_travel_min"],
            "congestion_factor": row["congestion_factor"],
            "road_condition": row["road_condition"],
            "last_updated": row["last_updated"],
        }

    # ======================== HELPERS ========================

    @staticmethod
    def _time_to_min(t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m

    @staticmethod
    def _min_to_time(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    def _load_reference_data(self):
        """Load all reference data needed for evaluation."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        techs = {r["tech_id"]: dict(r)
                 for r in conn.execute("SELECT * FROM technicians").fetchall()}
        jobs = {r["job_id"]: dict(r)
                for r in conn.execute(
                    "SELECT * FROM jobs WHERE status='pending'"
                ).fetchall()}

        van_parts = {}
        for r in conn.execute("SELECT * FROM parts_inventory").fetchall():
            van_parts.setdefault(r["van_id"], {})[r["part_id"]] = r["quantity"]

        job_reqs = {}
        for r in conn.execute("SELECT * FROM job_parts").fetchall():
            job_reqs.setdefault(r["job_id"], {})[r["part_id"]] = r["quantity_needed"]

        traffic = {}
        for r in conn.execute("SELECT * FROM traffic_conditions").fetchall():
            traffic[(r["from_zone"], r["to_zone"])] = dict(r)

        conn.close()

        with open(os.path.join(self.workspace, "scheduling_rules.json")) as f:
            sched_rules = json.load(f)
        with open(os.path.join(self.workspace, "part_substitutions.json")) as f:
            substitutions = json.load(f)

        zone_adj = {}
        adj_path = os.path.join(self.workspace, "travel_adjustments.csv")
        with open(adj_path) as f:
            for row in csv.DictReader(f):
                zone_adj[row["zone"]] = float(row["multiplier"])

        site_access = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_details_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rec in json.load(f):
                        site_access[rec["job_id"]] = rec

        tech_zones = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("gps_tracking_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tech_zones[row["tech_id"]] = row["current_zone"]

        return {
            "techs": techs, "jobs": jobs, "van_parts": van_parts,
            "job_reqs": job_reqs, "traffic": traffic, "sched_rules": sched_rules,
            "substitutions": substitutions, "zone_adj": zone_adj,
            "site_access": site_access, "tech_zones": tech_zones,
        }

    def _compute_travel(self, fz, tz, traffic, sched_rules, zone_adj):
        if fz == tz:
            return float(sched_rules.get("same_zone_travel_minutes", 5))
        key = (fz, tz)
        if key not in traffic:
            return 999.0
        seg = traffic[key]
        road_mult = sched_rules["road_condition_multipliers"].get(
            seg["road_condition"], 1.0
        )
        za = zone_adj.get(tz, 1.0)
        return round(
            seg["base_travel_min"] * seg["congestion_factor"] * road_mult * za, 1
        )

    @staticmethod
    def _has_parts(available, required, substitutions):
        for pid, qty in required.items():
            if available.get(pid, 0) >= qty:
                continue
            found = False
            for sub in substitutions.get(pid, []):
                if available.get(sub, 0) >= qty:
                    found = True
                    break
            if not found:
                return False
        return True

    @staticmethod
    def _deduct_parts(available, required, substitutions):
        used = dict(available)
        for pid, qty in required.items():
            if used.get(pid, 0) >= qty:
                used[pid] -= qty
            else:
                for sub in substitutions.get(pid, []):
                    if used.get(sub, 0) >= qty:
                        used[sub] -= qty
                        break
        return used

    # ======================== STEP ========================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.

        Returns a reward based on evaluation results.

        Args:
            action: The agent's final response.

        Returns:
            reward: The reward based on task completion (between 0.0 and 1.0).
            info: Evaluation results.
        """
        ref = self._load_reference_data()
        techs = ref["techs"]
        jobs = ref["jobs"]
        van_parts = ref["van_parts"]
        job_reqs = ref["job_reqs"]
        traffic = ref["traffic"]
        sched_rules = ref["sched_rules"]
        substitutions = ref["substitutions"]
        zone_adj = ref["zone_adj"]
        site_access = ref["site_access"]
        tech_zones = ref["tech_zones"]

        results = {}

        # ---------- Criterion 1: route_file_format (10 pts) ----------
        route_path = os.path.join(self.workspace, "route_plan.csv")
        required_cols = {
            "technician_id", "stop_number", "job_id",
            "estimated_arrival", "estimated_completion", "travel_minutes",
        }
        route_data = []
        file_ok = False
        if os.path.exists(route_path):
            with open(route_path) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames and required_cols.issubset(set(reader.fieldnames)):
                    file_ok = True
                    for row in reader:
                        route_data.append(row)

        results["route_file_format"] = {
            "passed": file_ok, "score": 10 if file_ok else 0, "max_score": 10,
        }
        if not file_ok:
            results["route_file_format"]["reason"] = (
                "File missing or required columns not found"
            )
            # Cannot evaluate further
            for name, ms in [
                ("job_coverage", 20), ("unique_assignment", 10),
                ("skill_compliance", 15), ("parts_compliance", 15),
                ("time_compliance", 15), ("priority_ordering", 15),
            ]:
                results[name] = {
                    "passed": False, "score": 0, "max_score": ms,
                    "reason": "Route file not valid",
                }
            ts = sum(r["score"] for r in results.values())
            ms = sum(r["max_score"] for r in results.values())
            return ts / ms, {"eval_criteria": results,
                             "total_score": ts, "max_score": ms}

        # Parse assignments
        assignments = []
        for row in route_data:
            try:
                assignments.append({
                    "technician_id": row["technician_id"].strip(),
                    "stop_number": int(row["stop_number"]),
                    "job_id": row["job_id"].strip(),
                    "estimated_arrival": row["estimated_arrival"].strip(),
                    "estimated_completion": row["estimated_completion"].strip(),
                    "travel_minutes": float(row["travel_minutes"]),
                })
            except (ValueError, KeyError):
                continue

        assigned_jobs = set(a["job_id"] for a in assignments)

        # ---------- Criterion 2: job_coverage (20 pts) ----------
        total_w, assigned_w = 0, 0
        tier_w = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}
        for jid, j in jobs.items():
            w = tier_w.get(j["priority_tier"], 1)
            total_w += w
            if jid in assigned_jobs:
                assigned_w += w
        cov_frac = assigned_w / total_w if total_w else 0
        c2 = round(cov_frac * 20)
        results["job_coverage"] = {
            "passed": cov_frac >= 0.95, "score": c2, "max_score": 20,
        }
        if cov_frac < 0.95:
            results["job_coverage"]["reason"] = (
                f"Weighted coverage {cov_frac:.1%}"
            )

        # ---------- Criterion 3: unique_assignment (10 pts) ----------
        jcounts = {}
        for a in assignments:
            jcounts[a["job_id"]] = jcounts.get(a["job_id"], 0) + 1
        dups = [j for j, c in jcounts.items() if c > 1]
        c3_ok = len(dups) == 0
        results["unique_assignment"] = {
            "passed": c3_ok, "score": 10 if c3_ok else 0, "max_score": 10,
        }
        if not c3_ok:
            results["unique_assignment"]["reason"] = (
                f"{len(dups)} job(s) assigned multiple times"
            )

        # ---------- Criterion 4: skill_compliance (15 pts) ----------
        sk_ok = sk_tot = 0
        for a in assignments:
            jid, tid = a["job_id"], a["technician_id"]
            if jid in jobs and tid in techs:
                sk_tot += 1
                if techs[tid]["skill_level"] >= jobs[jid]["required_skill_level"]:
                    sk_ok += 1
        sk_frac = sk_ok / sk_tot if sk_tot else 1
        c4 = round(sk_frac * 15)
        results["skill_compliance"] = {
            "passed": sk_frac >= 0.95, "score": c4, "max_score": 15,
        }
        if sk_frac < 0.95:
            results["skill_compliance"]["reason"] = (
                f"{sk_tot - sk_ok} assignment(s) violate skill requirement"
            )

        # ---------- Criterion 5: parts_compliance (15 pts) ----------
        # Sequential check within each tech's route
        tech_routes = {}
        for a in assignments:
            tech_routes.setdefault(a["technician_id"], []).append(a)

        pt_ok = pt_tot = 0
        for tid, route in tech_routes.items():
            if tid not in techs:
                continue
            van_id = techs[tid]["van_id"]
            remaining = dict(van_parts.get(van_id, {}))
            route.sort(key=lambda x: x["stop_number"])
            for a in route:
                jid = a["job_id"]
                if jid not in jobs:
                    continue
                reqs = job_reqs.get(jid, {})
                pt_tot += 1
                if self._has_parts(remaining, reqs, substitutions):
                    pt_ok += 1
                    remaining = self._deduct_parts(remaining, reqs, substitutions)
        pt_frac = pt_ok / pt_tot if pt_tot else 1
        c5 = round(pt_frac * 15)
        results["parts_compliance"] = {
            "passed": pt_frac >= 0.95, "score": c5, "max_score": 15,
        }
        if pt_frac < 0.95:
            results["parts_compliance"]["reason"] = (
                f"{pt_tot - pt_ok} assignment(s) lack required parts"
            )

        # ---------- Criterion 6: time_compliance (15 pts) ----------
        tm_ok = tm_tot = 0
        for a in assignments:
            jid = a["job_id"]
            if jid not in jobs:
                continue
            j = jobs[jid]
            try:
                arr = self._time_to_min(a["estimated_arrival"])
            except Exception:
                continue
            ws = self._time_to_min(j["window_start"])
            we = self._time_to_min(j["window_end"])
            sa = site_access.get(jid)
            if sa:
                acc_s = self._time_to_min(sa["access_start"])
                acc_e = self._time_to_min(sa["access_end"])
            else:
                acc_s, acc_e = 0, 24 * 60
            eff_s = max(ws, acc_s)
            eff_e = min(we, acc_e)
            tm_tot += 1
            if eff_s <= arr <= eff_e:
                tm_ok += 1
        tm_frac = tm_ok / tm_tot if tm_tot else 1
        c6 = round(tm_frac * 15)
        results["time_compliance"] = {
            "passed": tm_frac >= 0.95, "score": c6, "max_score": 15,
        }
        if tm_frac < 0.95:
            results["time_compliance"]["reason"] = (
                f"{tm_tot - tm_ok} arrival(s) outside effective window"
            )

        # ---------- Criterion 7: priority_ordering (15 pts) ----------
        tier_ord = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        ord_ok = ord_tot = 0
        for tid, route in tech_routes.items():
            route.sort(key=lambda x: x["stop_number"])
            for i in range(len(route) - 1):
                j1, j2 = route[i]["job_id"], route[i + 1]["job_id"]
                if j1 in jobs and j2 in jobs:
                    ord_tot += 1
                    t1 = tier_ord.get(jobs[j1]["priority_tier"], 5)
                    t2 = tier_ord.get(jobs[j2]["priority_tier"], 5)
                    if t1 <= t2:
                        ord_ok += 1
        ord_frac = ord_ok / ord_tot if ord_tot else 1.0
        c7 = round(ord_frac * 15)
        results["priority_ordering"] = {
            "passed": ord_frac >= 0.95, "score": c7, "max_score": 15,
        }
        if ord_frac < 0.95:
            results["priority_ordering"]["reason"] = (
                f"{ord_tot - ord_ok} priority ordering violation(s)"
            )

        total_score = sum(r["score"] for r in results.values())
        max_score = sum(r["max_score"] for r in results.values())
        return total_score / max_score, {
            "eval_criteria": results,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ======================== VERIFY ========================

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

        # ---- 1. Read workspace files ----
        tech_gps = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("gps_tracking_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for row in csv.DictReader(f):
                        tech_gps[row["tech_id"]] = {
                            "latitude": float(row["latitude"]),
                            "longitude": float(row["longitude"]),
                            "current_zone": row["current_zone"],
                        }

        site_access = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("site_details_batch_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    for rec in json.load(f):
                        site_access[rec["job_id"]] = rec

        with open(os.path.join(self.workspace, "priority_config.yaml")) as f:
            _priority_config = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "scheduling_rules.json")) as f:
            sched_rules = json.load(f)

        with open(os.path.join(self.workspace, "part_substitutions.json")) as f:
            substitutions = json.load(f)

        zone_adj = {}
        with open(os.path.join(self.workspace, "travel_adjustments.csv")) as f:
            for row in csv.DictReader(f):
                zone_adj[row["zone"]] = float(row["multiplier"])

        # ---- 2. Gather data via tools ----
        all_techs = []
        page = 1
        while True:
            res = self.tools["list_technicians"](page=page, page_size=10)
            all_techs.extend(res["technicians"])
            if len(res["technicians"]) < 10 or page * 10 >= res["total"]:
                break
            page += 1

        all_jobs = []
        page = 1
        while True:
            res = self.tools["list_jobs"](status="pending", page=page, page_size=10)
            all_jobs.extend(res["jobs"])
            if len(res["jobs"]) < 10 or page * 10 >= res["total"]:
                break
            page += 1

        # Van inventories
        tech_parts = {}
        for t in all_techs:
            inv = self.tools["get_van_inventory"](van_id=t["van_id"])
            tech_parts[t["tech_id"]] = {
                p["part_id"]: p["quantity"] for p in inv["parts"]
            }

        # Job required parts
        j_reqs = {}
        for j in all_jobs:
            rp = self.tools["get_job_required_parts"](job_id=j["job_id"])
            j_reqs[j["job_id"]] = {
                p["part_id"]: p["quantity_needed"] for p in rp["parts"]
            }

        # Also call list_zones to add tool calls
        _zones_result = self.tools["list_zones"]()

        # ---- 3. Travel time helper (via tools, cached) ----
        travel_cache = {}

        def get_travel(fz, tz):
            key = (fz, tz)
            if key not in travel_cache:
                res = self.tools["get_travel_info"](from_zone=fz, to_zone=tz)
                if "error" in res:
                    travel_cache[key] = 999.0
                else:
                    road_mult = sched_rules["road_condition_multipliers"].get(
                        res["road_condition"], 1.0
                    )
                    za = zone_adj.get(tz, 1.0)
                    travel_cache[key] = round(
                        res["base_travel_min"] * res["congestion_factor"]
                        * road_mult * za,
                        1,
                    )
            return travel_cache[key]

        max_jobs = sched_rules.get("max_jobs_per_technician", 6)

        # ---- 4. Greedy scheduling ----
        tier_ord = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        sorted_jobs = sorted(
            all_jobs,
            key=lambda j: (tier_ord.get(j["priority_tier"], 5), j["window_end"]),
        )

        # Initialize technician state
        tech_state = {}
        for t in all_techs:
            tid = t["tech_id"]
            gps = tech_gps.get(tid)
            czone = gps["current_zone"] if gps else t["home_zone"]
            tech_state[tid] = {
                "current_zone": czone,
                "current_time": self._time_to_min(t["shift_start"]),
                "shift_end": self._time_to_min(t["shift_end"]),
                "skill_level": t["skill_level"],
                "van_id": t["van_id"],
                "available_parts": dict(tech_parts.get(tid, {})),
                "route": [],
            }

        assigned_set = set()
        for job in sorted_jobs:
            jid = job["job_id"]
            j_zone = job["zone"]
            j_dur = job["estimated_duration_min"]
            j_skill = job["required_skill_level"]
            j_ws = self._time_to_min(job["window_start"])
            j_we = self._time_to_min(job["window_end"])

            sa = site_access.get(jid)
            if sa:
                acc_s = self._time_to_min(sa["access_start"])
                acc_e = self._time_to_min(sa["access_end"])
            else:
                acc_s, acc_e = 0, 24 * 60

            eff_s = max(j_ws, acc_s)
            eff_e = min(j_we, acc_e)
            if eff_e - eff_s < j_dur:
                continue  # infeasible

            best_tech = None
            best_travel = float("inf")
            best_arrival = 0

            for tid, st in tech_state.items():
                if st["skill_level"] < j_skill:
                    continue
                if len(st["route"]) >= max_jobs:
                    continue
                if not self._has_parts(
                    st["available_parts"], j_reqs.get(jid, {}), substitutions
                ):
                    continue

                travel = get_travel(st["current_zone"], j_zone)
                raw_arr = st["current_time"] + travel
                arrival = max(raw_arr, eff_s)
                completion = arrival + j_dur

                if arrival > eff_e:
                    continue
                if completion > st["shift_end"]:
                    continue

                if travel < best_travel or (
                    travel == best_travel and
                    (best_tech is None or tid < best_tech)
                ):
                    best_travel = travel
                    best_tech = tid
                    best_arrival = arrival

            if best_tech is not None:
                st = tech_state[best_tech]
                completion = best_arrival + j_dur
                st["route"].append({
                    "job_id": jid,
                    "stop_number": len(st["route"]) + 1,
                    "estimated_arrival": self._min_to_time(int(best_arrival)),
                    "estimated_completion": self._min_to_time(int(completion)),
                    "travel_minutes": round(best_travel, 1),
                })
                st["current_zone"] = j_zone
                st["current_time"] = completion
                st["available_parts"] = self._deduct_parts(
                    st["available_parts"], j_reqs.get(jid, {}), substitutions
                )
                assigned_set.add(jid)

        # ---- 5. Write route_plan.csv ----
        route_rows = []
        for tid, st in sorted(tech_state.items()):
            for stop in st["route"]:
                route_rows.append({
                    "technician_id": tid,
                    "stop_number": stop["stop_number"],
                    "job_id": stop["job_id"],
                    "estimated_arrival": stop["estimated_arrival"],
                    "estimated_completion": stop["estimated_completion"],
                    "travel_minutes": stop["travel_minutes"],
                })

        route_path = os.path.join(self.workspace, "route_plan.csv")
        with open(route_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "technician_id", "stop_number", "job_id",
                "estimated_arrival", "estimated_completion", "travel_minutes",
            ])
            writer.writeheader()
            writer.writerows(route_rows)

        # ---- 6. Build action string ----
        total_travel = round(sum(r["travel_minutes"] for r in route_rows), 1)
        num_scheduled = len(assigned_set)
        num_total = len(all_jobs)

        action_lines = [
            f"Total Travel Time: {total_travel} minutes",
            f"Jobs Scheduled: {num_scheduled} out of {num_total}",
        ]
        unassigned = sorted(
            j["job_id"] for j in all_jobs if j["job_id"] not in assigned_set
        )
        if unassigned:
            action_lines.append(f"Unassigned Jobs: {', '.join(unassigned)}")
        action = "\n".join(action_lines)

        return self.step(action)
