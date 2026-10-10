"""
Crude Oil Blending Optimization - Task Environment

Provides tools for querying crude-oil data and evaluates the agent's
daily blending schedule against a deterministic ground-truth solution.
"""
import csv
import glob
import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple

import yaml


# ---------- decorator (keep unchanged) ----------
def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ===========================================================================
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

    # -----------------------------------------------------------------------
    #  TOOL METHODS
    # -----------------------------------------------------------------------

    @tool(
        description=(
            "Returns a paginated list of crude-oil batch summaries. "
            "Each entry contains batch_id, crude_name, supplier, and "
            "origin_region. Use get_batch_details for full properties."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
            },
            "required": [],
        },
    )
    def list_crude_batches(self, page: int = 1, page_size: int = 20):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT batch_id, crude_name, supplier, origin_region "
            "FROM crude_batches ORDER BY batch_id LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        total = conn.execute("SELECT count(*) FROM crude_batches").fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "data": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Returns full properties for a single crude-oil batch: "
            "api_gravity, sulfur_pct, pour_point_f, cost_per_bbl, etc."
        ),
        parameters={
            "type": "object",
            "properties": {
                "batch_id": {
                    "type": "integer",
                    "description": "The batch identifier.",
                },
            },
            "required": ["batch_id"],
        },
    )
    def get_batch_details(self, batch_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM crude_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"batch_id {batch_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Returns a paginated list of storage tanks. "
            "Optionally filter by status ('available', 'maintenance', "
            "'reserved')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
                "status_filter": {
                    "type": "string",
                    "description": (
                        "If provided, return only tanks with this status."
                    ),
                },
            },
            "required": [],
        },
    )
    def list_storage_tanks(
        self, page: int = 1, page_size: int = 20, status_filter: str = ""
    ):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM storage_tanks WHERE status = ? "
                "ORDER BY tank_id LIMIT ? OFFSET ?",
                (status_filter, page_size, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT count(*) FROM storage_tanks WHERE status = ?",
                (status_filter,),
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM storage_tanks ORDER BY tank_id "
                "LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT count(*) FROM storage_tanks"
            ).fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "data": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Returns a paginated list of pipeline deliveries. "
            "When include_prior is true, returns deliveries scheduled "
            "on or before the given date; otherwise only that exact date. "
            "Each record includes delivery_id, batch_id, pipeline_name, "
            "scheduled_date, volume_bbl, eta_hour, delivery_status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
                "include_prior": {
                    "type": "boolean",
                    "description": (
                        "If true, include deliveries scheduled before "
                        "target_date as well (default false)."
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "1-based page number (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
            },
            "required": ["target_date"],
        },
    )
    def get_deliveries(
        self,
        target_date: str,
        include_prior: bool = False,
        page: int = 1,
        page_size: int = 20,
    ):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if include_prior:
            cond = "scheduled_date <= ?"
        else:
            cond = "scheduled_date = ?"
        rows = conn.execute(
            f"SELECT * FROM pipeline_deliveries WHERE {cond} "
            "ORDER BY delivery_id LIMIT ? OFFSET ?",
            (target_date, page_size, offset),
        ).fetchall()
        total = conn.execute(
            f"SELECT count(*) FROM pipeline_deliveries WHERE {cond}",
            (target_date,),
        ).fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "data": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Returns a paginated list of product demands for the given "
            "target date. Each record includes demand_id, product_type, "
            "customer_name, volume_bbl, price_per_bbl, quality_tier."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format.",
                },
                "page": {
                    "type": "integer",
                    "description": "1-based page number (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
            },
            "required": ["target_date"],
        },
    )
    def get_demands(
        self, target_date: str, page: int = 1, page_size: int = 20
    ):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM product_demands WHERE target_date = ? "
            "ORDER BY demand_id LIMIT ? OFFSET ?",
            (target_date, page_size, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT count(*) FROM product_demands WHERE target_date = ?",
            (target_date,),
        ).fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "data": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Returns a paginated list of blending units. Optionally "
            "filter by product_type and/or status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number (default 1).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (default 20, max 50).",
                },
                "product_type": {
                    "type": "string",
                    "description": "Filter by product type.",
                },
                "status_filter": {
                    "type": "string",
                    "description": "Filter by unit status.",
                },
            },
            "required": [],
        },
    )
    def list_blending_units(
        self,
        page: int = 1,
        page_size: int = 20,
        product_type: str = "",
        status_filter: str = "",
    ):
        page_size = min(page_size, 50)
        offset = (max(page, 1) - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conds, params = [], []
        if product_type:
            conds.append("product_type = ?")
            params.append(product_type)
        if status_filter:
            conds.append("status = ?")
            params.append(status_filter)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = conn.execute(
            f"SELECT * FROM blending_units {where} "
            "ORDER BY unit_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        total = conn.execute(
            f"SELECT count(*) FROM blending_units {where}", params
        ).fetchone()[0]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "data": [dict(r) for r in rows],
        }

    @tool(
        description="Returns full details for a single blending unit.",
        parameters={
            "type": "object",
            "properties": {
                "unit_id": {
                    "type": "integer",
                    "description": "The unit identifier.",
                },
            },
            "required": ["unit_id"],
        },
    )
    def get_unit_details(self, unit_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM blending_units WHERE unit_id = ?", (unit_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"unit_id {unit_id} not found"}
        return dict(row)

    # -----------------------------------------------------------------------
    #  INTERNAL HELPERS (not tools)
    # -----------------------------------------------------------------------

    def _load_lab_data(self) -> Dict[int, Dict[str, float]]:
        """Load all crude_lab_*.csv files into {batch_id: {prop: val}}."""
        lab: Dict[int, Dict[str, float]] = {}
        pattern = os.path.join(self.workspace, "crude_lab_*.csv")
        for path in sorted(glob.glob(pattern)):
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bid = int(row["batch_id"])
                    lab[bid] = {
                        "mercaptan_ppm": float(row["mercaptan_ppm"]),
                        "salt_ptb": float(row["salt_ptb"]),
                        "nickel_ppm": float(row["nickel_ppm"]),
                        "vanadium_ppm": float(row["vanadium_ppm"]),
                        "hydrogen_sulfide_ppm": float(
                            row["hydrogen_sulfide_ppm"]
                        ),
                    }
        return lab

    def _load_quality_specs(self) -> dict:
        path = os.path.join(self.workspace, "quality_specs.yaml")
        with open(path) as f:
            return yaml.safe_load(f)

    def _load_blending_rules(self) -> dict:
        path = os.path.join(self.workspace, "blending_rules.json")
        with open(path) as f:
            return json.load(f)

    def _batch_qualifies(
        self,
        batch_db: dict,
        lab: dict | None,
        specs: dict,
    ) -> bool:
        """Check if a single batch meets ALL specs for a product/tier."""
        for key, limit in specs.items():
            if key.startswith("min_"):
                prop = key[4:]
                val = batch_db.get(prop) if prop in batch_db else (
                    lab.get(prop) if lab else None
                )
                if val is None:
                    return False
                if val < limit:
                    return False
            elif key.startswith("max_"):
                prop = key[4:]
                val = batch_db.get(prop) if prop in batch_db else (
                    lab.get(prop) if lab else None
                )
                if val is None:
                    return False
                if val > limit:
                    return False
        return True

    def _compute_ground_truth(self):
        """Compute the deterministic optimal schedule using DB + workspace."""
        TARGET = "2026-04-21"

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # 1. Demands for target date, sorted by price desc, demand_id asc
        demands = [
            dict(r) for r in conn.execute(
                "SELECT * FROM product_demands WHERE target_date = ? "
                "ORDER BY price_per_bbl DESC, demand_id ASC",
                (TARGET,),
            ).fetchall()
        ]

        # 2. Available tanks
        tanks = [
            dict(r) for r in conn.execute(
                "SELECT * FROM storage_tanks WHERE status = 'available' "
                "ORDER BY tank_id"
            ).fetchall()
        ]

        # 3. Confirmed deliveries on or before target date
        deliveries = [
            dict(r) for r in conn.execute(
                "SELECT * FROM pipeline_deliveries "
                "WHERE delivery_status = 'confirmed' "
                "AND scheduled_date <= ? ORDER BY delivery_id",
                (TARGET,),
            ).fetchall()
        ]

        # 4. All batch details
        all_batches = {
            r["batch_id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM crude_batches ORDER BY batch_id"
            ).fetchall()
        }

        # 5. All blending units (online), keyed by product_type
        units_by_product: Dict[str, list] = {}
        for r in conn.execute(
            "SELECT * FROM blending_units WHERE status = 'online' "
            "ORDER BY unit_id"
        ).fetchall():
            d = dict(r)
            units_by_product.setdefault(d["product_type"], []).append(d)

        conn.close()

        # 6. Workspace config
        lab_data = self._load_lab_data()
        q_specs = self._load_quality_specs()
        rules = self._load_blending_rules()
        loss_pct = rules["processing_loss_pct"]

        # 7. Build crude availability pool
        #    {batch_id: [(source_type, source_id, available_volume)]}
        avail: Dict[int, list] = {}
        for t in tanks:
            bid = t["batch_id"]
            avail.setdefault(bid, []).append(
                ("tank", t["tank_id"], t["current_volume_bbl"])
            )
        for d in deliveries:
            bid = d["batch_id"]
            avail.setdefault(bid, []).append(
                ("delivery", d["delivery_id"], d["volume_bbl"])
            )

        # Mutable remaining volumes  {(source_type, source_id): remaining}
        remaining: Dict[tuple, float] = {}
        for bid, sources in avail.items():
            for stype, sid, vol in sources:
                remaining[(stype, sid)] = vol

        used_units: set = set()
        schedule: list = []
        entry_id = 0

        for dem in demands:
            ptype = dem["product_type"]
            tier = dem["quality_tier"]
            specs = q_specs.get(ptype, {}).get(tier, {})
            if not specs:
                continue

            # Find first available unit
            unit = None
            for u in units_by_product.get(ptype, []):
                if u["unit_id"] not in used_units:
                    unit = u
                    break
            if unit is None:
                continue

            # Filter qualifying batches
            qualifying = []
            for bid, sources in avail.items():
                # Has remaining volume?
                total_rem = sum(
                    remaining.get((s[0], s[1]), 0) for s in sources
                )
                if total_rem <= 0:
                    continue
                bdata = all_batches.get(bid)
                if bdata is None:
                    continue
                ldata = lab_data.get(bid)
                if self._batch_qualifies(bdata, ldata, specs):
                    qualifying.append(
                        (bdata["cost_per_bbl"], bid, total_rem)
                    )

            if not qualifying:
                continue

            # Sort: cost asc, batch_id asc
            qualifying.sort(key=lambda x: (x[0], x[1]))

            # Volume calculation
            crude_needed = dem["volume_bbl"] / (1 - loss_pct / 100.0)
            crude_needed = min(crude_needed, unit["max_throughput_bbl"])

            components: Dict[int, float] = {}  # batch_id -> volume used
            total_allocated = 0.0
            total_cost_weighted = 0.0

            for _cost, bid, _rem in qualifying:
                if total_allocated >= crude_needed:
                    break
                # Draw from sources for this batch
                for stype, sid, _orig_vol in avail[bid]:
                    key = (stype, sid)
                    rem = remaining.get(key, 0)
                    if rem <= 0:
                        continue
                    take = min(rem, crude_needed - total_allocated)
                    if take <= 0:
                        break
                    remaining[key] -= take
                    components[bid] = components.get(bid, 0) + take
                    total_allocated += take
                    total_cost_weighted += take * all_batches[bid][
                        "cost_per_bbl"
                    ]
                    if total_allocated >= crude_needed:
                        break

            if total_allocated <= 0:
                continue

            product_vol = total_allocated * (1 - loss_pct / 100.0)
            w_cost = total_cost_weighted / total_allocated
            net_rev = (
                product_vol * dem["price_per_bbl"]
                - total_allocated * w_cost
                - total_allocated * unit["operating_cost_per_bbl"]
            )

            # Compute blend properties for quality report
            blend_props: Dict[str, float] = {}
            for prop in [
                "api_gravity", "sulfur_pct", "pour_point_f",
            ]:
                wsum = sum(
                    all_batches[bid][prop] * vol
                    for bid, vol in components.items()
                )
                blend_props[prop] = wsum / total_allocated
            for prop in [
                "mercaptan_ppm", "salt_ptb", "nickel_ppm", "vanadium_ppm",
            ]:
                wsum = 0.0
                for bid, vol in components.items():
                    ldata = lab_data.get(bid, {})
                    wsum += ldata.get(prop, 0.0) * vol
                blend_props[prop] = wsum / total_allocated

            entry_id += 1
            used_units.add(unit["unit_id"])
            schedule.append({
                "entry_id": entry_id,
                "demand_id": dem["demand_id"],
                "unit_id": unit["unit_id"],
                "product_type": ptype,
                "quality_tier": tier,
                "crude_components": {
                    str(bid): round(vol, 2)
                    for bid, vol in components.items()
                },
                "total_crude_volume_bbl": round(total_allocated, 2),
                "product_volume_bbl": round(product_vol, 2),
                "net_revenue_usd": round(net_rev, 2),
                "blend_properties": {
                    k: round(v, 4) for k, v in blend_props.items()
                },
                "spec_limits": specs,
            })

        return schedule

    # -----------------------------------------------------------------------
    #  STEP — evaluate the agent's submission
    # -----------------------------------------------------------------------

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
        criteria: Dict[str, Dict[str, Any]] = {}
        gt = self._compute_ground_truth()
        gt_demand_ids = {e["demand_id"] for e in gt}
        gt_revenue = sum(e["net_revenue_usd"] for e in gt)

        # --- Criterion 1: schedule CSV exists + correct columns (10 pts) ---
        sched_path = os.path.join(self.workspace, "daily_blend_schedule.csv")
        required_cols = [
            "entry_id", "demand_id", "unit_id", "product_type",
            "quality_tier", "crude_components", "total_crude_volume_bbl",
            "product_volume_bbl", "net_revenue_usd",
        ]
        sched_rows = []
        if os.path.isfile(sched_path):
            with open(sched_path, newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                sched_rows = list(reader)
            missing = [c for c in required_cols if c not in headers]
            if not missing:
                criteria["schedule_format"] = {
                    "passed": True, "score": 10, "max_score": 10,
                }
            else:
                criteria["schedule_format"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Missing columns: {missing}",
                }
        else:
            criteria["schedule_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "daily_blend_schedule.csv not found",
            }

        # --- Criterion 2: quality JSON exists + structure (10 pts) ---
        qv_path = os.path.join(
            self.workspace, "quality_verification.json"
        )
        qv_data = []
        if os.path.isfile(qv_path):
            try:
                with open(qv_path) as f:
                    qv_data = json.load(f)
                if isinstance(qv_data, list) and len(qv_data) > 0:
                    sample = qv_data[0]
                    needed = {"entry_id", "blend_properties", "all_specs_met"}
                    if needed.issubset(sample.keys()):
                        criteria["quality_report_format"] = {
                            "passed": True, "score": 10, "max_score": 10,
                        }
                    else:
                        criteria["quality_report_format"] = {
                            "passed": False, "score": 5, "max_score": 10,
                            "reason": "quality JSON missing expected keys",
                        }
                else:
                    criteria["quality_report_format"] = {
                        "passed": False, "score": 3, "max_score": 10,
                        "reason": "quality JSON is not a non-empty list",
                    }
            except Exception as e:
                criteria["quality_report_format"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": f"Failed to parse quality JSON: {e}",
                }
        else:
            criteria["quality_report_format"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "quality_verification.json not found",
            }

        # --- Criterion 3: demand coverage matches ground truth (20 pts) ---
        agent_demand_ids = set()
        for row in sched_rows:
            try:
                agent_demand_ids.add(int(row["demand_id"]))
            except (KeyError, ValueError):
                pass
        if gt_demand_ids:
            correct = agent_demand_ids & gt_demand_ids
            coverage = len(correct) / len(gt_demand_ids)
            # Also penalise false positives lightly
            false_pos = agent_demand_ids - gt_demand_ids
            penalty = min(len(false_pos) * 0.02, 0.2)
            score_frac = max(coverage - penalty, 0)
            pts = round(score_frac * 20, 1)
            criteria["demand_coverage"] = {
                "passed": pts >= 18,
                "score": pts,
                "max_score": 20,
                "reason": (
                    f"matched {len(correct)}/{len(gt_demand_ids)} demands, "
                    f"{len(false_pos)} false positives"
                ),
            }
        else:
            criteria["demand_coverage"] = {
                "passed": True, "score": 20, "max_score": 20,
            }

        # --- Criterion 4: quality compliance (20 pts) ---
        q_specs = self._load_quality_specs()
        lab_data = self._load_lab_data()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        all_batches = {
            r["batch_id"]: dict(r)
            for r in conn.execute("SELECT * FROM crude_batches").fetchall()
        }
        conn.close()
        rules = self._load_blending_rules()
        loss_pct = rules["processing_loss_pct"]

        compliant_count = 0
        total_entries = max(len(sched_rows), 1)
        for row in sched_rows:
            try:
                ptype = row["product_type"]
                tier = row["quality_tier"]
                comps_raw = row.get("crude_components", "{}")
                comps = json.loads(comps_raw)
                specs = q_specs.get(ptype, {}).get(tier, {})
                if not specs or not comps:
                    continue
                total_vol = sum(float(v) for v in comps.values())
                if total_vol <= 0:
                    continue
                blend = {}
                for prop in [
                    "api_gravity", "sulfur_pct", "pour_point_f",
                    "mercaptan_ppm", "salt_ptb", "nickel_ppm",
                    "vanadium_ppm",
                ]:
                    wsum = 0.0
                    for bid_s, vol_s in comps.items():
                        bid = int(bid_s)
                        vol = float(vol_s)
                        bdata = all_batches.get(bid, {})
                        ldata = lab_data.get(bid, {})
                        val = bdata.get(prop, ldata.get(prop, 0.0))
                        wsum += val * vol
                    blend[prop] = wsum / total_vol
                ok = True
                for key, limit in specs.items():
                    prop = key[4:]
                    if key.startswith("min_") and blend.get(prop, 0) < limit:
                        ok = False
                    elif key.startswith("max_") and blend.get(prop, 0) > limit:
                        ok = False
                if ok:
                    compliant_count += 1
            except Exception:
                pass
        comp_frac = compliant_count / total_entries if sched_rows else 0
        pts4 = round(comp_frac * 20, 1)
        criteria["quality_compliance"] = {
            "passed": pts4 >= 18,
            "score": pts4,
            "max_score": 20,
            "reason": f"{compliant_count}/{len(sched_rows)} entries compliant",
        }

        # --- Criterion 5: volume constraints (15 pts) ---
        # Check: total crude drawn per source <= original available volume
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        tank_vols = {
            r["tank_id"]: r["current_volume_bbl"]
            for r in conn.execute(
                "SELECT tank_id, current_volume_bbl FROM storage_tanks "
                "WHERE status = 'available'"
            ).fetchall()
        }
        deliv_vols = {
            r["delivery_id"]: r["volume_bbl"]
            for r in conn.execute(
                "SELECT delivery_id, volume_bbl FROM pipeline_deliveries "
                "WHERE delivery_status = 'confirmed' "
                "AND scheduled_date <= '2026-04-21'"
            ).fetchall()
        }
        unit_caps = {
            r["unit_id"]: r["max_throughput_bbl"]
            for r in conn.execute(
                "SELECT unit_id, max_throughput_bbl FROM blending_units "
                "WHERE status = 'online'"
            ).fetchall()
        }
        # Map batch_id -> available sources with volumes
        batch_sources: Dict[int, Dict[str, float]] = {}
        for r in conn.execute(
            "SELECT tank_id, batch_id, current_volume_bbl "
            "FROM storage_tanks WHERE status = 'available'"
        ).fetchall():
            batch_sources.setdefault(r["batch_id"], {})
            batch_sources[r["batch_id"]][f"tank_{r['tank_id']}"] = r[
                "current_volume_bbl"
            ]
        for r in conn.execute(
            "SELECT delivery_id, batch_id, volume_bbl "
            "FROM pipeline_deliveries "
            "WHERE delivery_status = 'confirmed' AND scheduled_date <= '2026-04-21'"
        ).fetchall():
            batch_sources.setdefault(r["batch_id"], {})
            batch_sources[r["batch_id"]][f"deliv_{r['delivery_id']}"] = r[
                "volume_bbl"
            ]
        conn.close()

        # Aggregate how much crude of each batch the agent used
        batch_used: Dict[int, float] = {}
        unit_used: Dict[int, float] = {}
        for row in sched_rows:
            try:
                comps = json.loads(row.get("crude_components", "{}"))
                uid = int(row["unit_id"])
                entry_crude = 0.0
                for bid_s, vol_s in comps.items():
                    bid = int(bid_s)
                    vol = float(vol_s)
                    batch_used[bid] = batch_used.get(bid, 0) + vol
                    entry_crude += vol
                unit_used[uid] = unit_used.get(uid, 0) + entry_crude
            except Exception:
                pass

        vol_violations = 0
        vol_checks = 0
        for bid, used in batch_used.items():
            avail_total = sum(batch_sources.get(bid, {}).values())
            vol_checks += 1
            if used > avail_total * 1.01:  # 1% tolerance
                vol_violations += 1
        for uid, used in unit_used.items():
            cap = unit_caps.get(uid, 0)
            vol_checks += 1
            if cap > 0 and used > cap * 1.01:
                vol_violations += 1
        if vol_checks > 0:
            ok_frac = 1 - vol_violations / vol_checks
        else:
            ok_frac = 1.0 if not sched_rows else 0.0
        pts5 = round(ok_frac * 15, 1)
        criteria["volume_constraints"] = {
            "passed": vol_violations == 0,
            "score": pts5,
            "max_score": 15,
            "reason": f"{vol_violations} violations out of {vol_checks} checks",
        }

        # --- Criterion 6: revenue accuracy (15 pts) ---
        import re
        revenue_match = re.search(
            r"Total Net Revenue[:\s]*\$?([\d,]+\.?\d*)", action, re.IGNORECASE
        )
        if revenue_match and gt_revenue != 0:
            reported = float(revenue_match.group(1).replace(",", ""))
            pct_err = abs(reported - gt_revenue) / abs(gt_revenue)
            if pct_err <= 0.01:
                pts6 = 15
            elif pct_err <= 0.05:
                pts6 = 10
            elif pct_err <= 0.10:
                pts6 = 5
            else:
                pts6 = 0
            criteria["revenue_accuracy"] = {
                "passed": pts6 == 15,
                "score": pts6,
                "max_score": 15,
                "reason": (
                    f"reported={reported:.2f}, "
                    f"expected={gt_revenue:.2f}, "
                    f"error={pct_err*100:.1f}%"
                ),
            }
        elif gt_revenue == 0:
            criteria["revenue_accuracy"] = {
                "passed": True, "score": 15, "max_score": 15,
            }
        else:
            criteria["revenue_accuracy"] = {
                "passed": False, "score": 0, "max_score": 15,
                "reason": "Could not find 'Total Net Revenue' in response",
            }

        # --- Criterion 7: response summary (10 pts) ---
        pts7 = 0
        checks = [
            (r"(?i)demands?\s+fulfilled", 3),
            (r"(?i)product\s+volume", 3),
            (r"(?i)crude\s+processed", 4),
        ]
        reasons = []
        for pat, pts_each in checks:
            if re.search(pat, action):
                pts7 += pts_each
            else:
                reasons.append(f"missing '{pat}'")
        criteria["response_summary"] = {
            "passed": pts7 == 10,
            "score": pts7,
            "max_score": 10,
            "reason": "; ".join(reasons) if reasons else "",
        }

        # --- aggregate ---
        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = total_score / max_score if max_score > 0 else 0.0

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # -----------------------------------------------------------------------
    #  VERIFY — solve with tools + workspace only
    # -----------------------------------------------------------------------

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
        TARGET = "2026-04-21"

        # ------ 1. Read workspace config ------
        with open(os.path.join(self.workspace, "quality_specs.yaml")) as f:
            q_specs = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "blending_rules.json")) as f:
            rules = json.load(f)
        loss_pct = rules["processing_loss_pct"]

        # Lab data from CSVs
        lab_data: Dict[int, Dict[str, float]] = {}
        for fpath in sorted(glob.glob(
            os.path.join(self.workspace, "crude_lab_*.csv")
        )):
            with open(fpath, newline="") as f:
                for row in csv.DictReader(f):
                    bid = int(row["batch_id"])
                    lab_data[bid] = {
                        k: float(row[k])
                        for k in [
                            "mercaptan_ppm", "salt_ptb",
                            "nickel_ppm", "vanadium_ppm",
                            "hydrogen_sulfide_ppm",
                        ]
                    }

        # ------ 2. Gather demands via tool ------
        demands = []
        page = 1
        while True:
            res = self.tools["get_demands"](
                target_date=TARGET, page=page, page_size=50
            )
            demands.extend(res["data"])
            if page * 50 >= res["total"]:
                break
            page += 1
        demands.sort(
            key=lambda d: (-d["price_per_bbl"], d["demand_id"])
        )

        # ------ 3. Gather available tanks via tool ------
        tanks = []
        page = 1
        while True:
            res = self.tools["list_storage_tanks"](
                page=page, page_size=50, status_filter="available"
            )
            tanks.extend(res["data"])
            if page * 50 >= res["total"]:
                break
            page += 1

        # ------ 4. Gather confirmed deliveries on/before target ------
        deliveries = []
        page = 1
        while True:
            res = self.tools["get_deliveries"](
                target_date=TARGET, include_prior=True,
                page=page, page_size=50,
            )
            deliveries.extend(res["data"])
            if page * 50 >= res["total"]:
                break
            page += 1
        # Keep only confirmed
        deliveries = [
            d for d in deliveries if d["delivery_status"] == "confirmed"
        ]

        # ------ 5. Collect unique batch IDs and fetch details ------
        batch_ids = set()
        for t in tanks:
            batch_ids.add(t["batch_id"])
        for d in deliveries:
            batch_ids.add(d["batch_id"])

        batch_details: Dict[int, dict] = {}
        for bid in sorted(batch_ids):
            batch_details[bid] = self.tools["get_batch_details"](
                batch_id=bid
            )

        # ------ 6. Build availability pool ------
        avail: Dict[int, list] = {}
        for t in tanks:
            bid = t["batch_id"]
            avail.setdefault(bid, []).append(
                ("tank", t["tank_id"], t["current_volume_bbl"])
            )
        for d in deliveries:
            bid = d["batch_id"]
            avail.setdefault(bid, []).append(
                ("delivery", d["delivery_id"], d["volume_bbl"])
            )

        remaining: Dict[tuple, float] = {}
        for bid, sources in avail.items():
            for stype, sid, vol in sources:
                remaining[(stype, sid)] = vol

        # ------ 7. Gather online blending units ------
        units_by_product: Dict[str, list] = {}
        page = 1
        while True:
            res = self.tools["list_blending_units"](
                page=page, page_size=50, status_filter="online"
            )
            for u in res["data"]:
                units_by_product.setdefault(
                    u["product_type"], []
                ).append(u)
            if page * 50 >= res["total"]:
                break
            page += 1
        for k in units_by_product:
            units_by_product[k].sort(key=lambda u: u["unit_id"])

        # ------ 8. Schedule construction ------
        used_units: set = set()
        schedule = []
        quality_report = []
        entry_id = 0

        for dem in demands:
            ptype = dem["product_type"]
            tier = dem["quality_tier"]
            specs = q_specs.get(ptype, {}).get(tier, {})
            if not specs:
                continue

            # First available unit
            unit = None
            for u in units_by_product.get(ptype, []):
                if u["unit_id"] not in used_units:
                    unit = u
                    break
            if unit is None:
                continue

            # Qualifying batches
            qualifying = []
            for bid, sources in avail.items():
                total_rem = sum(
                    remaining.get((s[0], s[1]), 0) for s in sources
                )
                if total_rem <= 0:
                    continue
                bdata = batch_details.get(bid)
                if bdata is None or "error" in bdata:
                    continue
                ldata = lab_data.get(bid)
                if self._batch_qualifies(bdata, ldata, specs):
                    qualifying.append((bdata["cost_per_bbl"], bid))

            if not qualifying:
                continue

            qualifying.sort(key=lambda x: (x[0], x[1]))

            crude_needed = dem["volume_bbl"] / (1 - loss_pct / 100.0)
            crude_needed = min(crude_needed, unit["max_throughput_bbl"])

            components: Dict[int, float] = {}
            total_alloc = 0.0
            total_cost_w = 0.0

            for _cost, bid in qualifying:
                if total_alloc >= crude_needed:
                    break
                for stype, sid, _orig in avail[bid]:
                    key = (stype, sid)
                    rem = remaining.get(key, 0)
                    if rem <= 0:
                        continue
                    take = min(rem, crude_needed - total_alloc)
                    if take <= 0:
                        break
                    remaining[key] -= take
                    components[bid] = components.get(bid, 0) + take
                    total_alloc += take
                    total_cost_w += take * batch_details[bid]["cost_per_bbl"]
                    if total_alloc >= crude_needed:
                        break

            if total_alloc <= 0:
                continue

            product_vol = total_alloc * (1 - loss_pct / 100.0)
            w_cost = total_cost_w / total_alloc
            net_rev = (
                product_vol * dem["price_per_bbl"]
                - total_alloc * w_cost
                - total_alloc * unit["operating_cost_per_bbl"]
            )

            # Blend properties
            blend_props: Dict[str, float] = {}
            for prop in ["api_gravity", "sulfur_pct", "pour_point_f"]:
                wsum = sum(
                    batch_details[bid][prop] * vol
                    for bid, vol in components.items()
                )
                blend_props[prop] = wsum / total_alloc
            for prop in [
                "mercaptan_ppm", "salt_ptb", "nickel_ppm", "vanadium_ppm",
            ]:
                wsum = 0.0
                for bid, vol in components.items():
                    ld = lab_data.get(bid, {})
                    wsum += ld.get(prop, 0.0) * vol
                blend_props[prop] = wsum / total_alloc

            entry_id += 1
            used_units.add(unit["unit_id"])

            schedule.append({
                "entry_id": entry_id,
                "demand_id": dem["demand_id"],
                "unit_id": unit["unit_id"],
                "product_type": ptype,
                "quality_tier": tier,
                "crude_components": json.dumps(
                    {str(bid): round(vol, 2)
                     for bid, vol in components.items()}
                ),
                "total_crude_volume_bbl": round(total_alloc, 2),
                "product_volume_bbl": round(product_vol, 2),
                "net_revenue_usd": round(net_rev, 2),
            })

            quality_report.append({
                "entry_id": entry_id,
                "demand_id": dem["demand_id"],
                "product_type": ptype,
                "quality_tier": tier,
                "blend_properties": {
                    k: round(v, 4) for k, v in blend_props.items()
                },
                "spec_limits": specs,
                "all_specs_met": True,
            })

        # ------ 9. Write deliverables ------
        sched_path = os.path.join(self.workspace, "daily_blend_schedule.csv")
        with open(sched_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "entry_id", "demand_id", "unit_id", "product_type",
                "quality_tier", "crude_components",
                "total_crude_volume_bbl", "product_volume_bbl",
                "net_revenue_usd",
            ])
            writer.writeheader()
            writer.writerows(schedule)

        qv_path = os.path.join(
            self.workspace, "quality_verification.json"
        )
        with open(qv_path, "w") as f:
            json.dump(quality_report, f, indent=2)

        # ------ 10. Build response ------
        total_revenue = sum(e["net_revenue_usd"] for e in schedule)
        total_product = sum(e["product_volume_bbl"] for e in schedule)
        total_crude = sum(e["total_crude_volume_bbl"] for e in schedule)
        n_demands = len(schedule)

        action = (
            f"DAILY BLENDING SCHEDULE SUMMARY\n"
            f"Target Date: {TARGET}\n"
            f"Demands Fulfilled: {n_demands}\n"
            f"Total Product Volume: {total_product:,.2f} bbl\n"
            f"Total Crude Processed: {total_crude:,.2f} bbl\n"
            f"Total Net Revenue: ${total_revenue:,.2f}\n"
        )

        return self.step(action)
