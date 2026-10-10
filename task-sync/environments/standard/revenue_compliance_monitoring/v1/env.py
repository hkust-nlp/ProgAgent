import csv
import json
import os
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

    # ── Helper ─────────────────────────────────────────────────────────────────

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ── Tools ──────────────────────────────────────────────────────────────────

    @tool(
        description=(
            "List distributor partners with optional filters. Returns a paginated "
            "list of distributors. Each entry contains id, name, country, "
            "territory_code, partner_tier, registration_date, and active status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "territory": {
                    "type": "string",
                    "description": "Filter by territory code (e.g. 'NA', 'EMEA-W'). Omit for all.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "inactive", "all"],
                    "description": "Filter by active status. Default 'all'.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1. Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_distributors(self, territory: str = None, status: str = "all",
                          page: int = 1, page_size: int = 20) -> dict:
        conn = self._conn()
        c = conn.cursor()
        clauses, params = [], []
        if territory:
            clauses.append("territory_code = ?")
            params.append(territory)
        if status == "active":
            clauses.append("active = 1")
        elif status == "inactive":
            clauses.append("active = 0")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        c.execute(f"SELECT COUNT(*) FROM distributors {where}", params)
        total = c.fetchone()[0]
        offset = (max(1, page) - 1) * page_size
        c.execute(
            f"SELECT id, name, country, territory_code, partner_tier, "
            f"registration_date, active FROM distributors {where} "
            f"ORDER BY id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = c.fetchall()
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "distributors": [
                {
                    "id": r[0], "name": r[1], "country": r[2],
                    "territory_code": r[3], "partner_tier": r[4],
                    "registration_date": r[5], "active": bool(r[6]),
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Get full details for a single distributor by ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "distributor_id": {
                    "type": "integer",
                    "description": "The distributor's numeric ID.",
                },
            },
            "required": ["distributor_id"],
        },
    )
    def get_distributor_details(self, distributor_id: int) -> dict:
        conn = self._conn()
        c = conn.cursor()
        c.execute(
            "SELECT id, name, country, territory_code, partner_tier, "
            "registration_date, active FROM distributors WHERE id = ?",
            (distributor_id,),
        )
        r = c.fetchone()
        conn.close()
        if not r:
            return {"error": f"Distributor {distributor_id} not found."}
        return {
            "id": r[0], "name": r[1], "country": r[2],
            "territory_code": r[3], "partner_tier": r[4],
            "registration_date": r[5], "active": bool(r[6]),
        }

    @tool(
        description=(
            "Retrieve all license agreements for a given distributor. Each "
            "agreement includes agreement_code, territory_code, product_category, "
            "effective_date, expiry_date, min_annual_volume, royalty_discount_pct, "
            "and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "distributor_id": {
                    "type": "integer",
                    "description": "The distributor's numeric ID.",
                },
            },
            "required": ["distributor_id"],
        },
    )
    def get_agreements_for_distributor(self, distributor_id: int) -> dict:
        conn = self._conn()
        c = conn.cursor()
        c.execute(
            "SELECT id, agreement_code, distributor_id, territory_code, "
            "product_category, effective_date, expiry_date, min_annual_volume, "
            "royalty_discount_pct, status "
            "FROM license_agreements WHERE distributor_id = ? ORDER BY id",
            (distributor_id,),
        )
        rows = c.fetchall()
        conn.close()
        return {
            "agreements": [
                {
                    "id": r[0], "agreement_code": r[1],
                    "distributor_id": r[2], "territory_code": r[3],
                    "product_category": r[4], "effective_date": r[5],
                    "expiry_date": r[6], "min_annual_volume": r[7],
                    "royalty_discount_pct": r[8], "status": r[9],
                }
                for r in rows
            ]
        }

    @tool(
        description=(
            "Look up a product SKU by its code (e.g. 'SKU-1000'). Returns "
            "id, sku_code, product_name, category, unit_price, and base_royalty_pct."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sku_code": {
                    "type": "string",
                    "description": "The SKU code to look up.",
                },
            },
            "required": ["sku_code"],
        },
    )
    def get_sku_details(self, sku_code: str) -> dict:
        conn = self._conn()
        c = conn.cursor()
        c.execute(
            "SELECT id, sku_code, product_name, category, unit_price, "
            "base_royalty_pct FROM product_skus WHERE sku_code = ?",
            (sku_code,),
        )
        r = c.fetchone()
        conn.close()
        if not r:
            return {"error": f"SKU '{sku_code}' not found."}
        return {
            "id": r[0], "sku_code": r[1], "product_name": r[2],
            "category": r[3], "unit_price": r[4], "base_royalty_pct": r[5],
        }

    @tool(
        description=(
            "Look up a product SKU by its numeric database ID. Returns "
            "id, sku_code, product_name, category, unit_price, and base_royalty_pct."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "integer",
                    "description": "The SKU numeric ID.",
                },
            },
            "required": ["sku_id"],
        },
    )
    def get_sku_by_id(self, sku_id: int) -> dict:
        conn = self._conn()
        c = conn.cursor()
        c.execute(
            "SELECT id, sku_code, product_name, category, unit_price, "
            "base_royalty_pct FROM product_skus WHERE id = ?",
            (sku_id,),
        )
        r = c.fetchone()
        conn.close()
        if not r:
            return {"error": f"SKU id {sku_id} not found."}
        return {
            "id": r[0], "sku_code": r[1], "product_name": r[2],
            "category": r[3], "unit_price": r[4], "base_royalty_pct": r[5],
        }

    @tool(
        description=(
            "Retrieve shipment records for a distributor. Returns paginated "
            "results including sku_id, territory_code, quantity, ship_date, "
            "reported_royalty, and invoice_number."
        ),
        parameters={
            "type": "object",
            "properties": {
                "distributor_id": {
                    "type": "integer",
                    "description": "The distributor's numeric ID.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number, starting at 1. Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page. Default 50.",
                },
            },
            "required": ["distributor_id"],
        },
    )
    def get_shipment_records(self, distributor_id: int, page: int = 1,
                             page_size: int = 50) -> dict:
        conn = self._conn()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM shipments WHERE distributor_id = ?",
            (distributor_id,),
        )
        total = c.fetchone()[0]
        offset = (max(1, page) - 1) * page_size
        c.execute(
            "SELECT id, distributor_id, sku_id, territory_code, quantity, "
            "ship_date, reported_royalty, invoice_number "
            "FROM shipments WHERE distributor_id = ? ORDER BY id "
            "LIMIT ? OFFSET ?",
            (distributor_id, page_size, offset),
        )
        rows = c.fetchall()
        conn.close()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "shipments": [
                {
                    "id": r[0], "distributor_id": r[1], "sku_id": r[2],
                    "territory_code": r[3], "quantity": r[4],
                    "ship_date": r[5], "reported_royalty": r[6],
                    "invoice_number": r[7],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Retrieve audit exception records for a distributor. Returns all "
            "exception entries including exception_type, severity, finding_detail, "
            "audit_date, and resolved status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "distributor_id": {
                    "type": "integer",
                    "description": "The distributor's numeric ID.",
                },
            },
            "required": ["distributor_id"],
        },
    )
    def get_audit_exceptions(self, distributor_id: int) -> dict:
        conn = self._conn()
        c = conn.cursor()
        c.execute(
            "SELECT id, distributor_id, exception_type, severity, "
            "finding_detail, audit_date, resolved "
            "FROM audit_exceptions WHERE distributor_id = ? ORDER BY id",
            (distributor_id,),
        )
        rows = c.fetchall()
        conn.close()
        return {
            "exceptions": [
                {
                    "id": r[0], "distributor_id": r[1],
                    "exception_type": r[2], "severity": r[3],
                    "finding_detail": r[4], "audit_date": r[5],
                    "resolved": bool(r[6]),
                }
                for r in rows
            ]
        }

    # ── Ground-truth computation (shared by step & verify) ─────────────────────

    def _compute_ground_truth(self):
        """Compute the full ground-truth leakage analysis from DB + workspace."""
        conn = self._conn()
        c = conn.cursor()

        # Load workspace configs
        with open(os.path.join(self.workspace, "territory_modifiers.yaml")) as f:
            t_mods = yaml.safe_load(f)["territory_modifiers"]
        with open(os.path.join(self.workspace, "risk_scoring_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "compliance_config.json")) as f:
            comp = json.load(f)

        fy_start = comp["fiscal_year_start"]
        fy_end = comp["fiscal_year_end"]
        thresh_amt = comp["leakage_threshold_amount"]
        thresh_pct = comp["leakage_threshold_pct"]

        weights = policy["scoring_weights"]
        sev_pts = policy["severity_points"]
        risk_cats = policy["risk_categories"]
        norm = policy["normalization"]

        # All active distributors
        c.execute("SELECT id, name, territory_code FROM distributors WHERE active = 1")
        dists = {r[0]: {"name": r[1], "territory": r[2]} for r in c.fetchall()}

        # All SKUs
        c.execute("SELECT id, sku_code, category, unit_price, base_royalty_pct FROM product_skus")
        skus = {}
        for r in c.fetchall():
            skus[r[0]] = {
                "sku_code": r[1], "category": r[2],
                "unit_price": r[3], "base_royalty_pct": r[4],
            }

        # All agreements indexed by (distributor_id, territory, category)
        c.execute(
            "SELECT id, distributor_id, territory_code, product_category, "
            "effective_date, expiry_date, min_annual_volume, royalty_discount_pct, status "
            "FROM license_agreements"
        )
        agr_idx = {}
        all_agreements = []
        for r in c.fetchall():
            a = {
                "id": r[0], "distributor_id": r[1], "territory_code": r[2],
                "product_category": r[3], "effective_date": r[4],
                "expiry_date": r[5], "min_annual_volume": r[6],
                "royalty_discount_pct": r[7], "status": r[8],
            }
            all_agreements.append(a)
            key = (r[1], r[2], r[3])
            agr_idx.setdefault(key, []).append(a)

        # Shipments within fiscal year for active distributors
        c.execute(
            "SELECT id, distributor_id, sku_id, territory_code, quantity, "
            "ship_date, reported_royalty, invoice_number FROM shipments "
            "WHERE ship_date >= ? AND ship_date <= ? ORDER BY id",
            (fy_start, fy_end),
        )
        all_shipments = c.fetchall()
        conn.close()

        # Load verification reports
        verif = {}  # invoice_number -> verified_quantity
        for fn in os.listdir(self.workspace):
            if fn.startswith("verification_report_") and fn.endswith(".csv"):
                path = os.path.join(self.workspace, fn)
                with open(path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        verif[row["invoice_number"]] = int(row["verified_quantity"])

        def best_agreement(dist_id, terr, cat, ship_dt):
            for a in agr_idx.get((dist_id, terr, cat), []):
                if (a["status"] == "active"
                        and a["effective_date"] <= ship_dt <= a["expiry_date"]):
                    return a
            return None

        # Per-distributor aggregation
        dist_data = {}  # dist_id -> {...}
        for r in all_shipments:
            sid, dist_id, sku_id, terr, qty, ship_dt, rep_roy, inv = r
            if dist_id not in dists:
                continue
            sku = skus.get(sku_id)
            if not sku:
                continue
            t_mod = t_mods.get(terr, 1.0)
            agr = best_agreement(dist_id, terr, sku["category"], ship_dt)
            discount = agr["royalty_discount_pct"] / 100.0 if agr else 0.0
            expected = qty * sku["unit_price"] * sku["base_royalty_pct"] * t_mod * (1 - discount)

            # Check verified quantity
            vq = verif.get(inv)
            if vq is not None and vq > qty:
                adj_expected = vq * sku["unit_price"] * sku["base_royalty_pct"] * t_mod * (1 - discount)
            else:
                adj_expected = expected

            entry = dist_data.setdefault(dist_id, {
                "total_expected": 0.0,
                "total_reported": 0.0,
                "qty_disc_count": 0,
                "shipment_categories": {},  # (territory, category) -> total qty
            })
            entry["total_expected"] += adj_expected
            entry["total_reported"] += rep_roy

            if vq is not None and vq != qty:
                entry["qty_disc_count"] += 1

            cat_key = (terr, sku["category"])
            entry["shipment_categories"][cat_key] = (
                entry["shipment_categories"].get(cat_key, 0) + qty
            )

        # Volume gap per distributor
        for dist_id in list(dist_data.keys()):
            entry = dist_data[dist_id]
            gaps = []
            for a in all_agreements:
                if a["distributor_id"] != dist_id or a["status"] != "active":
                    continue
                if a["expiry_date"] < fy_start or a["effective_date"] > fy_end:
                    continue
                cat_key = (a["territory_code"], a["product_category"])
                actual = entry["shipment_categories"].get(cat_key, 0)
                committed = a["min_annual_volume"]
                if committed > 0 and actual < committed:
                    gap_pct = (committed - actual) / committed
                    gaps.append(gap_pct)
            entry["avg_volume_gap"] = (sum(gaps) / len(gaps)) if gaps else 0.0

        # Audit severity per distributor
        conn2 = self._conn()
        c2 = conn2.cursor()
        c2.execute(
            "SELECT distributor_id, severity, resolved FROM audit_exceptions"
        )
        audit_data = {}
        for r in c2.fetchall():
            dist_id, sev, resolved = r
            if not resolved:
                audit_data.setdefault(dist_id, []).append(sev)
        conn2.close()

        # Compute risk scores
        results = []
        for dist_id, info in dists.items():
            entry = dist_data.get(dist_id, {
                "total_expected": 0.0, "total_reported": 0.0,
                "qty_disc_count": 0, "avg_volume_gap": 0.0,
                "shipment_categories": {},
            })
            te = entry["total_expected"]
            tr = entry["total_reported"]
            leakage = max(0.0, te - tr)
            leak_pct = leakage / te if te > 0 else 0.0

            # Check thresholds
            if leakage < thresh_amt and leak_pct < thresh_pct:
                continue

            # Component scores
            s_leak_amt = min(leakage / norm["max_leakage_amount"] * 100, 100)
            s_leak_pct = min(leak_pct / norm["max_leakage_pct"] * 100, 100)

            unresolved = audit_data.get(dist_id, [])
            if unresolved:
                s_audit = sum(sev_pts.get(s, 0) for s in unresolved) / len(unresolved)
            else:
                s_audit = 0.0

            vol_gap = entry.get("avg_volume_gap", 0.0)
            s_vol = min(vol_gap / norm["max_volume_gap_pct"] * 100, 100)

            qd = entry["qty_disc_count"]
            s_qd = min(qd / norm["max_quantity_discrepancies"] * 100, 100)

            risk_score = (
                weights["leakage_amount"] * s_leak_amt
                + weights["leakage_percentage"] * s_leak_pct
                + weights["audit_severity"] * s_audit
                + weights["volume_gap"] * s_vol
                + weights["quantity_discrepancy"] * s_qd
            )

            # Risk category
            cat = "Low"
            for cat_name in ["critical", "high", "medium", "low"]:
                if risk_score >= risk_cats[cat_name]:
                    cat = cat_name.capitalize()
                    break

            # Primary risk factor
            components = {
                "leakage_amount": weights["leakage_amount"] * s_leak_amt,
                "leakage_percentage": weights["leakage_percentage"] * s_leak_pct,
                "audit_severity": weights["audit_severity"] * s_audit,
                "volume_gap": weights["volume_gap"] * s_vol,
                "quantity_discrepancy": weights["quantity_discrepancy"] * s_qd,
            }
            primary = max(components, key=components.get)

            results.append({
                "partner_id": dist_id,
                "partner_name": info["name"],
                "territory": info["territory"],
                "total_expected_royalty": round(te, 2),
                "total_reported_royalty": round(tr, 2),
                "leakage_amount": round(leakage, 2),
                "leakage_pct": round(leak_pct, 4),
                "quantity_discrepancies": qd,
                "risk_score": round(risk_score, 2),
                "risk_category": cat,
                "primary_risk_factor": primary,
            })

        results.sort(key=lambda x: (-x["risk_score"], x["partner_id"]))
        high_risk = [r for r in results if r["risk_category"] in ("Critical", "High")]
        return results, high_risk, comp

    # ── Step ───────────────────────────────────────────────────────────────────

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's
        final response.
        """
        results, high_risk, comp = self._compute_ground_truth()
        criteria = {}
        max_score = 0

        # ── Criterion 1: leakage_analysis.csv exists and has correct columns (15 pts)
        c1_max = 15
        max_score += c1_max
        la_path = os.path.join(self.workspace, "leakage_analysis.csv")
        la_ok = False
        la_rows = []
        expected_cols = [
            "partner_id", "partner_name", "territory",
            "total_expected_royalty", "total_reported_royalty",
            "leakage_amount", "leakage_pct", "quantity_discrepancies",
            "risk_score", "risk_category",
        ]
        if os.path.exists(la_path):
            with open(la_path) as f:
                reader = csv.DictReader(f)
                la_rows = list(reader)
            if reader.fieldnames and all(c in reader.fieldnames for c in expected_cols):
                la_ok = True
        criteria["leakage_analysis_format"] = {
            "passed": la_ok,
            "score": c1_max if la_ok else 0,
            "max_score": c1_max,
            "reason": "" if la_ok else "leakage_analysis.csv missing or wrong columns",
        }

        # ── Criterion 2: Correct number of flagged distributors (15 pts)
        c2_max = 15
        max_score += c2_max
        c2_ok = la_ok and len(la_rows) == len(results)
        criteria["flagged_count"] = {
            "passed": c2_ok,
            "score": c2_max if c2_ok else 0,
            "max_score": c2_max,
            "reason": "" if c2_ok else f"Expected {len(results)} rows, got {len(la_rows)}",
        }

        # ── Criterion 3: Leakage amounts accuracy (20 pts)
        c3_max = 20
        max_score += c3_max
        gt_map = {r["partner_id"]: r for r in results}
        correct_leakage = 0
        for row in la_rows:
            try:
                pid = int(row["partner_id"])
                gt = gt_map.get(pid)
                if gt is None:
                    continue
                la_val = float(row["leakage_amount"])
                if abs(la_val - gt["leakage_amount"]) < max(1.0, gt["leakage_amount"] * 0.02):
                    correct_leakage += 1
            except (ValueError, KeyError):
                continue
        if len(results) > 0:
            c3_score = round(c3_max * correct_leakage / len(results))
        else:
            c3_score = c3_max
        criteria["leakage_accuracy"] = {
            "passed": c3_score == c3_max,
            "score": c3_score,
            "max_score": c3_max,
            "reason": "" if c3_score == c3_max else f"{correct_leakage}/{len(results)} accurate",
        }

        # ── Criterion 4: Risk scores accuracy (15 pts)
        c4_max = 15
        max_score += c4_max
        correct_risk = 0
        for row in la_rows:
            try:
                pid = int(row["partner_id"])
                gt = gt_map.get(pid)
                if gt is None:
                    continue
                rs = float(row["risk_score"])
                if abs(rs - gt["risk_score"]) < max(0.5, gt["risk_score"] * 0.03):
                    correct_risk += 1
            except (ValueError, KeyError):
                continue
        if len(results) > 0:
            c4_score = round(c4_max * correct_risk / len(results))
        else:
            c4_score = c4_max
        criteria["risk_score_accuracy"] = {
            "passed": c4_score == c4_max,
            "score": c4_score,
            "max_score": c4_max,
            "reason": "" if c4_score == c4_max else f"{correct_risk}/{len(results)} accurate",
        }

        # ── Criterion 5: Sort order (10 pts)
        c5_max = 10
        max_score += c5_max
        c5_ok = False
        if la_rows and la_ok:
            try:
                la_sorted = all(
                    (float(la_rows[i]["risk_score"]) > float(la_rows[i + 1]["risk_score"])
                     or (float(la_rows[i]["risk_score"]) == float(la_rows[i + 1]["risk_score"])
                         and int(la_rows[i]["partner_id"]) <= int(la_rows[i + 1]["partner_id"])))
                    for i in range(len(la_rows) - 1)
                )
                c5_ok = la_sorted
            except (ValueError, KeyError):
                pass
        criteria["sort_order"] = {
            "passed": c5_ok,
            "score": c5_max if c5_ok else 0,
            "max_score": c5_max,
            "reason": "" if c5_ok else "Rows not sorted by risk_score DESC, partner_id ASC",
        }

        # ── Criterion 6: high_risk_summary.csv (15 pts)
        c6_max = 15
        max_score += c6_max
        hr_path = os.path.join(self.workspace, "high_risk_summary.csv")
        c6_ok = False
        if os.path.exists(hr_path):
            with open(hr_path) as f:
                reader = csv.DictReader(f)
                hr_rows = list(reader)
            hr_cols = ["partner_id", "partner_name", "risk_score",
                       "risk_category", "primary_risk_factor"]
            if reader.fieldnames and all(c in reader.fieldnames for c in hr_cols):
                if len(hr_rows) == len(high_risk):
                    hr_ids = set()
                    try:
                        hr_ids = {int(r["partner_id"]) for r in hr_rows}
                    except (ValueError, KeyError):
                        pass
                    gt_ids = {r["partner_id"] for r in high_risk}
                    if hr_ids == gt_ids:
                        c6_ok = True
        criteria["high_risk_summary"] = {
            "passed": c6_ok,
            "score": c6_max if c6_ok else 0,
            "max_score": c6_max,
            "reason": "" if c6_ok else "high_risk_summary.csv missing, wrong columns, or wrong partners",
        }

        # ── Criterion 7: Response contains high-risk partner count + names (10 pts)
        c7_max = 10
        max_score += c7_max
        c7_score = 0
        if action:
            # Check count
            count_str = str(len(high_risk))
            if count_str in action:
                c7_score += 5
            # Check at least half of partner names mentioned
            names_found = sum(
                1 for r in high_risk if r["partner_name"] in action
            )
            if len(high_risk) > 0 and names_found >= len(high_risk) // 2:
                c7_score += 5
            elif len(high_risk) == 0:
                c7_score += 5
        criteria["response_summary"] = {
            "passed": c7_score == c7_max,
            "score": c7_score,
            "max_score": c7_max,
            "reason": "" if c7_score == c7_max else "Response missing count or partner names",
        }

        total = sum(c["score"] for c in criteria.values())
        return total / max_score, {
            "eval_criteria": criteria,
            "total_score": total,
            "max_score": max_score,
        }

    # ── Verify ─────────────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import math

        # ── 1. Read workspace config files ──
        with open(os.path.join(self.workspace, "territory_modifiers.yaml")) as f:
            t_mods = yaml.safe_load(f)["territory_modifiers"]
        with open(os.path.join(self.workspace, "risk_scoring_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "compliance_config.json")) as f:
            comp = json.load(f)

        fy_start = comp["fiscal_year_start"]
        fy_end = comp["fiscal_year_end"]
        thresh_amt = comp["leakage_threshold_amount"]
        thresh_pct = comp["leakage_threshold_pct"]
        weights = policy["scoring_weights"]
        sev_pts = policy["severity_points"]
        risk_cats = policy["risk_categories"]
        norm = policy["normalization"]

        # ── 2. Read verification reports ──
        verif = {}
        for fn in os.listdir(self.workspace):
            if fn.startswith("verification_report_") and fn.endswith(".csv"):
                with open(os.path.join(self.workspace, fn)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        verif[row["invoice_number"]] = int(row["verified_quantity"])

        # ── 3. List all active distributors via tool ──
        all_dists = []
        page = 1
        while True:
            res = self.tools["list_distributors"](status="active", page=page, page_size=20)
            all_dists.extend(res["distributors"])
            if page * 20 >= res["total"]:
                break
            page += 1

        # ── 4. For each distributor gather data via tools ──
        sku_cache = {}  # sku_id -> details
        dist_results = []

        for dist in all_dists:
            did = dist["id"]

            # Get agreements
            agr_res = self.tools["get_agreements_for_distributor"](distributor_id=did)
            agreements = agr_res["agreements"]

            # Build agreement index for this distributor
            agr_idx = {}
            for a in agreements:
                key = (a["territory_code"], a["product_category"])
                agr_idx.setdefault(key, []).append(a)

            def best_agr(terr, cat, ship_dt):
                for a in agr_idx.get((terr, cat), []):
                    if (a["status"] == "active"
                            and a["effective_date"] <= ship_dt <= a["expiry_date"]):
                        return a
                return None

            # Get all shipments
            all_ships = []
            sp = 1
            while True:
                sr = self.tools["get_shipment_records"](
                    distributor_id=did, page=sp, page_size=50
                )
                all_ships.extend(sr["shipments"])
                if sp * 50 >= sr["total"]:
                    break
                sp += 1

            # Filter to fiscal year
            fy_ships = [
                s for s in all_ships
                if fy_start <= s["ship_date"] <= fy_end
            ]

            total_expected = 0.0
            total_reported = 0.0
            qty_disc = 0
            cat_volumes = {}  # (territory, category) -> qty

            for s in fy_ships:
                sku_id = s["sku_id"]
                if sku_id not in sku_cache:
                    sku_cache[sku_id] = self.tools["get_sku_by_id"](sku_id=sku_id)
                sku = sku_cache[sku_id]

                terr = s["territory_code"]
                t_mod = t_mods.get(terr, 1.0)
                agr = best_agr(terr, sku["category"], s["ship_date"])
                discount = agr["royalty_discount_pct"] / 100.0 if agr else 0.0

                qty = s["quantity"]
                vq = verif.get(s["invoice_number"])
                use_qty = vq if (vq is not None and vq > qty) else qty

                expected = use_qty * sku["unit_price"] * sku["base_royalty_pct"] * t_mod * (1 - discount)
                total_expected += expected
                total_reported += s["reported_royalty"]

                if vq is not None and vq != qty:
                    qty_disc += 1

                ck = (terr, sku["category"])
                cat_volumes[ck] = cat_volumes.get(ck, 0) + qty

            leakage = max(0.0, total_expected - total_reported)
            leak_pct = leakage / total_expected if total_expected > 0 else 0.0

            if leakage < thresh_amt and leak_pct < thresh_pct:
                continue

            # Volume gap
            gaps = []
            for a in agreements:
                if a["status"] != "active":
                    continue
                if a["expiry_date"] < fy_start or a["effective_date"] > fy_end:
                    continue
                ck = (a["territory_code"], a["product_category"])
                actual = cat_volumes.get(ck, 0)
                committed = a["min_annual_volume"]
                if committed > 0 and actual < committed:
                    gaps.append((committed - actual) / committed)
            avg_vol_gap = (sum(gaps) / len(gaps)) if gaps else 0.0

            # Audit exceptions
            exc_res = self.tools["get_audit_exceptions"](distributor_id=did)
            unresolved_sevs = [
                e["severity"] for e in exc_res["exceptions"] if not e["resolved"]
            ]
            if unresolved_sevs:
                s_audit = sum(sev_pts.get(s, 0) for s in unresolved_sevs) / len(unresolved_sevs)
            else:
                s_audit = 0.0

            # Risk score components
            s_leak_amt = min(leakage / norm["max_leakage_amount"] * 100, 100)
            s_leak_pct = min(leak_pct / norm["max_leakage_pct"] * 100, 100)
            s_vol = min(avg_vol_gap / norm["max_volume_gap_pct"] * 100, 100)
            s_qd = min(qty_disc / norm["max_quantity_discrepancies"] * 100, 100)

            risk_score = (
                weights["leakage_amount"] * s_leak_amt
                + weights["leakage_percentage"] * s_leak_pct
                + weights["audit_severity"] * s_audit
                + weights["volume_gap"] * s_vol
                + weights["quantity_discrepancy"] * s_qd
            )

            cat = "Low"
            for cat_name in ["critical", "high", "medium", "low"]:
                if risk_score >= risk_cats[cat_name]:
                    cat = cat_name.capitalize()
                    break

            components = {
                "leakage_amount": weights["leakage_amount"] * s_leak_amt,
                "leakage_percentage": weights["leakage_percentage"] * s_leak_pct,
                "audit_severity": weights["audit_severity"] * s_audit,
                "volume_gap": weights["volume_gap"] * s_vol,
                "quantity_discrepancy": weights["quantity_discrepancy"] * s_qd,
            }
            primary = max(components, key=components.get)

            dist_results.append({
                "partner_id": did,
                "partner_name": dist["name"],
                "territory": dist["territory_code"],
                "total_expected_royalty": round(total_expected, 2),
                "total_reported_royalty": round(total_reported, 2),
                "leakage_amount": round(leakage, 2),
                "leakage_pct": round(leak_pct, 4),
                "quantity_discrepancies": qty_disc,
                "risk_score": round(risk_score, 2),
                "risk_category": cat,
                "primary_risk_factor": primary,
            })

        dist_results.sort(key=lambda x: (-x["risk_score"], x["partner_id"]))

        # ── Write leakage_analysis.csv ──
        la_path = os.path.join(self.workspace, "leakage_analysis.csv")
        la_cols = [
            "partner_id", "partner_name", "territory",
            "total_expected_royalty", "total_reported_royalty",
            "leakage_amount", "leakage_pct", "quantity_discrepancies",
            "risk_score", "risk_category",
        ]
        with open(la_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=la_cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(dist_results)

        # ── Write high_risk_summary.csv ──
        high_risk = [r for r in dist_results if r["risk_category"] in ("Critical", "High")]
        hr_path = os.path.join(self.workspace, "high_risk_summary.csv")
        hr_cols = ["partner_id", "partner_name", "risk_score",
                   "risk_category", "primary_risk_factor"]
        with open(hr_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=hr_cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(high_risk)

        # ── Build action string ──
        lines = [f"Licensing Revenue Leakage Analysis Complete."]
        lines.append(f"Total partners flagged above threshold: {len(dist_results)}")
        lines.append(f"High-risk partners (Critical or High): {len(high_risk)}")
        lines.append("")
        for r in high_risk:
            lines.append(
                f"- {r['partner_name']} (ID {r['partner_id']}): "
                f"risk_score={r['risk_score']}, category={r['risk_category']}, "
                f"leakage=${r['leakage_amount']:.2f}"
            )
        action = "\n".join(lines)

        return self.step(action)
