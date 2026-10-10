"""
Environment for the lease renewal incentive targeting task.
"""

import sqlite3
import os
import json
import csv
import yaml
import glob as glob_mod
from typing import Tuple, Dict, List, Any
from datetime import datetime


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
        description="List tenants with pagination. Returns tenant_id, name, unit, property_id, lease_start_date, lease_end_date, and monthly_rent for each tenant.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based).",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 20).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_tenants(self, page: int, page_size: int):
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM tenants")
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT tenant_id, name, unit, property_id, lease_start_date, lease_end_date, monthly_rent "
            "FROM tenants ORDER BY tenant_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"total": total, "page": page, "page_size": page_size, "tenants": rows}

    @tool(
        description="Search for tenants whose lease ends within a given date range (inclusive). Returns tenant_id, name, unit, property_id, lease_start_date, lease_end_date, monthly_rent.",
        parameters={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start of date range (YYYY-MM-DD, inclusive).",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of date range (YYYY-MM-DD, inclusive).",
                },
            },
            "required": ["start_date", "end_date"],
        },
    )
    def search_expiring_leases(self, start_date: str, end_date: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT tenant_id, name, unit, property_id, lease_start_date, lease_end_date, monthly_rent "
            "FROM tenants WHERE lease_end_date >= ? AND lease_end_date <= ? ORDER BY tenant_id",
            (start_date, end_date),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"count": len(rows), "tenants": rows}

    @tool(
        description="Get the full payment history for a specific tenant. Returns a list of payment records with due_date, paid_date, amount_due, and amount_paid.",
        parameters={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "integer",
                    "description": "The tenant's unique identifier.",
                },
            },
            "required": ["tenant_id"],
        },
    )
    def get_payment_history(self, tenant_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT due_date, paid_date, amount_due, amount_paid FROM payments "
            "WHERE tenant_id = ? ORDER BY due_date",
            (tenant_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"tenant_id": tenant_id, "payment_count": len(rows), "payments": rows}

    @tool(
        description="Get all maintenance requests filed by a specific tenant. Returns request_date, category, description, status, and resolved_date.",
        parameters={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "integer",
                    "description": "The tenant's unique identifier.",
                },
            },
            "required": ["tenant_id"],
        },
    )
    def get_maintenance_records(self, tenant_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT request_date, category, description, status, resolved_date "
            "FROM maintenance_requests WHERE tenant_id = ? ORDER BY request_date",
            (tenant_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"tenant_id": tenant_id, "request_count": len(rows), "requests": rows}

    @tool(
        description="Get all property damage incidents associated with a specific tenant. Returns incident_date, severity, description, repair_cost, and tenant_responsible (1 = yes, 0 = no).",
        parameters={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "integer",
                    "description": "The tenant's unique identifier.",
                },
            },
            "required": ["tenant_id"],
        },
    )
    def get_damage_incidents(self, tenant_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT incident_date, severity, description, repair_cost, tenant_responsible "
            "FROM damage_incidents WHERE tenant_id = ? ORDER BY incident_date",
            (tenant_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"tenant_id": tenant_id, "incident_count": len(rows), "incidents": rows}

    @tool(
        description="Get detailed information about a property including its address, neighborhood, bedrooms, square footage, property type, and year built.",
        parameters={
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "integer",
                    "description": "The property's unique identifier.",
                },
            },
            "required": ["property_id"],
        },
    )
    def get_property_info(self, property_id: int):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT property_id, address, neighborhood, bedrooms, sqft, property_type, year_built "
            "FROM properties WHERE property_id = ?",
            (property_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Property {property_id} not found."}

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _load_policy(self):
        with open(os.path.join(self.workspace, "renewal_policy.yaml")) as f:
            return yaml.safe_load(f)

    def _load_severity_weights(self):
        with open(os.path.join(self.workspace, "severity_weights.json")) as f:
            return json.load(f)

    def _load_discount_tiers(self):
        tiers = []
        with open(os.path.join(self.workspace, "discount_tiers.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                tiers.append({
                    "tier": row["tier"],
                    "min_score": float(row["min_score"]),
                    "max_score": float(row["max_score"]),
                    "discount_pct": float(row["discount_pct"]),
                    "lease_term_months": int(row["lease_term_months"]),
                })
        return tiers

    def _load_market_rents(self):
        """Load all market reports and compute average rent by (neighborhood, bedrooms)."""
        market = {}  # (neighborhood, bedrooms) -> list of rents
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "market_*"))):
            fname = os.path.basename(fpath)
            # extract neighborhood from filename: market_<name>.<ext>
            name_part = fname[len("market_"):]
            ext = name_part.rsplit(".", 1)[-1]
            nb_slug = name_part.rsplit(".", 1)[0]
            # convert slug back to neighborhood name (lowercase with underscores)
            listings = []
            if ext == "csv":
                with open(fpath) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        listings.append({"bedrooms": int(row["bedrooms"]), "monthly_rent": float(row["monthly_rent"])})
            elif ext == "json":
                with open(fpath) as f:
                    data = json.load(f)
                    for row in data:
                        listings.append({"bedrooms": int(row["bedrooms"]), "monthly_rent": float(row["monthly_rent"])})
            elif ext == "txt":
                with open(fpath) as f:
                    lines = f.readlines()
                    # skip header and separator
                    for line in lines[2:]:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 5:
                            listings.append({"bedrooms": int(parts[2]), "monthly_rent": float(parts[4])})
            elif ext == "md":
                with open(fpath) as f:
                    lines = f.readlines()
                    for line in lines[2:]:  # skip header + separator
                        parts = [p.strip() for p in line.strip().split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 5:
                            listings.append({"bedrooms": int(parts[2]), "monthly_rent": float(parts[4])})

            for l in listings:
                key = (nb_slug, l["bedrooms"])
                market.setdefault(key, []).append(l["monthly_rent"])

        # compute averages
        avg_market = {}
        for key, rents in market.items():
            avg_market[key] = round(sum(rents) / len(rents), 2)
        return avg_market

    def _compute_ground_truth(self):
        """Compute the full ground truth outreach list."""
        policy = self._load_policy()
        sev_weights = self._load_severity_weights()
        tiers = self._load_discount_tiers()
        avg_market = self._load_market_rents()

        ref_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        window = policy["lease_expiry_window_days"]
        elig = policy["eligibility"]
        scoring = policy["scoring"]
        mkt_adj = policy["market_adjustment"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # get expiring tenants
        from datetime import timedelta
        end_date = (ref_date + timedelta(days=window)).strftime("%Y-%m-%d")
        start_date = ref_date.strftime("%Y-%m-%d")
        cur.execute(
            "SELECT t.*, p.address, p.neighborhood, p.bedrooms, p.property_type "
            "FROM tenants t JOIN properties p ON t.property_id = p.property_id "
            "WHERE t.lease_end_date >= ? AND t.lease_end_date <= ?",
            (start_date, end_date),
        )
        expiring = [dict(r) for r in cur.fetchall()]

        results = []
        for t in expiring:
            tid = t["tenant_id"]

            # payment score
            cur.execute("SELECT due_date, paid_date FROM payments WHERE tenant_id = ?", (tid,))
            payments = cur.fetchall()
            if len(payments) == 0:
                payment_score = 0.0
            else:
                on_time = sum(1 for p in payments if p["paid_date"] <= p["due_date"])
                payment_score = on_time / len(payments)

            if payment_score < elig["min_payment_score"]:
                continue

            # maintenance frequency
            cur.execute("SELECT COUNT(*) as cnt FROM maintenance_requests WHERE tenant_id = ?", (tid,))
            maint_count = cur.fetchone()["cnt"]
            lease_start = datetime.strptime(t["lease_start_date"], "%Y-%m-%d")
            years = max((ref_date - lease_start).days / 365.25, 0.01)
            maint_freq = maint_count / years

            if maint_freq > elig["max_maintenance_frequency"]:
                continue

            # damage cost (weighted)
            cur.execute(
                "SELECT severity, repair_cost FROM damage_incidents WHERE tenant_id = ? AND tenant_responsible = 1",
                (tid,),
            )
            damage_rows = cur.fetchall()
            damage_cost_w = sum(r["repair_cost"] * sev_weights.get(r["severity"], 1.0) for r in damage_rows)

            if damage_cost_w > elig["max_damage_cost_weighted"]:
                continue

            # scores
            maint_score = max(0.0, 1.0 - maint_freq / elig["max_maintenance_frequency"])
            damage_score = max(0.0, 1.0 - damage_cost_w / elig["max_damage_cost_weighted"])
            overall = (
                scoring["payment_weight"] * payment_score
                + scoring["maintenance_weight"] * maint_score
                + scoring["damage_weight"] * damage_score
            )

            # tier
            tier_name = "bronze"
            discount_pct = 3
            lease_term = 12
            for tr in tiers:
                if tr["min_score"] <= overall < tr["max_score"] or (tr["max_score"] == 1.0 and overall == 1.0):
                    tier_name = tr["tier"]
                    discount_pct = tr["discount_pct"]
                    lease_term = tr["lease_term_months"]
                    break

            # market rent
            nb_slug = t["neighborhood"].lower().replace(" ", "_")
            market_rent = avg_market.get((nb_slug, t["bedrooms"]), t["monthly_rent"])

            # market adjustment
            if t["monthly_rent"] > market_rent * mkt_adj["rent_above_market_threshold"]:
                discount_pct += mkt_adj["extra_discount_pct"]

            proposed_rent = round(t["monthly_rent"] * (1 - discount_pct / 100.0), 2)

            results.append({
                "tenant_id": tid,
                "tenant_name": t["name"],
                "unit": t["unit"],
                "current_rent": t["monthly_rent"],
                "market_rent": market_rent,
                "payment_score": round(payment_score, 4),
                "overall_score": round(overall, 4),
                "tier": tier_name,
                "discount_pct": discount_pct,
                "proposed_rent": proposed_rent,
                "lease_term_months": lease_term,
            })

        conn.close()

        # sort by overall_score desc, tenant_id asc
        results.sort(key=lambda x: (-x["overall_score"], x["tenant_id"]))
        return results

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
        gt = self._compute_ground_truth()
        gt_ids = set(r["tenant_id"] for r in gt)
        gt_by_id = {r["tenant_id"]: r for r in gt}

        criteria = {}
        max_total = 0
        earned_total = 0

        # ---- Criterion 1: outreach_list.csv exists (5 pts) ----
        outreach_path = os.path.join(self.workspace, "outreach_list.csv")
        c1_max = 5
        max_total += c1_max
        if os.path.exists(outreach_path):
            criteria["file_exists"] = {"passed": True, "score": c1_max, "max_score": c1_max}
            earned_total += c1_max
        else:
            criteria["file_exists"] = {"passed": False, "score": 0, "max_score": c1_max, "reason": "outreach_list.csv not found"}
            # can't evaluate further if file missing
            max_total_final = sum(v["max_score"] for v in criteria.values())
            return earned_total / max(max_total_final, 1), {
                "eval_criteria": criteria,
                "total_score": earned_total,
                "max_score": max_total_final,
            }

        # parse the CSV
        try:
            with open(outreach_path) as f:
                reader = csv.DictReader(f)
                submitted_rows = list(reader)
                submitted_cols = reader.fieldnames or []
        except Exception as e:
            criteria["file_parseable"] = {"passed": False, "score": 0, "max_score": 0, "reason": str(e)}
            return 0.1, {"eval_criteria": criteria, "total_score": earned_total, "max_score": 100}

        # ---- Criterion 2: correct columns (10 pts) ----
        expected_cols = ["tenant_id", "tenant_name", "unit", "current_rent", "market_rent",
                         "payment_score", "overall_score", "tier", "discount_pct",
                         "proposed_rent", "lease_term_months"]
        c2_max = 5
        max_total += c2_max
        if submitted_cols == expected_cols:
            criteria["correct_columns"] = {"passed": True, "score": c2_max, "max_score": c2_max}
            earned_total += c2_max
        else:
            # partial credit if columns present but wrong order
            if set(submitted_cols) >= set(expected_cols):
                criteria["correct_columns"] = {"passed": False, "score": 5, "max_score": c2_max, "reason": "Columns present but wrong order"}
                earned_total += 5
            else:
                missing = set(expected_cols) - set(submitted_cols)
                criteria["correct_columns"] = {"passed": False, "score": 0, "max_score": c2_max, "reason": f"Missing columns: {missing}"}

        # ---- Criterion 3: correct set of eligible tenants (20 pts) ----
        c3_max = 20
        max_total += c3_max
        submitted_ids = set()
        for row in submitted_rows:
            try:
                submitted_ids.add(int(row.get("tenant_id", -1)))
            except (ValueError, TypeError):
                pass
        if submitted_ids == gt_ids:
            criteria["correct_tenants"] = {"passed": True, "score": c3_max, "max_score": c3_max}
            earned_total += c3_max
        else:
            extra = submitted_ids - gt_ids
            missing = gt_ids - submitted_ids
            correct = submitted_ids & gt_ids
            partial = round(c3_max * len(correct) / max(len(gt_ids), 1), 1)
            criteria["correct_tenants"] = {
                "passed": False, "score": partial, "max_score": c3_max,
                "reason": f"Extra: {sorted(extra)}, Missing: {sorted(missing)}"
            }
            earned_total += partial

        # ---- Criterion 4: correct payment scores (15 pts) ----
        c4_max = 15
        max_total += c4_max
        ps_correct = 0
        ps_total = 0
        for row in submitted_rows:
            try:
                tid = int(row["tenant_id"])
            except (KeyError, ValueError):
                continue
            if tid in gt_by_id:
                ps_total += 1
                try:
                    sub_ps = round(float(row.get("payment_score", -1)), 4)
                except (ValueError, TypeError):
                    continue
                if abs(sub_ps - gt_by_id[tid]["payment_score"]) < 0.005:
                    ps_correct += 1
        if ps_total > 0 and ps_correct == ps_total:
            criteria["payment_scores"] = {"passed": True, "score": c4_max, "max_score": c4_max}
            earned_total += c4_max
        else:
            partial = round(c4_max * ps_correct / max(ps_total, 1), 1)
            criteria["payment_scores"] = {
                "passed": False, "score": partial, "max_score": c4_max,
                "reason": f"{ps_correct}/{ps_total} correct"
            }
            earned_total += partial

        # ---- Criterion 5: correct overall scores and tiers (15 pts) ----
        c5_max = 15
        max_total += c5_max
        os_correct = 0
        os_total = 0
        for row in submitted_rows:
            try:
                tid = int(row["tenant_id"])
            except (KeyError, ValueError):
                continue
            if tid in gt_by_id:
                os_total += 1
                try:
                    sub_os = round(float(row.get("overall_score", -1)), 4)
                    sub_tier = row.get("tier", "").strip().lower()
                except (ValueError, TypeError):
                    continue
                gt_rec = gt_by_id[tid]
                if abs(sub_os - gt_rec["overall_score"]) < 0.005 and sub_tier == gt_rec["tier"]:
                    os_correct += 1
        if os_total > 0 and os_correct == os_total:
            criteria["overall_scores_tiers"] = {"passed": True, "score": c5_max, "max_score": c5_max}
            earned_total += c5_max
        else:
            partial = round(c5_max * os_correct / max(os_total, 1), 1)
            criteria["overall_scores_tiers"] = {
                "passed": False, "score": partial, "max_score": c5_max,
                "reason": f"{os_correct}/{os_total} correct"
            }
            earned_total += partial

        # ---- Criterion 6: correct discount and proposed rent (15 pts) ----
        c6_max = 15
        max_total += c6_max
        dr_correct = 0
        dr_total = 0
        for row in submitted_rows:
            try:
                tid = int(row["tenant_id"])
            except (KeyError, ValueError):
                continue
            if tid in gt_by_id:
                dr_total += 1
                try:
                    sub_disc = float(row.get("discount_pct", -1))
                    sub_pr = round(float(row.get("proposed_rent", -1)), 2)
                    sub_lt = int(row.get("lease_term_months", -1))
                except (ValueError, TypeError):
                    continue
                gt_rec = gt_by_id[tid]
                if (abs(sub_disc - gt_rec["discount_pct"]) < 0.01
                        and abs(sub_pr - gt_rec["proposed_rent"]) < 0.01
                        and sub_lt == gt_rec["lease_term_months"]):
                    dr_correct += 1
        if dr_total > 0 and dr_correct == dr_total:
            criteria["discount_rent"] = {"passed": True, "score": c6_max, "max_score": c6_max}
            earned_total += c6_max
        else:
            partial = round(c6_max * dr_correct / max(dr_total, 1), 1)
            criteria["discount_rent"] = {
                "passed": False, "score": partial, "max_score": c6_max,
                "reason": f"{dr_correct}/{dr_total} correct"
            }
            earned_total += partial

        # ---- Criterion 7: correct sorting (10 pts) ----
        c7_max = 10
        max_total += c7_max
        submitted_id_order = []
        for row in submitted_rows:
            try:
                submitted_id_order.append(int(row["tenant_id"]))
            except (KeyError, ValueError):
                pass
        gt_id_order = [r["tenant_id"] for r in gt]
        if submitted_id_order == gt_id_order:
            criteria["sorting"] = {"passed": True, "score": c7_max, "max_score": c7_max}
            earned_total += c7_max
        else:
            criteria["sorting"] = {"passed": False, "score": 0, "max_score": c7_max, "reason": "Wrong sort order"}

        # ---- Criterion 8: response summary (15 pts) ----
        c8_max = 15
        max_total += c8_max
        expected_count = len(gt)
        if str(expected_count) in action:
            criteria["response_summary"] = {"passed": True, "score": c8_max, "max_score": c8_max}
            earned_total += c8_max
        else:
            criteria["response_summary"] = {
                "passed": False, "score": 0, "max_score": c8_max,
                "reason": f"Expected count {expected_count} not found in response"
            }

        reward = earned_total / max(max_total, 1)
        return reward, {
            "eval_criteria": criteria,
            "total_score": earned_total,
            "max_score": max_total,
        }

    # ------------------------------------------------------------------
    # Verify
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
        tool_calls = 0

        # --- Step 1: read workspace config files ---
        with open(os.path.join(self.workspace, "renewal_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        with open(os.path.join(self.workspace, "severity_weights.json")) as f:
            sev_weights = json.load(f)

        tiers = []
        with open(os.path.join(self.workspace, "discount_tiers.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                tiers.append({
                    "tier": row["tier"],
                    "min_score": float(row["min_score"]),
                    "max_score": float(row["max_score"]),
                    "discount_pct": float(row["discount_pct"]),
                    "lease_term_months": int(row["lease_term_months"]),
                })

        # --- Step 2: load market reports ---
        avg_market = {}  # (nb_slug, bedrooms) -> avg rent
        for fpath in sorted(glob_mod.glob(os.path.join(self.workspace, "market_*"))):
            fname = os.path.basename(fpath)
            name_part = fname[len("market_"):]
            ext = name_part.rsplit(".", 1)[-1]
            nb_slug = name_part.rsplit(".", 1)[0]
            listings = []
            if ext == "csv":
                with open(fpath) as f:
                    rdr = csv.DictReader(f)
                    for row in rdr:
                        listings.append({"bedrooms": int(row["bedrooms"]), "monthly_rent": float(row["monthly_rent"])})
            elif ext == "json":
                with open(fpath) as f:
                    data = json.load(f)
                    for row in data:
                        listings.append({"bedrooms": int(row["bedrooms"]), "monthly_rent": float(row["monthly_rent"])})
            elif ext == "txt":
                with open(fpath) as f:
                    lines = f.readlines()
                    for line in lines[2:]:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 5:
                            listings.append({"bedrooms": int(parts[2]), "monthly_rent": float(parts[4])})
            elif ext == "md":
                with open(fpath) as f:
                    lines = f.readlines()
                    for line in lines[2:]:
                        parts = [p.strip() for p in line.strip().split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 5:
                            listings.append({"bedrooms": int(parts[2]), "monthly_rent": float(parts[4])})
            for l in listings:
                key = (nb_slug, l["bedrooms"])
                avg_market.setdefault(key, []).append(l["monthly_rent"])
        for key in avg_market:
            rents = avg_market[key]
            avg_market[key] = round(sum(rents) / len(rents), 2)

        # --- Step 3: search for expiring leases via tools ---
        ref_date = policy["reference_date"]
        window = policy["lease_expiry_window_days"]
        from datetime import timedelta
        ref_dt = datetime.strptime(ref_date, "%Y-%m-%d")
        end_dt = ref_dt + timedelta(days=window)

        result = self.tools["search_expiring_leases"](
            start_date=ref_date,
            end_date=end_dt.strftime("%Y-%m-%d"),
        )
        tool_calls += 1
        expiring_tenants = result["tenants"]

        elig = policy["eligibility"]
        scoring = policy["scoring"]
        mkt_adj = policy["market_adjustment"]

        outreach = []
        for t in expiring_tenants:
            tid = t["tenant_id"]

            # payment history
            pay_result = self.tools["get_payment_history"](tenant_id=tid)
            tool_calls += 1
            payments = pay_result["payments"]
            if len(payments) == 0:
                continue
            on_time = sum(1 for p in payments if p["paid_date"] <= p["due_date"])
            payment_score = on_time / len(payments)

            if payment_score < elig["min_payment_score"]:
                continue

            # maintenance records
            maint_result = self.tools["get_maintenance_records"](tenant_id=tid)
            tool_calls += 1
            maint_count = maint_result["request_count"]
            lease_start = datetime.strptime(t["lease_start_date"], "%Y-%m-%d")
            years = max((ref_dt - lease_start).days / 365.25, 0.01)
            maint_freq = maint_count / years

            if maint_freq > elig["max_maintenance_frequency"]:
                continue

            # damage incidents
            dmg_result = self.tools["get_damage_incidents"](tenant_id=tid)
            tool_calls += 1
            damage_cost_w = 0.0
            for inc in dmg_result["incidents"]:
                if inc["tenant_responsible"] == 1:
                    damage_cost_w += inc["repair_cost"] * sev_weights.get(inc["severity"], 1.0)

            if damage_cost_w > elig["max_damage_cost_weighted"]:
                continue

            # property info (for neighborhood & bedrooms)
            prop_result = self.tools["get_property_info"](property_id=t["property_id"])
            tool_calls += 1

            # scores
            maint_score = max(0.0, 1.0 - maint_freq / elig["max_maintenance_frequency"])
            damage_score = max(0.0, 1.0 - damage_cost_w / elig["max_damage_cost_weighted"])
            overall = (
                scoring["payment_weight"] * payment_score
                + scoring["maintenance_weight"] * maint_score
                + scoring["damage_weight"] * damage_score
            )

            # tier
            tier_name = "bronze"
            discount_pct = 3.0
            lease_term = 12
            for tr in tiers:
                if tr["min_score"] <= overall < tr["max_score"] or (tr["max_score"] == 1.0 and overall == 1.0):
                    tier_name = tr["tier"]
                    discount_pct = tr["discount_pct"]
                    lease_term = tr["lease_term_months"]
                    break

            # market rent
            nb_slug = prop_result["neighborhood"].lower().replace(" ", "_")
            bedrooms = prop_result["bedrooms"]
            market_rent = avg_market.get((nb_slug, bedrooms), t["monthly_rent"])

            # market adjustment
            if t["monthly_rent"] > market_rent * mkt_adj["rent_above_market_threshold"]:
                discount_pct += mkt_adj["extra_discount_pct"]

            proposed_rent = round(t["monthly_rent"] * (1 - discount_pct / 100.0), 2)

            outreach.append({
                "tenant_id": tid,
                "tenant_name": t["name"],
                "unit": t["unit"],
                "current_rent": t["monthly_rent"],
                "market_rent": market_rent,
                "payment_score": round(payment_score, 4),
                "overall_score": round(overall, 4),
                "tier": tier_name,
                "discount_pct": discount_pct,
                "proposed_rent": proposed_rent,
                "lease_term_months": lease_term,
            })

        # sort by overall_score desc, tenant_id asc
        outreach.sort(key=lambda x: (-x["overall_score"], x["tenant_id"]))

        # --- Step 4: write outreach_list.csv ---
        fieldnames = ["tenant_id", "tenant_name", "unit", "current_rent", "market_rent",
                       "payment_score", "overall_score", "tier", "discount_pct",
                       "proposed_rent", "lease_term_months"]
        outreach_path = os.path.join(self.workspace, "outreach_list.csv")
        with open(outreach_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(outreach)

        # --- Step 5: build action string ---
        action = (
            f"Identified {len(outreach)} tenants eligible for lease renewal incentives "
            f"out of {len(expiring_tenants)} tenants with leases expiring within the next {window} days. "
            f"The outreach list has been saved to outreach_list.csv with recommended offer terms "
            f"including tier classification, discount percentage, proposed rent, and lease term."
        )

        assert tool_calls >= 15, f"Tool-call floor not met: {tool_calls} < 15"

        return self.step(action)
