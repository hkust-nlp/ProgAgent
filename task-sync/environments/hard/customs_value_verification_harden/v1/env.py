"""
Customs Value Verification - Task Environment (hardened tool surface)

Provides tools for querying customs invoice/shipment data and evaluates
the agent's discrepancy report output.

Hardened surface (M2 + M3): tools return a mix of shapes — deeply nested
record objects, JSON-encoded strings, MCP-style envelopes, plain key:value
text, and Python-repr strings. Error responses use a different object shape
than success responses. Task semantics, data, and scoring are unchanged
from the base environment.
"""

import ast
import csv
import glob
import hashlib
import json
import os
import re
import sqlite3
import yaml
from typing import Any, Dict, List, Tuple


def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ─── Hardened tool-surface helpers ───

def _request_id(message: str) -> str:
    return "req_" + hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def _error(status: int, code: str, message: str) -> dict:
    """Error responses share NO keys with success responses."""
    return {
        "status": status,
        "object": "error",
        "code": code,
        "message": message,
        "request_id": _request_id(f"{status}:{code}:{message}"),
    }


def _envelope(payload) -> dict:
    """MCP-style envelope: payload is JSON-encoded into a text content block."""
    return {
        "meta": None,
        "content": [
            {"type": "text",
             "text": json.dumps(payload, ensure_ascii=False, default=str)}
        ],
        "isError": False,
    }


def _shape(value) -> str:
    """Short rendering of a wrong-typed value for error text."""
    if value is None:
        return "'undefined'"
    r = repr(value)
    if len(r) > 60:
        r = r[:57] + "..."
    return f"'{r}'"


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _number(value):
    return {"type": "number", "number": value}


def _title(text):
    return {"type": "title", "title": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [
        {"type": "text", "text": {"content": text, "link": None}, "plain_text": text}]}


def _relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


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
    def count_invoices(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM invoices")
        count = c.fetchone()[0]
        conn.close()
        return {"object": "count", "count": count}

    @tool(
        description="Returns a paginated list of invoice records sorted alphabetically by invoice ID.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of invoices per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_invoice_ids(self, page: Any = None, page_size: Any = None) -> dict:
        try:
            page = int(page)
            page_size = int(page_size)
        except (TypeError, ValueError):
            return _error(
                400, "validation_error",
                f"body.page and body.page_size should be integers, instead were "
                f"{_shape(page)} and {_shape(page_size)}.",
            )
        if page < 1 or page_size < 1:
            return _error(
                400, "validation_error",
                "body.page and body.page_size should be positive integers.",
            )
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM invoices")
        total = c.fetchone()[0]
        c.execute(
            "SELECT invoice_id FROM invoices ORDER BY invoice_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = c.fetchall()
        conn.close()
        results = [{"object": "invoice", "id": r[0]} for r in rows]
        has_more = offset + len(rows) < total
        return {
            "object": "list",
            "results": results,
            "has_more": has_more,
            "next_cursor": page + 1 if has_more else None,
        }

    @tool(
        description=(
            "Retrieves the full declaration record for a specific invoice: declared "
            "unit value, currency, quantity, invoice date, and the linked supplier "
            "and product."
        ),
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
    def get_invoice(self, invoice_id: Any = None) -> str:
        if not isinstance(invoice_id, str) or not invoice_id:
            return json.dumps(_error(
                400, "validation_error",
                f"body.invoice_id should be a non-empty string, instead was {_shape(invoice_id)}.",
            ))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return json.dumps(_error(
                404, "object_not_found",
                f"Could not find invoice with ID: {invoice_id}.",
            ))
        payload = {
            "object": "invoice",
            "id": row["invoice_id"],
            "properties": {
                "Invoice ID": _title(row["invoice_id"]),
                "Supplier": _relation(row["supplier_id"]),
                "Product": _relation(row["product_id"]),
                "Declared Unit Value": _number(row["declared_unit_value"]),
                "Currency": _select(row["currency"]),
                "Quantity": _number(row["quantity"]),
                "Invoice Date": {
                    "type": "date",
                    "date": {"start": row["invoice_date"], "end": None},
                },
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @tool(
        description=(
            "Retrieves the catalog record for a specific product: name, harmonized "
            "system code, category, and unit of measure."
        ),
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
    def get_product(self, product_id: Any = None) -> Any:
        if not isinstance(product_id, str) or not product_id:
            return _error(
                400, "validation_error",
                f"body.product_id should be a non-empty string, instead was {_shape(product_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find product with ID: {product_id}.",
            )
        payload = {
            "object": "product",
            "id": row["product_id"],
            "properties": {
                "Product Name": _title(row["product_name"]),
                "HS Code": _rich_text(row["hs_code"]),
                "Category": _select(row["category"]),
                "Unit of Measure": _select(row["unit_of_measure"]),
            },
        }
        return repr(payload)

    @tool(
        description=(
            "Retrieves the shipment record linked to a given invoice: port of entry "
            "and trade term."
        ),
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
    def get_shipment(self, invoice_id: Any = None) -> Any:
        if not isinstance(invoice_id, str) or not invoice_id:
            return _error(
                400, "validation_error",
                f"body.invoice_id should be a non-empty string, instead was {_shape(invoice_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM shipments WHERE invoice_id = ?", (invoice_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find shipment for invoice with ID: {invoice_id}.",
            )
        payload = {
            "shipment_id": row["shipment_id"],
            "invoice_id": row["invoice_id"],
            "port_of_entry": row["port_of_entry"],
            "incoterm": row["incoterm"],
        }
        return _envelope(payload)

    @tool(
        description=(
            "Retrieves the registration record for a specific supplier: company "
            "name, country, and registration number."
        ),
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
    def get_supplier(self, supplier_id: Any = None) -> Any:
        if not isinstance(supplier_id, str) or not supplier_id:
            return _error(
                400, "validation_error",
                f"body.supplier_id should be a non-empty string, instead was {_shape(supplier_id)}.",
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM suppliers WHERE supplier_id = ?", (supplier_id,))
        row = c.fetchone()
        conn.close()
        if row is None:
            return _error(
                404, "object_not_found",
                f"Could not find supplier with ID: {supplier_id}.",
            )
        fields = {
            "supplier_id": row["supplier_id"],
            "supplier_name": row["supplier_name"],
            "country": row["country"],
            "registration_number": row["registration_number"],
        }
        return "\n".join(f"{k}: {v}" for k, v in fields.items())

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

        # Sub-check A: total flagged count (4 pts)
        expected_count = str(len(ground_truth))
        count_pattern = r"\b" + re.escape(expected_count) + r"\b"
        count_found = bool(re.search(count_pattern, action))
        if count_found:
            response_score += 4

        # Sub-check B: total underpayment amount (4 pts)
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
            response_score += 4

        # Sub-check C: per-risk-tier counts (2 pts)
        # prompt.md requires "a count of entries in each risk tier"
        tier_counts_found = True
        for tier, tier_count in risk_breakdown_gt.items():
            tier_pattern = r"\b" + re.escape(str(tier_count)) + r"\b"
            if not re.search(tier_pattern, action):
                tier_counts_found = False
                break
        if tier_counts_found:
            response_score += 2

        criteria["response_summary"] = {
            "passed": response_score == 10,
            "score": response_score,
            "max_score": 10,
            "reason": (
                ""
                if response_score == 10
                else f"Count match: {count_found}, Amount match: {amount_found}, Tier counts match: {tier_counts_found}"
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

        Note: the hardened tool surface returns mixed shapes, so this solver
        unwraps envelopes, parses JSON strings / repr strings / key:value
        text, walks nested property objects, and follows cursor pagination.
        """
        tool_calls = 0

        def call_tool(name, **kwargs):
            nonlocal tool_calls
            tool_calls += 1
            return self.tools[name](**kwargs)

        def unwrap_envelope(resp):
            return json.loads(resp["content"][0]["text"])

        def parse_kv_text(text):
            out = {}
            for line in text.splitlines():
                k, _, v = line.partition(": ")
                out[k] = v
            return out

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
        # count_invoices returns a native dict
        total_count = call_tool("count_invoices")["count"]

        # list_invoice_ids returns a native nested list object with cursor pagination
        all_ids = []
        page = 1
        while True:
            result = call_tool("list_invoice_ids", page=page, page_size=20)
            all_ids.extend(rec["id"] for rec in result["results"])
            if not result["has_more"]:
                break
            page = result["next_cursor"]
        assert len(all_ids) == total_count

        # ----- Step 3: process every invoice -----
        product_cache = {}
        supplier_cache = {}
        flagged = []

        for inv_id in all_ids:
            # get_invoice returns a JSON-encoded string of a nested record
            inv_rec = json.loads(call_tool("get_invoice", invoice_id=inv_id))
            props = inv_rec["properties"]
            inv = {
                "product_id": props["Product"]["relation"][0]["id"],
                "supplier_id": props["Supplier"]["relation"][0]["id"],
                "declared_unit_value": props["Declared Unit Value"]["number"],
                "currency": props["Currency"]["select"]["name"],
                "quantity": props["Quantity"]["number"],
            }

            # get_product returns a Python-repr string of a nested record (cached)
            prod_id = inv["product_id"]
            if prod_id not in product_cache:
                prod_rec = ast.literal_eval(call_tool("get_product", product_id=prod_id))
                pprops = prod_rec["properties"]
                product_cache[prod_id] = {
                    "product_name": pprops["Product Name"]["title"][0]["plain_text"],
                    "hs_code": pprops["HS Code"]["rich_text"][0]["plain_text"],
                    "category": pprops["Category"]["select"]["name"],
                }
            product = product_cache[prod_id]

            # get_shipment returns an MCP-style envelope
            ship = unwrap_envelope(call_tool("get_shipment", invoice_id=inv_id))

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
                    # get_supplier returns plain "key: value" text
                    supplier_cache[sup_id] = parse_kv_text(
                        call_tool("get_supplier", supplier_id=sup_id)
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

        print(f"verify: {tool_calls} tool calls made")
        return self.step(action)
