import csv
import json
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

        self.tools = {}
        for name in dir(self):
            method = getattr(self, name, None)
            if callable(method) and hasattr(method, "_tool_info"):
                self.tools[name] = method

    def get_assistant_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format."""
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
        description=(
            "Returns a paginated list of buildings. Each entry includes "
            "building_id, building_name, address, and total_sqft."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page":      {"type": "integer", "description": "1-based page number."},
                "page_size": {"type": "integer", "description": "Records per page (max 50)."},
            },
            "required": ["page", "page_size"],
        },
    )
    def list_buildings(self, page: int, page_size: int) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM buildings")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT building_id, building_name, address, total_sqft "
            "FROM buildings ORDER BY building_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "page": page, "page_size": page_size, "total": total,
            "buildings": [
                {"building_id": r[0], "building_name": r[1],
                 "address": r[2], "total_sqft": r[3]}
                for r in rows
            ],
        }

    @tool(
        description=(
            "Returns all tenants in a given building. Each entry includes "
            "tenant_id, unit_number, tenant_name, and leased_sqft."
        ),
        parameters={
            "type": "object",
            "properties": {
                "building_id": {
                    "type": "string",
                    "description": "The building identifier, e.g. 'BLD-0001'.",
                },
            },
            "required": ["building_id"],
        },
    )
    def get_building_tenants(self, building_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT tenant_id, unit_number, tenant_name, leased_sqft "
            "FROM tenants WHERE building_id = ? ORDER BY tenant_id",
            (building_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "building_id": building_id,
            "tenants": [
                {"tenant_id": r[0], "unit_number": r[1],
                 "tenant_name": r[2], "leased_sqft": r[3]}
                for r in rows
            ],
        }

    @tool(
        description=(
            "Returns the lease utility clause for a specific tenant and utility type. "
            "Includes billing_method ('sub_metered', 'pro_rata_sqft', 'pro_rata_units', "
            "or 'fixed') and fixed_monthly (only present when billing_method is 'fixed')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "The tenant identifier, e.g. 'TNT-0001-01'.",
                },
                "utility_type": {
                    "type": "string",
                    "description": "One of 'electricity', 'gas', or 'water'.",
                },
            },
            "required": ["tenant_id", "utility_type"],
        },
    )
    def get_lease_clause(self, tenant_id: str, utility_type: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT billing_method, fixed_monthly "
            "FROM lease_utility_clauses WHERE tenant_id = ? AND utility_type = ?",
            (tenant_id, utility_type),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"No clause found for {tenant_id} / {utility_type}"}
        result = {"tenant_id": tenant_id, "utility_type": utility_type,
                  "billing_method": row[0]}
        if row[1] is not None:
            result["fixed_monthly"] = row[1]
        return result

    @tool(
        description=(
            "Returns the applicable utility tariff rate for a given utility type "
            "and billing period. The period should be in YYYY-MM format. "
            "Returns rate_per_unit and unit."
        ),
        parameters={
            "type": "object",
            "properties": {
                "utility_type": {
                    "type": "string",
                    "description": "One of 'electricity', 'gas', or 'water'.",
                },
                "period": {
                    "type": "string",
                    "description": "Billing period in YYYY-MM format, e.g. '2025-01'.",
                },
            },
            "required": ["utility_type", "period"],
        },
    )
    def get_tariff_rate(self, utility_type: str, period: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        period_date = period + "-01"
        cur.execute(
            "SELECT rate_per_unit, unit FROM tariff_schedules "
            "WHERE utility_type = ? AND effective_from <= ? "
            "ORDER BY effective_from DESC LIMIT 1",
            (utility_type, period_date),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"No tariff found for {utility_type} in {period}"}
        return {
            "utility_type": utility_type,
            "period": period,
            "rate_per_unit": row[0],
            "unit": row[1],
        }

    @tool(
        description=(
            "Returns the original billed amount for a specific tenant, utility type, "
            "and period from the historical billing records."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "description": "The tenant identifier.",
                },
                "utility_type": {
                    "type": "string",
                    "description": "One of 'electricity', 'gas', or 'water'.",
                },
                "period": {
                    "type": "string",
                    "description": "Billing period in YYYY-MM format.",
                },
            },
            "required": ["tenant_id", "utility_type", "period"],
        },
    )
    def get_original_billing(self, tenant_id: str, utility_type: str, period: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT original_billed FROM billing_history "
            "WHERE tenant_id = ? AND utility_type = ? AND period = ?",
            (tenant_id, utility_type, period),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"No billing record for {tenant_id}/{utility_type}/{period}"}
        return {
            "tenant_id": tenant_id,
            "utility_type": utility_type,
            "period": period,
            "original_billed": row[0],
        }

    # -------------------------------------------------------------- step

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion.

        Args:
            action: The agent's final response text.

        Returns:
            (reward, info) where reward is 0.0 – 1.0.
        """
        criteria = {}

        # Load ground truth
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT tenant_id, building_id, utility_type, period, "
            "billing_method, metered_charge, ca_charge, total_charge, "
            "original_billed, adjustment "
            "FROM ground_truth ORDER BY building_id, tenant_id, utility_type, period"
        )
        gt_rows = cur.fetchall()
        conn.close()

        gt = {}
        for r in gt_rows:
            key = (r[0], r[2], r[3])  # (tenant_id, utility_type, period)
            gt[key] = {
                "tenant_id": r[0], "building_id": r[1],
                "utility_type": r[2], "period": r[3],
                "billing_method": r[4],
                "metered_charge": r[5], "ca_charge": r[6],
                "total_charge": r[7], "original_billed": r[8],
                "adjustment": r[9],
            }

        total_rows = len(gt)

        # ── Criterion 1: file exists, correct columns, correct sort order (15 pts) ──
        ledger_path = os.path.join(self.workspace, "chargeback_ledger.csv")
        expected_cols = [
            "tenant_id", "tenant_name", "building_id", "utility_type", "period",
            "billing_method", "metered_charge", "ca_charge",
            "total_charge", "original_billed", "adjustment",
        ]
        agent_data = {}
        file_ok = False
        cols_ok = False
        sort_ok = False
        ordered_rows = []  # for sort check: (bid, tid, ut, period)
        if os.path.exists(ledger_path):
            try:
                with open(ledger_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in (reader.fieldnames or [])]
                    cols_ok = all(c in actual_cols for c in expected_cols)
                    for row in reader:
                        row = {k.strip(): v.strip() for k, v in row.items()}
                        key = (
                            row.get("tenant_id", ""),
                            row.get("utility_type", ""),
                            row.get("period", ""),
                        )
                        agent_data[key] = row
                        ordered_rows.append((
                            row.get("building_id", ""),
                            row.get("tenant_id", ""),
                            row.get("utility_type", ""),
                            row.get("period", ""),
                        ))
                file_ok = True
            except Exception:
                pass

        # Sort: building_id ASC, tenant_id ASC, utility_type ASC, period ASC
        if len(ordered_rows) >= 2:
            sort_ok = all(
                ordered_rows[i] <= ordered_rows[i + 1]
                for i in range(len(ordered_rows) - 1)
            )
        else:
            sort_ok = True

        c1 = 0
        if file_ok:
            c1 += 5
        if cols_ok:
            c1 += 5
        if sort_ok:
            c1 += 5
        criteria["file_structure"] = {
            "passed": c1 == 15, "score": c1, "max_score": 15,
            "reason": "" if c1 == 15 else (
                "File missing" if not file_ok else
                "Columns incorrect" if not cols_ok else
                "Rows not sorted by building_id, tenant_id, utility_type, period"
            ),
        }

        # ── Criterion 2: coverage – all rows present (10 pts) ────────────────
        present = sum(1 for key in gt if key in agent_data)
        c2 = round(present / total_rows * 10) if total_rows else 0
        criteria["coverage"] = {
            "passed": c2 == 10, "score": c2, "max_score": 10,
            "reason": "" if c2 == 10 else f"{total_rows - present} rows missing",
        }

        def _close(a, b, tol=0.02):
            try:
                return abs(float(a) - float(b)) <= tol
            except (ValueError, TypeError):
                return False

        # ── Criterion 3: metered_charge and ca_charge accuracy (10 pts) ─────────
        mc_ok = sum(
            1 for key, g in gt.items()
            if key in agent_data
            and _close(agent_data[key].get("metered_charge", ""), g["metered_charge"])
            and _close(agent_data[key].get("ca_charge", ""), g["ca_charge"])
        )
        c3 = round(mc_ok / total_rows * 10) if total_rows else 0
        criteria["metered_ca_accuracy"] = {
            "passed": c3 == 10, "score": c3, "max_score": 10,
            "reason": "" if c3 == 10 else f"{total_rows - mc_ok} rows have metered_charge or ca_charge errors",
        }

        # ── Criterion 4: total_charge accuracy (20 pts) ──────────────────────
        charge_ok = sum(
            1 for key, g in gt.items()
            if key in agent_data and _close(agent_data[key].get("total_charge", ""), g["total_charge"])
        )
        c4 = round(charge_ok / total_rows * 20) if total_rows else 0
        criteria["total_charge_accuracy"] = {
            "passed": c4 == 20, "score": c4, "max_score": 20,
            "reason": "" if c4 == 20 else f"{total_rows - charge_ok} rows have total_charge errors",
        }

        # ── Criterion 5: original_billed accuracy (15 pts) ───────────────────
        orig_ok = sum(
            1 for key, g in gt.items()
            if key in agent_data and _close(agent_data[key].get("original_billed", ""), g["original_billed"])
        )
        c5 = round(orig_ok / total_rows * 15) if total_rows else 0
        criteria["original_billed_accuracy"] = {
            "passed": c5 == 15, "score": c5, "max_score": 15,
            "reason": "" if c5 == 15 else f"{total_rows - orig_ok} rows have original_billed errors",
        }

        # ── Criterion 6: adjustment accuracy (20 pts) ────────────────────────
        adj_ok = sum(
            1 for key, g in gt.items()
            if key in agent_data and _close(agent_data[key].get("adjustment", ""), g["adjustment"])
        )
        c6_adj = round(adj_ok / total_rows * 20) if total_rows else 0
        criteria["adjustment_accuracy"] = {
            "passed": c6_adj == 20, "score": c6_adj, "max_score": 20,
            "reason": "" if c6_adj == 20 else f"{total_rows - adj_ok} rows have adjustment errors",
        }

        # ── Criterion 6: response mentions largest adjustments (10 pts) ──────
        # Tenants with |adjustment| > 5% of original_billed should be mentioned
        sig_tenants = set()
        for key, g in gt.items():
            orig = g["original_billed"]
            if orig > 0 and abs(g["adjustment"]) / orig > 0.05:
                sig_tenants.add(g["tenant_id"])
        mentioned = sum(1 for tid in sig_tenants if tid in action)
        c7 = round(mentioned / len(sig_tenants) * 10) if sig_tenants else 10
        criteria["response_summary"] = {
            "passed": c7 == 10, "score": c7, "max_score": 10,
            "reason": "" if c7 == 10 else (
                f"{len(sig_tenants) - mentioned} tenants with significant adjustments not mentioned"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score if max_score else 0.0, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # -------------------------------------------------------------- verify

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using only self.tools + workspace files,
        then call self.step() and return its result.
        """
        import glob as globmod

        UTILITY_TYPES = ["electricity", "gas", "water"]

        # 1. List all buildings
        all_buildings = []
        page = 1
        while True:
            res = self.tools["list_buildings"](page=page, page_size=50)
            all_buildings.extend(res["buildings"])
            if page * 50 >= res["total"]:
                break
            page += 1

        # 2. For each building, get tenants
        bld_tenant_map = {}   # bid -> list of tenant dicts
        bld_sqft_total = {}   # bid -> sum of all tenant leased_sqft
        for bld in all_buildings:
            bid = bld["building_id"]
            res = self.tools["get_building_tenants"](building_id=bid)
            bld_tenant_map[bid] = res["tenants"]
            bld_sqft_total[bid] = sum(t["leased_sqft"] for t in res["tenants"])

        # Collect all (tenant -> building) mapping
        tenant_bld = {}
        tenant_sqft_map = {}
        tenant_name_map = {}
        for bld in all_buildings:
            bid = bld["building_id"]
            for t in bld_tenant_map[bid]:
                tenant_bld[t["tenant_id"]] = bid
                tenant_sqft_map[t["tenant_id"]] = t["leased_sqft"]
                tenant_name_map[t["tenant_id"]] = t["tenant_name"]

        # 3. Read CA allocation JSONs
        ca_map = {}  # (bid, ut) -> {"ca_fraction": f, "allocation_basis": b}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "ca_allocation_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
            for bld in data:
                bid = bld["building_id"]
                for alloc in bld["common_area_allocations"]:
                    ca_map[(bid, alloc["utility_type"])] = {
                        "ca_fraction": alloc["ca_fraction"],
                        "allocation_basis": alloc["allocation_basis"],
                    }

        # 4. Read master meter CSVs
        master_map = {}  # (bid, ut, period) -> total_usage
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "master_meter_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row["building_id"], row["utility_type"], row["period"])
                    master_map[key] = float(row["total_usage"])

        # 5. Read sub-meter CSVs
        sub_map = {}  # (tid, ut, period) -> usage
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "sub_meter_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("usage"):
                        key = (row["tenant_id"], row["utility_type"], row["period"])
                        sub_map[key] = float(row["usage"])

        # 6. Determine periods from master_map keys
        periods = sorted(set(k[2] for k in master_map))

        # 7. Compute correct charges for every (tenant, utility, period)
        results = []
        for bld in all_buildings:
            bid = bld["building_id"]
            tenants_in_bld = bld_tenant_map[bid]
            num_t = len(tenants_in_bld)
            total_sqft = bld_sqft_total[bid]

            for t in tenants_in_bld:
                tid = t["tenant_id"]
                tsqft = t["leased_sqft"]

                for ut in UTILITY_TYPES:
                    clause = self.tools["get_lease_clause"](
                        tenant_id=tid, utility_type=ut
                    )
                    method = clause["billing_method"]
                    fixed_mo = clause.get("fixed_monthly")

                    for period in periods:
                        tariff = self.tools["get_tariff_rate"](
                            utility_type=ut, period=period
                        )
                        rate = tariff["rate_per_unit"]
                        master = master_map.get((bid, ut, period), 0.0)
                        ca_info = ca_map.get((bid, ut), {"ca_fraction": 0.0, "allocation_basis": "units"})
                        ca_frac = ca_info["ca_fraction"]
                        alloc_basis = ca_info["allocation_basis"]

                        if method == "fixed":
                            metered_charge = 0.0
                            ca_charge = 0.0
                            total_charge = fixed_mo

                        elif method == "sub_metered":
                            usage = sub_map.get((tid, ut, period), 0.0)
                            metered_charge = usage * rate
                            ca_cost = ca_frac * master * rate
                            if alloc_basis == "sqft":
                                ca_share = (tsqft / total_sqft) * ca_cost if total_sqft > 0 else 0.0
                            else:
                                ca_share = (1.0 / num_t) * ca_cost if num_t > 0 else 0.0
                            ca_charge = ca_share
                            total_charge = metered_charge + ca_charge

                        elif method == "pro_rata_sqft":
                            frac = tsqft / total_sqft if total_sqft > 0 else 0.0
                            metered_charge = frac * master * rate
                            ca_charge = 0.0
                            total_charge = metered_charge

                        else:  # pro_rata_units
                            frac = 1.0 / num_t if num_t > 0 else 0.0
                            metered_charge = frac * master * rate
                            ca_charge = 0.0
                            total_charge = metered_charge

                        # Original billing from DB
                        orig_res = self.tools["get_original_billing"](
                            tenant_id=tid, utility_type=ut, period=period
                        )
                        original_billed = orig_res.get("original_billed", 0.0)
                        adjustment = total_charge - original_billed

                        results.append({
                            "tenant_id": tid,
                            "tenant_name": tenant_name_map[tid],
                            "building_id": bid,
                            "utility_type": ut,
                            "period": period,
                            "billing_method": method,
                            "metered_charge": round(metered_charge, 2),
                            "ca_charge": round(ca_charge, 2),
                            "total_charge": round(total_charge, 2),
                            "original_billed": round(original_billed, 2),
                            "adjustment": round(adjustment, 2),
                        })

        # Sort: building_id, tenant_id, utility_type, period
        results.sort(key=lambda x: (
            x["building_id"], x["tenant_id"], x["utility_type"], x["period"]
        ))

        # 8. Write chargeback_ledger.csv
        ledger_path = os.path.join(self.workspace, "chargeback_ledger.csv")
        cols = [
            "tenant_id", "tenant_name", "building_id", "utility_type", "period",
            "billing_method", "metered_charge", "ca_charge",
            "total_charge", "original_billed", "adjustment",
        ]
        with open(ledger_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(results)

        # 9. Build action string mentioning tenants with significant adjustments
        sig = [
            r for r in results
            if r["original_billed"] > 0
            and abs(r["adjustment"]) / r["original_billed"] > 0.05
        ]
        sig_tenants = sorted(set(r["tenant_id"] for r in sig))
        lines = [
            "Chargeback reconciliation complete.",
            f"Ledger saved to {ledger_path}.",
            f"Total line items: {len(results)}",
            "",
            "Tenants with significant billing adjustments (>5% of original billed):",
        ]
        for tid in sig_tenants:
            lines.append(f"  {tid} ({tenant_name_map.get(tid, '')})")

        action = "\n".join(lines)
        return self.step(action)
