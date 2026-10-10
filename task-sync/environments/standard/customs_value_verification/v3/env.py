import sqlite3
import os
import re
import csv
import json
import glob
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

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    @tool(
        description="Returns the total number of invoices in the database.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def count_invoices(self) -> int:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM invoices")
        count = c.fetchone()[0]
        conn.close()
        return count

    @tool(
        description="Returns a paginated list of invoice IDs sorted alphabetically.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of invoice IDs per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_invoice_ids(self, page: int, page_size: int) -> dict:
        page_size = min(int(page_size), 50)
        page = int(page)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM invoices")
        total = c.fetchone()[0]
        c.execute(
            "SELECT invoice_id FROM invoices ORDER BY invoice_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        ids = [row[0] for row in c.fetchall()]
        conn.close()
        total_pages = (total + page_size - 1) // page_size
        return {
            "invoice_ids": ids,
            "total": total,
            "page": page,
            "total_pages": total_pages,
        }

    @tool(
        description="Retrieves full details for a specific invoice by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "The invoice ID, e.g. INV-0001.",
                },
            },
            "required": ["invoice_id"],
        },
    )
    def get_invoice(self, invoice_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Invoice {invoice_id} not found"}
        return dict(row)

    @tool(
        description="Retrieves product details by product ID, including HS code and category.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID, e.g. P0001.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_product(self, product_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Product {product_id} not found"}
        return dict(row)

    @tool(
        description="Retrieves shipment details (port of entry and trade term) for a given invoice.",
        parameters={
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "The invoice ID to look up.",
                },
            },
            "required": ["invoice_id"],
        },
    )
    def get_shipment(self, invoice_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM shipments WHERE invoice_id = ?", (invoice_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Shipment for invoice {invoice_id} not found"}
        return dict(row)

    @tool(
        description="Retrieves supplier details by supplier ID.",
        parameters={
            "type": "object",
            "properties": {
                "supplier_id": {
                    "type": "string",
                    "description": "The supplier ID, e.g. S0001.",
                },
            },
            "required": ["supplier_id"],
        },
    )
    def get_supplier(self, supplier_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM suppliers WHERE supplier_id = ?", (supplier_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Supplier {supplier_id} not found"}
        return dict(row)

    # ------------------------------------------------------------------
    # Ground-truth helper (used by step; may access DB directly)
    # ------------------------------------------------------------------

    def _compute_ground_truth(self):
        """Compute the ground-truth list of flagged entries."""
        # --- workspace files ---
        exchange_rates = {}
        with open(os.path.join(self.workspace, "exchange_rates.csv")) as f:
            for row in csv.DictReader(f):
                exchange_rates[row["currency_code"]] = float(row["rate_to_usd"])

        benchmarks = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "market_benchmarks_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
                for hs_code, info in data.items():
                    benchmarks[hs_code] = info["benchmark_unit_price_usd"]

        freight_data = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "freight_insurance_ledger_*.csv"))):
            with open(fpath) as f:
                for row in csv.DictReader(f):
                    freight_data[row["invoice_id"]] = {
                        "freight": float(row["freight_cost_usd"]),
                        "insurance": float(row["insurance_cost_usd"]),
                    }

        supp_data = {}
        for fpath in sorted(glob.glob(os.path.join(self.workspace, "invoice_supplements_*.csv"))):
            with open(fpath) as f:
                for row in csv.DictReader(f):
                    supp_data[row["invoice_id"]] = {
                        "packaging": float(row["packaging_cost_usd"]),
                        "handling": float(row["handling_cost_usd"]),
                    }

        with open(os.path.join(self.workspace, "port_surcharges.yaml")) as f:
            surcharges = yaml.safe_load(f)

        # --- database ---
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        invoices = [dict(r) for r in conn.execute("SELECT * FROM invoices").fetchall()]
        products = {
            r["product_id"]: dict(r)
            for r in conn.execute("SELECT * FROM products").fetchall()
        }
        ship_map = {
            r["invoice_id"]: dict(r)
            for r in conn.execute("SELECT * FROM shipments").fetchall()
        }
        suppliers = {
            r["supplier_id"]: dict(r)
            for r in conn.execute("SELECT * FROM suppliers").fetchall()
        }
        conn.close()

        flagged = []
        for inv in invoices:
            inv_id = inv["invoice_id"]
            product = products[inv["product_id"]]
            ship = ship_map[inv_id]
            hs_code = product["hs_code"]
            benchmark = benchmarks.get(hs_code)
            if benchmark is None:
                continue

            rate = exchange_rates[inv["currency"]]
            declared_usd = inv["declared_unit_value"] * rate * inv["quantity"]

            incoterm = ship["incoterm"]
            fr = freight_data.get(inv_id, {"freight": 0, "insurance": 0})
            freight = fr["freight"]
            insurance = fr["insurance"]

            if incoterm in ("FOB", "EXW"):
                freight_adj = freight
                insurance_adj = insurance
            elif incoterm == "CFR":
                freight_adj = 0
                insurance_adj = insurance
            else:
                freight_adj = 0
                insurance_adj = 0

            surcharge_rate = surcharges.get(ship["port_of_entry"], 0)
            surcharge_amount = freight * surcharge_rate

            supp = supp_data.get(inv_id, {"packaging": 0, "handling": 0})

            total_cif = (
                declared_usd
                + freight_adj
                + insurance_adj
                + surcharge_amount
                + supp["packaging"]
                + supp["handling"]
            )
            cif_per_unit = total_cif / inv["quantity"]

            disc_pct = (benchmark - cif_per_unit) / benchmark * 100

            if disc_pct > 10.0:
                if disc_pct > 35.0:
                    risk = "Critical"
                elif disc_pct > 20.0:
                    risk = "High"
                else:
                    risk = "Medium"

                supplier = suppliers[inv["supplier_id"]]
                flagged.append({
                    "invoice_id": inv_id,
                    "supplier_name": supplier["supplier_name"],
                    "product_name": product["product_name"],
                    "hs_code": hs_code,
                    "declared_cif_usd": round(cif_per_unit, 2),
                    "benchmark_usd": round(benchmark, 2),
                    "discrepancy_pct": round(disc_pct, 2),
                    "risk_level": risk,
                    "quantity": inv["quantity"],
                })

        flagged.sort(key=lambda x: (-x["discrepancy_pct"], x["invoice_id"]))
        return flagged

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

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
        ground_truth = self._compute_ground_truth()
        gt_ids = set(e["invoice_id"] for e in ground_truth)
        gt_map = {e["invoice_id"]: e for e in ground_truth}

        total_underpayment_gt = round(
            sum(
                (e["benchmark_usd"] - e["declared_cif_usd"]) * e["quantity"]
                for e in ground_truth
            ),
            2,
        )

        risk_breakdown_gt = {}
        for e in ground_truth:
            risk_breakdown_gt[e["risk_level"]] = (
                risk_breakdown_gt.get(e["risk_level"], 0) + 1
            )

        criteria = {}

        # --- Criterion 1: report file exists (10 pts) ---
        report_path = os.path.join(self.workspace, "discrepancy_report.csv")
        if not os.path.exists(report_path):
            criteria["report_exists"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "discrepancy_report.csv not found",
            }
            return 0.0, {
                "eval_criteria": criteria,
                "total_score": 0,
                "max_score": 100,
            }

        try:
            with open(report_path) as f:
                agent_rows = list(csv.DictReader(f))
        except Exception as e:
            criteria["report_exists"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": f"Failed to read report: {e}",
            }
            return 0.0, {
                "eval_criteria": criteria,
                "total_score": 0,
                "max_score": 100,
            }

        criteria["report_exists"] = {"passed": True, "score": 10, "max_score": 10}

        # --- Criterion 2: correct flagged invoice IDs (25 pts) ---
        agent_ids = set(r.get("invoice_id", "").strip() for r in agent_rows)
        correct_ids = gt_ids & agent_ids
        missing_ids = gt_ids - agent_ids
        extra_ids = agent_ids - gt_ids

        if agent_ids == gt_ids:
            criteria["correct_invoice_ids"] = {
                "passed": True,
                "score": 25,
                "max_score": 25,
            }
        else:
            if len(gt_ids) > 0 and len(agent_ids) > 0:
                recall = len(correct_ids) / len(gt_ids)
                precision = len(correct_ids) / len(agent_ids)
                f1 = (
                    2 * recall * precision / (recall + precision)
                    if (recall + precision) > 0
                    else 0
                )
                score = round(25 * f1)
            else:
                score = 0 if len(gt_ids) > 0 else 25
            criteria["correct_invoice_ids"] = {
                "passed": False,
                "score": score,
                "max_score": 25,
                "reason": f"Missing {len(missing_ids)}, extra {len(extra_ids)} of {len(gt_ids)} expected",
            }

        # --- Criterion 3: correct CIF values (15 pts) ---
        agent_map = {
            r["invoice_id"].strip(): r
            for r in agent_rows
            if r.get("invoice_id", "").strip() in gt_ids
        }
        cif_correct = 0
        cif_total = len(ground_truth)
        for e in ground_truth:
            if e["invoice_id"] in agent_map:
                try:
                    agent_cif = float(agent_map[e["invoice_id"]].get("declared_cif_usd", 0))
                    if abs(agent_cif - e["declared_cif_usd"]) < 0.02:
                        cif_correct += 1
                except (ValueError, TypeError):
                    pass

        cif_score = round(15 * cif_correct / cif_total) if cif_total > 0 else 15
        criteria["correct_cif_values"] = {
            "passed": cif_score == 15,
            "score": cif_score,
            "max_score": 15,
            "reason": "" if cif_score == 15 else f"{cif_correct}/{cif_total} correct",
        }

        # --- Criterion 4: correct discrepancy percentages (15 pts) ---
        disc_correct = 0
        for e in ground_truth:
            if e["invoice_id"] in agent_map:
                try:
                    agent_disc = float(
                        agent_map[e["invoice_id"]].get("discrepancy_pct", 0)
                    )
                    if abs(agent_disc - e["discrepancy_pct"]) < 0.05:
                        disc_correct += 1
                except (ValueError, TypeError):
                    pass

        disc_score = round(15 * disc_correct / cif_total) if cif_total > 0 else 15
        criteria["correct_discrepancy_pct"] = {
            "passed": disc_score == 15,
            "score": disc_score,
            "max_score": 15,
            "reason": "" if disc_score == 15 else f"{disc_correct}/{cif_total} correct",
        }

        # --- Criterion 5: correct risk classifications (15 pts) ---
        risk_correct = 0
        for e in ground_truth:
            if e["invoice_id"] in agent_map:
                if (
                    agent_map[e["invoice_id"]].get("risk_level", "").strip()
                    == e["risk_level"]
                ):
                    risk_correct += 1

        risk_score = round(15 * risk_correct / cif_total) if cif_total > 0 else 15
        criteria["correct_risk_levels"] = {
            "passed": risk_score == 15,
            "score": risk_score,
            "max_score": 15,
            "reason": "" if risk_score == 15 else f"{risk_correct}/{cif_total} correct",
        }

        # --- Criterion 6: correct sort order (10 pts) ---
        if len(agent_rows) > 0:
            agent_order = [
                r.get("invoice_id", "").strip()
                for r in agent_rows
                if r.get("invoice_id", "").strip() in gt_ids
            ]
            gt_order = [
                e["invoice_id"]
                for e in ground_truth
                if e["invoice_id"] in agent_ids
            ]
            if agent_order == gt_order:
                criteria["correct_sort_order"] = {
                    "passed": True,
                    "score": 10,
                    "max_score": 10,
                }
            else:
                criteria["correct_sort_order"] = {
                    "passed": False,
                    "score": 0,
                    "max_score": 10,
                    "reason": "Rows not sorted by discrepancy_pct desc / invoice_id asc",
                }
        else:
            criteria["correct_sort_order"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "No rows in report",
            }

        # --- Criterion 7: response summary accuracy (10 pts) ---
        response_score = 0

        expected_count = str(len(ground_truth))
        count_pattern = r"\b" + re.escape(expected_count) + r"\b"
        if re.search(count_pattern, action):
            response_score += 5

        numbers = re.findall(r"[\d]+\.?\d*", action.replace(",", ""))
        amount_found = False
        # Tolerance accounts for rounding-error compounding when an agent computes
        # underpayment from unrounded vs. 2dp-rounded intermediates across many entries,
        # plus a small relative slack to scale with magnitude.
        amount_tol = max(1.0, 0.05 * len(ground_truth), 0.001 * abs(total_underpayment_gt))
        for num_str in numbers:
            try:
                num = float(num_str)
                if abs(num - total_underpayment_gt) <= amount_tol:
                    amount_found = True
                    break
            except ValueError:
                continue
        if amount_found:
            response_score += 5

        criteria["response_summary"] = {
            "passed": response_score == 10,
            "score": response_score,
            "max_score": 10,
            "reason": (
                ""
                if response_score == 10
                else f"Count match: {bool(re.search(count_pattern, action))}, Amount match: {amount_found}"
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ------------------------------------------------------------------
    # Self-verification
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
        # ----- Step 1: read workspace reference files -----
        exchange_rates = {}
        with open(os.path.join(self.workspace, "exchange_rates.csv")) as f:
            for row in csv.DictReader(f):
                exchange_rates[row["currency_code"]] = float(row["rate_to_usd"])

        benchmarks = {}
        for fpath in sorted(
            glob.glob(os.path.join(self.workspace, "market_benchmarks_*.json"))
        ):
            with open(fpath) as f:
                data = json.load(f)
                for hs_code, info in data.items():
                    benchmarks[hs_code] = info["benchmark_unit_price_usd"]

        freight_data = {}
        for fpath in sorted(
            glob.glob(os.path.join(self.workspace, "freight_insurance_ledger_*.csv"))
        ):
            with open(fpath) as f:
                for row in csv.DictReader(f):
                    freight_data[row["invoice_id"]] = {
                        "freight": float(row["freight_cost_usd"]),
                        "insurance": float(row["insurance_cost_usd"]),
                    }

        supp_data = {}
        for fpath in sorted(
            glob.glob(os.path.join(self.workspace, "invoice_supplements_*.csv"))
        ):
            with open(fpath) as f:
                for row in csv.DictReader(f):
                    supp_data[row["invoice_id"]] = {
                        "packaging": float(row["packaging_cost_usd"]),
                        "handling": float(row["handling_cost_usd"]),
                    }

        with open(os.path.join(self.workspace, "port_surcharges.yaml")) as f:
            surcharges = yaml.safe_load(f)

        # Read policy + incoterm reference (an agent would read these to learn rules)
        with open(os.path.join(self.workspace, "customs_valuation_policy.md")) as f:
            _ = f.read()
        with open(os.path.join(self.workspace, "incoterm_reference.yaml")) as f:
            incoterm_ref = yaml.safe_load(f)

        # ----- Step 2: gather all invoice IDs via tools -----
        total_count = self.tools["count_invoices"]()
        page_size = 20
        all_ids = []
        page = 1
        while len(all_ids) < total_count:
            result = self.tools["list_invoice_ids"](page=page, page_size=page_size)
            all_ids.extend(result["invoice_ids"])
            if page >= result["total_pages"]:
                break
            page += 1

        # ----- Step 3: process every invoice -----
        product_cache = {}
        supplier_cache = {}
        flagged = []

        for inv_id in all_ids:
            inv = self.tools["get_invoice"](invoice_id=inv_id)

            # product (cached)
            prod_id = inv["product_id"]
            if prod_id not in product_cache:
                product_cache[prod_id] = self.tools["get_product"](product_id=prod_id)
            product = product_cache[prod_id]

            # shipment
            ship = self.tools["get_shipment"](invoice_id=inv_id)

            # currency conversion
            rate = exchange_rates[inv["currency"]]
            declared_usd = inv["declared_unit_value"] * rate * inv["quantity"]

            # incoterm-based adjustments
            incoterm = ship["incoterm"]
            inc_ref = incoterm_ref.get(incoterm, {})
            fr = freight_data.get(inv_id, {"freight": 0, "insurance": 0})
            freight = fr["freight"]
            insurance = fr["insurance"]

            freight_adj = freight if inc_ref.get("add_freight", False) else 0
            insurance_adj = insurance if inc_ref.get("add_insurance", False) else 0

            # port surcharge
            surcharge_rate = surcharges.get(ship["port_of_entry"], 0)
            surcharge_amount = freight * surcharge_rate

            # supplements
            supp = supp_data.get(inv_id, {"packaging": 0, "handling": 0})

            # adjusted CIF per unit
            total_cif = (
                declared_usd
                + freight_adj
                + insurance_adj
                + surcharge_amount
                + supp["packaging"]
                + supp["handling"]
            )
            cif_per_unit = total_cif / inv["quantity"]

            # benchmark comparison
            hs_code = product["hs_code"]
            benchmark = benchmarks.get(hs_code)
            if benchmark is None:
                continue

            disc_pct = (benchmark - cif_per_unit) / benchmark * 100

            if disc_pct > 10.0:
                if disc_pct > 35.0:
                    risk = "Critical"
                elif disc_pct > 20.0:
                    risk = "High"
                else:
                    risk = "Medium"

                sup_id = inv["supplier_id"]
                if sup_id not in supplier_cache:
                    supplier_cache[sup_id] = self.tools["get_supplier"](
                        supplier_id=sup_id
                    )
                supplier = supplier_cache[sup_id]

                flagged.append({
                    "invoice_id": inv_id,
                    "supplier_name": supplier["supplier_name"],
                    "product_name": product["product_name"],
                    "hs_code": hs_code,
                    "declared_cif_usd": round(cif_per_unit, 2),
                    "benchmark_usd": round(benchmark, 2),
                    "discrepancy_pct": round(disc_pct, 2),
                    "risk_level": risk,
                    "quantity": inv["quantity"],
                })

        # ----- Step 4: sort and write deliverables -----
        flagged.sort(key=lambda x: (-x["discrepancy_pct"], x["invoice_id"]))

        report_path = os.path.join(self.workspace, "discrepancy_report.csv")
        fieldnames = [
            "invoice_id",
            "supplier_name",
            "product_name",
            "hs_code",
            "declared_cif_usd",
            "benchmark_usd",
            "discrepancy_pct",
            "risk_level",
        ]
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in flagged:
                writer.writerow({k: entry[k] for k in fieldnames})

        # ----- Step 5: build summary action string -----
        total_flagged = len(flagged)
        total_underpayment = round(
            sum(
                (e["benchmark_usd"] - e["declared_cif_usd"]) * e["quantity"]
                for e in flagged
            ),
            2,
        )

        risk_breakdown = {}
        for e in flagged:
            risk_breakdown[e["risk_level"]] = (
                risk_breakdown.get(e["risk_level"], 0) + 1
            )

        action = f"Total flagged entries: {total_flagged}\n"
        action += f"Total estimated underpayment: ${total_underpayment}\n"
        action += "Risk breakdown:\n"
        for level in ["Critical", "High", "Medium"]:
            count = risk_breakdown.get(level, 0)
            if count > 0:
                action += f"  {level}: {count}\n"

        return self.step(action)
