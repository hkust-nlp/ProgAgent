import csv
import io
import json
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

    # ------------------------------------------------------------------ tools
    @tool(
        description=(
            "Returns a paginated list of finished goods. Each entry includes "
            "product_id, product_name, and category."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "1-based page number.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 50).",
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_products(self, page: int, page_size: int) -> dict:
        page_size = min(int(page_size), 50)
        page = max(int(page), 1)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM finished_goods")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT product_id, product_name, category FROM finished_goods "
            "ORDER BY product_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "products": [
                {"product_id": r[0], "product_name": r[1], "category": r[2]}
                for r in rows
            ],
        }

    @tool(
        description=(
            "Returns the bill of materials for a given product. Each BOM line "
            "includes material_id, standard_qty, and standard_unit_price."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier, e.g. 'FG-0001'.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_bom(self, product_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT material_id, standard_qty, standard_unit_price "
            "FROM bom_items WHERE product_id = ? ORDER BY material_id",
            (product_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "product_id": product_id,
            "bom_items": [
                {
                    "material_id": r[0],
                    "standard_qty": r[1],
                    "standard_unit_price": r[2],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Returns details for a single raw material including its "
            "material_name, unit, and standard_price."
        ),
        parameters={
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "The material identifier, e.g. 'MAT-0001'.",
                },
            },
            "required": ["material_id"],
        },
    )
    def get_material_info(self, material_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT material_id, material_name, unit, standard_price "
            "FROM raw_materials WHERE material_id = ?",
            (material_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"error": f"Material {material_id} not found."}
        return {
            "material_id": row[0],
            "material_name": row[1],
            "unit": row[2],
            "standard_price": row[3],
        }

    @tool(
        description=(
            "Returns the list of approved vendors for a given material. Each "
            "entry includes vendor_id, vendor_name, is_preferred (0 or 1), "
            "and status ('active' or 'inactive')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "string",
                    "description": "The material identifier, e.g. 'MAT-0001'.",
                },
            },
            "required": ["material_id"],
        },
    )
    def get_approved_vendors(self, material_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT vendor_id, vendor_name, is_preferred, status "
            "FROM approved_vendors WHERE material_id = ? ORDER BY vendor_id",
            (material_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "material_id": material_id,
            "vendors": [
                {
                    "vendor_id": r[0],
                    "vendor_name": r[1],
                    "is_preferred": r[2],
                    "status": r[3],
                }
                for r in rows
            ],
        }

    @tool(
        description=(
            "Returns the labor routing for a given product. Each routing line "
            "includes operation_name, standard_hours, and standard_labor_rate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product identifier, e.g. 'FG-0001'.",
                },
            },
            "required": ["product_id"],
        },
    )
    def get_labor_routing(self, product_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT operation_name, standard_hours, standard_labor_rate "
            "FROM labor_routings WHERE product_id = ? ORDER BY operation_name",
            (product_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return {
            "product_id": product_id,
            "routings": [
                {
                    "operation_name": r[0],
                    "standard_hours": r[1],
                    "standard_labor_rate": r[2],
                }
                for r in rows
            ],
        }

    # -------------------------------------------------------------- step
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
        criteria = {}

        # Load ground truth
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT product_id, product_name, standard_material_cost, actual_material_cost, "
            "material_variance, material_variance_pct, standard_labor_cost, actual_labor_cost, "
            "labor_variance, labor_variance_pct, yield_rate, yield_adjusted_total, "
            "total_standard_cost, total_variance, total_variance_pct, flag, revision_recommended "
            "FROM ground_truth ORDER BY product_id"
        )
        gt_rows = cur.fetchall()
        conn.close()

        gt = {}
        for r in gt_rows:
            gt[r[0]] = {
                "product_id": r[0],
                "product_name": r[1],
                "standard_material_cost": r[2],
                "actual_material_cost": r[3],
                "material_variance": r[4],
                "material_variance_pct": r[5],
                "standard_labor_cost": r[6],
                "actual_labor_cost": r[7],
                "labor_variance": r[8],
                "labor_variance_pct": r[9],
                "yield_rate": r[10],
                "yield_adjusted_total": r[11],
                "total_standard_cost": r[12],
                "total_variance": r[13],
                "total_variance_pct": r[14],
                "flag": r[15],
                "revision_recommended": r[16],
            }

        total_products = len(gt)

        # ---- Criterion 1: file exists, correct columns, correct sort order (15 pts) ----
        report_path = os.path.join(self.workspace, "variance_report.csv")
        expected_cols = [
            "product_id", "product_name",
            "standard_material_cost", "actual_material_cost",
            "material_variance", "material_variance_pct",
            "standard_labor_cost", "actual_labor_cost",
            "labor_variance", "labor_variance_pct",
            "yield_rate", "yield_adjusted_total",
            "total_standard_cost", "total_variance", "total_variance_pct",
            "flag", "revision_recommended",
        ]
        agent_data = {}
        ordered_abs_pcts = []
        file_ok = False
        cols_ok = False
        sort_ok = False
        if os.path.exists(report_path):
            try:
                with open(report_path, "r") as f:
                    reader = csv.DictReader(f)
                    actual_cols = [c.strip() for c in reader.fieldnames] if reader.fieldnames else []
                    cols_ok = all(c in actual_cols for c in expected_cols)
                    for row in reader:
                        row = {k.strip(): v.strip() for k, v in row.items()}
                        pid = row.get("product_id", "")
                        agent_data[pid] = row
                        try:
                            ordered_abs_pcts.append(abs(float(row.get("total_variance_pct", "0"))))
                        except (ValueError, TypeError):
                            pass
                file_ok = True
            except Exception:
                pass
        # Sort order: abs(total_variance_pct) must be non-increasing
        if len(ordered_abs_pcts) >= 2:
            sort_ok = all(
                ordered_abs_pcts[i] >= ordered_abs_pcts[i + 1]
                for i in range(len(ordered_abs_pcts) - 1)
            )
        elif len(ordered_abs_pcts) <= 1:
            sort_ok = True

        c1_score = 0
        if file_ok:
            c1_score += 5
        if cols_ok:
            c1_score += 5
        if sort_ok:
            c1_score += 5
        criteria["file_structure"] = {
            "passed": c1_score == 15,
            "score": c1_score,
            "max_score": 15,
            "reason": "" if c1_score == 15 else "File missing, columns incorrect, or rows not sorted by descending abs(total_variance_pct)",
        }

        # ---- Criterion 2: all products present (10 pts) ----
        present = sum(1 for pid in gt if pid in agent_data)
        c2_score = round(present / total_products * 10) if total_products else 0
        criteria["all_products_present"] = {
            "passed": c2_score == 10,
            "score": c2_score,
            "max_score": 10,
            "reason": "" if c2_score == 10 else f"{total_products - present} products missing",
        }

        # Helper for numeric comparison
        def _close(a, b, rel=0.01, abs_tol=1.0):
            try:
                a, b = float(a), float(b)
            except (ValueError, TypeError):
                return False
            if abs(b) < 1e-9:
                return abs(a) < abs_tol
            return abs(a - b) <= max(rel * abs(b), abs_tol)

        # ---- Criterion 3: material cost variances (20 pts) ----
        mat_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                _close(a.get("standard_material_cost", ""), g["standard_material_cost"])
                and _close(a.get("actual_material_cost", ""), g["actual_material_cost"])
                and _close(a.get("material_variance", ""), g["material_variance"])
                and _close(a.get("material_variance_pct", ""), g["material_variance_pct"], rel=0.02, abs_tol=0.5)
            ):
                mat_ok += 1
        c3_score = round(mat_ok / total_products * 20) if total_products else 0
        criteria["material_cost_accuracy"] = {
            "passed": c3_score == 20,
            "score": c3_score,
            "max_score": 20,
            "reason": "" if c3_score == 20 else f"{total_products - mat_ok} products have material cost errors",
        }

        # ---- Criterion 4: labor cost variances (20 pts) ----
        lab_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                _close(a.get("standard_labor_cost", ""), g["standard_labor_cost"])
                and _close(a.get("actual_labor_cost", ""), g["actual_labor_cost"])
                and _close(a.get("labor_variance", ""), g["labor_variance"])
                and _close(a.get("labor_variance_pct", ""), g["labor_variance_pct"], rel=0.02, abs_tol=0.5)
            ):
                lab_ok += 1
        c4_score = round(lab_ok / total_products * 20) if total_products else 0
        criteria["labor_cost_accuracy"] = {
            "passed": c4_score == 20,
            "score": c4_score,
            "max_score": 20,
            "reason": "" if c4_score == 20 else f"{total_products - lab_ok} products have labor cost errors",
        }

        # ---- Criterion 5: yield rates and adjusted totals (15 pts) ----
        yld_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                _close(a.get("yield_rate", ""), g["yield_rate"], rel=0.005, abs_tol=0.005)
                and _close(a.get("yield_adjusted_total", ""), g["yield_adjusted_total"])
                and _close(a.get("total_standard_cost", ""), g["total_standard_cost"])
                and _close(a.get("total_variance", ""), g["total_variance"])
                and _close(a.get("total_variance_pct", ""), g["total_variance_pct"], rel=0.02, abs_tol=0.5)
            ):
                yld_ok += 1
        c5_score = round(yld_ok / total_products * 15) if total_products else 0
        criteria["yield_and_totals"] = {
            "passed": c5_score == 15,
            "score": c5_score,
            "max_score": 15,
            "reason": "" if c5_score == 15 else f"{total_products - yld_ok} products have yield/total errors",
        }

        # ---- Criterion 6: flags and revision recommendations (10 pts) ----
        flag_ok = 0
        for pid, g in gt.items():
            if pid not in agent_data:
                continue
            a = agent_data[pid]
            if (
                a.get("flag", "").strip().upper() == g["flag"]
                and a.get("revision_recommended", "").strip().upper() == g["revision_recommended"]
            ):
                flag_ok += 1
        c6_score = round(flag_ok / total_products * 10) if total_products else 0
        criteria["flags_and_revision"] = {
            "passed": c6_score == 10,
            "score": c6_score,
            "max_score": 10,
            "reason": "" if c6_score == 10 else f"{total_products - flag_ok} products have flag/revision errors",
        }

        # ---- Criterion 7: action string lists revision products (10 pts) ----
        revision_pids = [pid for pid, g in gt.items() if g["revision_recommended"] == "YES"]
        mentioned = 0
        for pid in revision_pids:
            if pid in action:
                mentioned += 1
        if revision_pids:
            c7_score = round(mentioned / len(revision_pids) * 10)
        else:
            c7_score = 10  # no revisions needed, auto-pass
        criteria["action_revision_summary"] = {
            "passed": c7_score == 10,
            "score": c7_score,
            "max_score": 10,
            "reason": "" if c7_score == 10 else f"{len(revision_pids) - mentioned} revision products not mentioned in response",
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
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import glob as globmod

        # 1. List all products via paginated tool
        all_products = []
        page = 1
        while True:
            res = self.tools["list_products"](page=page, page_size=10)
            all_products.extend(res["products"])
            if page * 10 >= res["total"]:
                break
            page += 1

        # 2. Read cost thresholds
        with open(os.path.join(self.workspace, "cost_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)

        # 3. Read revision policy (to confirm rules)
        with open(os.path.join(self.workspace, "revision_policy.txt")) as f:
            _ = f.read()

        # 4. Read all vendor quote JSON files
        vendor_price_map = {}  # vendor_id -> {material_id, quoted_price}
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "vendor_quotes_*.json"))):
            with open(fpath) as f:
                data = json.load(f)
            for q in data["quotes"]:
                vendor_price_map[q["vendor_id"]] = {
                    "material_id": q["material_id"],
                    "quoted_price": q["quoted_price"],
                }

        # 5. Read all material handling TXT files
        handling_map = {}  # material_id -> surcharge
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "material_specs_*.txt"))):
            with open(fpath) as f:
                content = f.read()
            # Parse material blocks
            blocks = content.split("---")
            for block in blocks:
                mid_m = re.search(r"Material ID:\s*(\S+)", block)
                hs_m = re.search(r"Handling Surcharge:\s*([\d.]+)", block)
                if mid_m and hs_m:
                    handling_map[mid_m.group(1)] = float(hs_m.group(1))

        # 6. Read all yield report CSV files
        yield_map = {}  # product_id -> [(planned, actual)]
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "yield_report_*.csv"))):
            with open(fpath) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row["product_id"]
                    yield_map.setdefault(pid, []).append(
                        (int(row["planned_qty"]), int(row["actual_qty"]))
                    )

        # 7. Read all production summary MD files for actual hours
        actual_hours_map = {}  # (product_id, operation) -> actual_hours
        for fpath in sorted(globmod.glob(os.path.join(self.workspace, "production_summary_*.md"))):
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("|") and not line.startswith("|-") and "Product ID" not in line:
                        parts = [p.strip() for p in line.split("|")]
                        parts = [p for p in parts if p]
                        if len(parts) >= 4:
                            pid = parts[0]
                            op = parts[1]
                            try:
                                ah = float(parts[3])
                                actual_hours_map[(pid, op)] = ah
                            except ValueError:
                                pass

        # 8. For each product, compute variances using tools + workspace
        results = []
        for prod in all_products:
            pid = prod["product_id"]
            pname = prod["product_name"]

            # Get BOM
            bom_res = self.tools["get_bom"](product_id=pid)
            bom = bom_res["bom_items"]

            # Standard material cost
            std_mat = sum(b["standard_qty"] * b["standard_unit_price"] for b in bom)

            # Actual material cost
            act_mat = 0.0
            has_non_preferred = False
            for b in bom:
                mid = b["material_id"]
                # Get approved vendors
                vres = self.tools["get_approved_vendors"](material_id=mid)
                vendors = vres["vendors"]
                active = [v for v in vendors if v["status"] == "active"]
                preferred = [v for v in active if v["is_preferred"] == 1]

                if preferred and preferred[0]["vendor_id"] in vendor_price_map:
                    act_price = vendor_price_map[preferred[0]["vendor_id"]]["quoted_price"]
                else:
                    has_non_preferred = True
                    prices = [
                        vendor_price_map[v["vendor_id"]]["quoted_price"]
                        for v in active
                        if v["vendor_id"] in vendor_price_map
                    ]
                    act_price = min(prices) if prices else 0.0

                handling = handling_map.get(mid, 0.0)
                act_mat += b["standard_qty"] * (act_price + handling)

            mat_var = act_mat - std_mat
            mat_var_pct = (mat_var / std_mat * 100) if std_mat else 0.0

            # Labor
            lr_res = self.tools["get_labor_routing"](product_id=pid)
            routings = lr_res["routings"]
            std_lab = sum(r["standard_hours"] * r["standard_labor_rate"] for r in routings)

            act_lab = 0.0
            for r in routings:
                ah = actual_hours_map.get((pid, r["operation_name"]), r["standard_hours"])
                act_lab += ah * r["standard_labor_rate"]
            lab_var = act_lab - std_lab
            lab_var_pct = (lab_var / std_lab * 100) if std_lab else 0.0

            # Yield
            ylds = yield_map.get(pid, [])
            total_planned = sum(p for p, _ in ylds)
            total_actual = sum(a for _, a in ylds)
            yield_rate = total_actual / total_planned if total_planned > 0 else 1.0

            yield_adj = (act_mat + act_lab) / yield_rate if yield_rate > 0 else (act_mat + act_lab)
            total_std = std_mat + std_lab
            total_var = yield_adj - total_std
            total_var_pct = (total_var / total_std * 100) if total_std else 0.0

            flag = "YES" if abs(total_var_pct) > thresholds["total_variance_threshold"] else "NO"

            revision = "NO"
            if abs(total_var_pct) > thresholds["total_critical_threshold"]:
                revision = "YES"
            elif abs(mat_var_pct) > thresholds["material_critical_threshold"] and has_non_preferred:
                revision = "YES"
            elif yield_rate < thresholds["yield_loss_threshold"]:
                revision = "YES"

            results.append({
                "product_id": pid,
                "product_name": pname,
                "standard_material_cost": round(std_mat, 2),
                "actual_material_cost": round(act_mat, 2),
                "material_variance": round(mat_var, 2),
                "material_variance_pct": round(mat_var_pct, 2),
                "standard_labor_cost": round(std_lab, 2),
                "actual_labor_cost": round(act_lab, 2),
                "labor_variance": round(lab_var, 2),
                "labor_variance_pct": round(lab_var_pct, 2),
                "yield_rate": round(yield_rate, 4),
                "yield_adjusted_total": round(yield_adj, 2),
                "total_standard_cost": round(total_std, 2),
                "total_variance": round(total_var, 2),
                "total_variance_pct": round(total_var_pct, 2),
                "flag": flag,
                "revision_recommended": revision,
            })

        # Sort by absolute total_variance_pct descending
        results.sort(key=lambda x: abs(x["total_variance_pct"]), reverse=True)

        # 9. Write variance_report.csv
        cols = [
            "product_id", "product_name",
            "standard_material_cost", "actual_material_cost",
            "material_variance", "material_variance_pct",
            "standard_labor_cost", "actual_labor_cost",
            "labor_variance", "labor_variance_pct",
            "yield_rate", "yield_adjusted_total",
            "total_standard_cost", "total_variance", "total_variance_pct",
            "flag", "revision_recommended",
        ]
        report_path = os.path.join(self.workspace, "variance_report.csv")
        with open(report_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(results)

        # 10. Build action string
        revision_items = [r for r in results if r["revision_recommended"] == "YES"]
        lines = ["Cost Variance Analysis Complete.", ""]
        lines.append(f"Total products analysed: {len(results)}")
        lines.append(f"Products flagged: {sum(1 for r in results if r['flag'] == 'YES')}")
        lines.append(f"Products recommended for revision: {len(revision_items)}")
        lines.append("")
        lines.append("Products recommended for cost revision:")
        for r in revision_items:
            reasons = []
            if abs(r["total_variance_pct"]) > thresholds["total_critical_threshold"]:
                reasons.append(f"total variance {r['total_variance_pct']:.2f}% exceeds critical threshold")
            if abs(r["material_variance_pct"]) > thresholds["material_critical_threshold"]:
                reasons.append(f"material variance {r['material_variance_pct']:.2f}% exceeds material critical threshold (non-preferred vendor used)")
            if r["yield_rate"] < thresholds["yield_loss_threshold"]:
                reasons.append(f"yield rate {r['yield_rate']:.4f} below minimum threshold")
            lines.append(
                f"  {r['product_id']} ({r['product_name']}): total variance = {r['total_variance_pct']:.2f}% "
                f"— reasons: {'; '.join(reasons)}"
            )

        action = "\n".join(lines)
        return self.step(action)
