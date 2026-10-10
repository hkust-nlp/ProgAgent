"""
Environment for customs import shipment inspection task.
Agent must identify high-risk shipments with >85% anomaly probability
and produce a daily inspection shortlist.
"""

import csv
import json
import os
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

    # ── Tool methods ───────────────────────────────────────────────────────

    @tool(
        description=(
            "Retrieve import shipment declarations for a given date. "
            "Returns up to 10 records per page. Use the 'page' parameter "
            "to paginate through results."
        ),
        parameters={
            "type": "object",
            "properties": {
                "declaration_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Each page has up to 10 records.",
                },
            },
            "required": ["declaration_date", "page"],
        },
    )
    def get_declarations_by_date(self, declaration_date: str, page: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        page_size = 10
        offset = (int(page) - 1) * page_size

        c.execute(
            "SELECT COUNT(*) FROM shipments WHERE declaration_date = ?",
            (declaration_date,),
        )
        total = c.fetchone()[0]

        c.execute(
            "SELECT shipment_id, shipper_id, hs_code, country_of_origin, "
            "declared_value, quantity, weight_kg, port_of_entry, "
            "commodity_description, consignee_name "
            "FROM shipments WHERE declaration_date = ? "
            "ORDER BY shipment_id LIMIT ? OFFSET ?",
            (declaration_date, page_size, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "declaration_date": declaration_date,
            "page": int(page),
            "page_size": page_size,
            "total_records": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": rows,
        }

    @tool(
        description=(
            "Get detailed information about a specific shipment by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shipment_id": {
                    "type": "string",
                    "description": "The shipment identifier (e.g. IMP00001)",
                },
            },
            "required": ["shipment_id"],
        },
    )
    def get_shipment_details(self, shipment_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM shipments WHERE shipment_id = ?", (shipment_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Shipment {shipment_id} not found"}

    @tool(
        description=(
            "Retrieve the compliance profile of a shipper including tier, "
            "violation count, and registration details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shipper_id": {
                    "type": "string",
                    "description": "The shipper identifier (e.g. SH0001)",
                },
            },
            "required": ["shipper_id"],
        },
    )
    def get_shipper_profile(self, shipper_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM shippers WHERE shipper_id = ?", (shipper_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"Shipper {shipper_id} not found"}

    @tool(
        description=(
            "Look up HS code classification details including chapter, "
            "category, duty rate, and license requirements."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hs_code": {
                    "type": "string",
                    "description": "The HS code (e.g. 8401.23)",
                },
            },
            "required": ["hs_code"],
        },
    )
    def lookup_hs_code(self, hs_code: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM hs_codes WHERE hs_code = ?", (hs_code,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"error": f"HS code {hs_code} not found"}

    @tool(
        description=(
            "Retrieve past inspection results for a given shipper. "
            "Returns all inspection records associated with the shipper."
        ),
        parameters={
            "type": "object",
            "properties": {
                "shipper_id": {
                    "type": "string",
                    "description": "The shipper identifier",
                },
            },
            "required": ["shipper_id"],
        },
    )
    def get_shipper_inspections(self, shipper_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM inspection_results WHERE shipper_id = ? "
            "ORDER BY inspection_date DESC",
            (shipper_id,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return {
            "shipper_id": shipper_id,
            "total_inspections": len(rows),
            "records": rows,
        }

    @tool(
        description=(
            "List all available shipper dossier files in the workspace. "
            "Returns file names of shipper dossier JSON files."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_dossier_files(self) -> dict:
        files = []
        for f in sorted(os.listdir(self.workspace)):
            if f.startswith("shipper_dossier_") and f.endswith(".json"):
                files.append(f)
        return {"dossier_files": files, "count": len(files)}

    @tool(
        description=(
            "Read a specific file from the working directory. "
            "Supports JSON, YAML, CSV, MD, and TXT files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the file to read (e.g. 'anomaly_weights.yaml')",
                },
            },
            "required": ["filename"],
        },
    )
    def read_workspace_file(self, filename: str) -> dict:
        filepath = os.path.join(self.workspace, filename)
        if not os.path.exists(filepath):
            return {"error": f"File {filename} not found"}
        try:
            with open(filepath, "r") as f:
                content = f.read()
            if filename.endswith(".json"):
                return {"filename": filename, "format": "json",
                        "content": json.loads(content)}
            elif filename.endswith(".yaml") or filename.endswith(".yml"):
                return {"filename": filename, "format": "yaml",
                        "content": yaml.safe_load(content)}
            elif filename.endswith(".csv"):
                rows = []
                reader = csv.DictReader(content.splitlines())
                for row in reader:
                    rows.append(dict(row))
                return {"filename": filename, "format": "csv",
                        "content": rows}
            else:
                return {"filename": filename, "format": "text",
                        "content": content}
        except Exception as e:
            return {"error": f"Error reading {filename}: {str(e)}"}

    @tool(
        description=(
            "List all files in the working directory with their types and sizes."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_workspace_files(self) -> dict:
        files = []
        for f in sorted(os.listdir(self.workspace)):
            fpath = os.path.join(self.workspace, f)
            if os.path.isfile(fpath):
                size = os.path.getsize(fpath)
                ext = os.path.splitext(f)[1]
                files.append({"filename": f, "extension": ext,
                              "size_bytes": size})
        return {"files": files, "total_count": len(files)}

    @tool(
        description=(
            "Write content to a file in the working directory. "
            "Use this to save output deliverables."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["filename", "content"],
        },
    )
    def write_workspace_file(self, filename: str, content: str) -> dict:
        filepath = os.path.join(self.workspace, filename)
        try:
            with open(filepath, "w") as f:
                f.write(content)
            return {"success": True, "filename": filename,
                    "bytes_written": len(content)}
        except Exception as e:
            return {"error": f"Error writing {filename}: {str(e)}"}

    # ── Scoring helpers ────────────────────────────────────────────────────

    def _compute_ground_truth(self) -> List[dict]:
        """Compute the ground-truth anomaly scores for all shipments on TARGET_DATE."""
        # Load workspace config files
        with open(os.path.join(self.workspace, "anomaly_weights.yaml")) as f:
            config = yaml.safe_load(f)
        scoring = config["anomaly_scoring"]
        weights = scoring["weights"]
        tier_scores = scoring["shipper_tier_scores"]
        blend = scoring["shipper_compliance_blend"]
        dossier_defaults = scoring["dossier_defaults"]

        with open(os.path.join(self.workspace, "country_risk_tiers.json")) as f:
            country_risks = json.load(f)

        evasion_lookup = {}
        with open(os.path.join(self.workspace, "evasion_watchlist.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["hs_chapter"], row["country_of_origin"])
                evasion_lookup[key] = float(row["match_score"])

        # Parse valuation benchmarks
        benchmarks = {}
        with open(os.path.join(self.workspace, "valuation_benchmarks.md")) as f:
            for line in f:
                line = line.strip()
                if line.startswith("|") and not line.startswith("|-"):
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) == 4 and parts[0] != "Category":
                        try:
                            benchmarks[parts[0]] = {
                                "min": float(parts[1]),
                                "max": float(parts[2]),
                                "median": float(parts[3]),
                            }
                        except ValueError:
                            pass

        # Load dossier files
        dossiers = {}
        for f in os.listdir(self.workspace):
            if f.startswith("shipper_dossier_") and f.endswith(".json"):
                with open(os.path.join(self.workspace, f)) as fh:
                    d = json.load(fh)
                    dossiers[d["shipper_id"]] = d

        # Query DB for today's shipments
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT * FROM shipments WHERE declaration_date = '2026-04-20' "
            "ORDER BY shipment_id"
        )
        today_shipments = [dict(r) for r in c.fetchall()]

        results = []
        for ship in today_shipments:
            # 1. Shipper compliance score
            c.execute("SELECT * FROM shippers WHERE shipper_id = ?",
                      (ship["shipper_id"],))
            shipper = dict(c.fetchone())

            tier_score = tier_scores.get(shipper["compliance_tier"], 0.5)
            violation_rate = (shipper["violation_count"] /
                              max(shipper["total_shipments"], 1))
            violation_component = min(
                violation_rate * blend["violation_rate_multiplier"], 1.0
            )
            shipper_compliance_score = (
                tier_score * blend["tier_weight"] +
                violation_component * blend["violation_rate_weight"]
            )

            # 2. Country risk score
            country_raw = country_risks.get(ship["country_of_origin"], 50)
            country_risk_score = country_raw / 100.0

            # 3. Evasion pattern match
            c.execute("SELECT chapter FROM hs_codes WHERE hs_code = ?",
                      (ship["hs_code"],))
            hs_row = c.fetchone()
            hs_chapter = dict(hs_row)["chapter"] if hs_row else ""
            evasion_key = (hs_chapter, ship["country_of_origin"])
            evasion_score = evasion_lookup.get(evasion_key, 0.0)

            # 4. Valuation anomaly
            c.execute("SELECT category FROM hs_codes WHERE hs_code = ?",
                      (ship["hs_code"],))
            cat_row = c.fetchone()
            category = dict(cat_row)["category"] if cat_row else ""
            unit_price = ship["declared_value"] / max(ship["quantity"], 1)
            bench = benchmarks.get(category)
            if bench:
                median = bench["median"]
                if median > 0:
                    ratio = abs(unit_price - median) / median
                    valuation_score = min(ratio, 1.0)
                else:
                    valuation_score = 0.0
            else:
                valuation_score = 0.0

            # 5. Dossier alerts score
            dossier = dossiers.get(ship["shipper_id"])
            if dossier:
                alert_sum = (dossier["recent_alert_count"] +
                             dossier["pending_investigations"])
                dossier_score = min(
                    alert_sum / dossier_defaults["alert_divisor"], 1.0
                )
            else:
                dossier_score = dossier_defaults["missing_dossier_score"]

            # Weighted anomaly probability
            anomaly_prob = (
                weights["shipper_compliance"] * shipper_compliance_score +
                weights["country_risk"] * country_risk_score +
                weights["evasion_pattern"] * evasion_score +
                weights["valuation_anomaly"] * valuation_score +
                weights["dossier_alerts"] * dossier_score
            )

            results.append({
                "shipment_id": ship["shipment_id"],
                "shipper_id": ship["shipper_id"],
                "hs_code": ship["hs_code"],
                "country_of_origin": ship["country_of_origin"],
                "declared_value": ship["declared_value"],
                "anomaly_probability": round(anomaly_prob, 4),
                "flagged": anomaly_prob > 0.85,
                "shipper_compliance_score": round(shipper_compliance_score, 4),
                "country_risk_score": round(country_risk_score, 4),
                "evasion_score": round(evasion_score, 4),
                "valuation_score": round(valuation_score, 4),
                "dossier_score": round(dossier_score, 4),
            })

        conn.close()
        # Sort by anomaly_probability descending
        results.sort(key=lambda x: x["anomaly_probability"], reverse=True)
        return results

    # ── step ───────────────────────────────────────────────────────────────

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
        gt_flagged = [r for r in ground_truth if r["flagged"]]
        gt_flagged_ids = set(r["shipment_id"] for r in gt_flagged)
        gt_all_ids = set(r["shipment_id"] for r in ground_truth)

        eval_criteria = {}
        total_score = 0
        max_score = 0

        # ── Criterion 1: inspection_shortlist.csv exists (10 pts) ──────
        crit_name = "shortlist_file_exists"
        crit_max = 10
        max_score += crit_max
        shortlist_path = os.path.join(self.workspace, "inspection_shortlist.csv")
        file_exists = os.path.exists(shortlist_path)
        if file_exists:
            eval_criteria[crit_name] = {
                "passed": True, "score": crit_max, "max_score": crit_max
            }
            total_score += crit_max
        else:
            eval_criteria[crit_name] = {
                "passed": False, "score": 0, "max_score": crit_max,
                "reason": "inspection_shortlist.csv not found in workspace"
            }

        # ── Criterion 2: correct columns in CSV (10 pts) ──────────────
        crit_name = "correct_columns"
        crit_max = 10
        max_score += crit_max
        required_cols = {
            "shipment_id", "shipper_id", "hs_code",
            "country_of_origin", "declared_value", "anomaly_probability"
        }
        agent_rows = []
        csv_cols_ok = False
        if file_exists:
            try:
                with open(shortlist_path) as f:
                    reader = csv.DictReader(f)
                    actual_cols = set(reader.fieldnames) if reader.fieldnames else set()
                    for row in reader:
                        agent_rows.append(row)
                if required_cols.issubset(actual_cols):
                    csv_cols_ok = True
                    eval_criteria[crit_name] = {
                        "passed": True, "score": crit_max, "max_score": crit_max
                    }
                    total_score += crit_max
                else:
                    missing = required_cols - actual_cols
                    eval_criteria[crit_name] = {
                        "passed": False, "score": 0, "max_score": crit_max,
                        "reason": f"Missing columns: {missing}"
                    }
            except Exception as e:
                eval_criteria[crit_name] = {
                    "passed": False, "score": 0, "max_score": crit_max,
                    "reason": f"Error parsing CSV: {e}"
                }
        else:
            eval_criteria[crit_name] = {
                "passed": False, "score": 0, "max_score": crit_max,
                "reason": "File does not exist"
            }

        # ── Criterion 3: correct flagged shipment IDs (25 pts) ─────────
        crit_name = "correct_flagged_shipments"
        crit_max = 25
        max_score += crit_max
        if csv_cols_ok and agent_rows:
            agent_flagged_ids = set(r["shipment_id"] for r in agent_rows)
            true_positives = agent_flagged_ids & gt_flagged_ids
            false_positives = agent_flagged_ids - gt_flagged_ids
            false_negatives = gt_flagged_ids - agent_flagged_ids

            if len(gt_flagged_ids) > 0:
                recall = len(true_positives) / len(gt_flagged_ids)
            else:
                recall = 1.0 if len(agent_flagged_ids) == 0 else 0.0
            if len(agent_flagged_ids) > 0:
                precision = len(true_positives) / len(agent_flagged_ids)
            else:
                precision = 1.0 if len(gt_flagged_ids) == 0 else 0.0

            if precision + recall > 0:
                f1 = 2 * precision * recall / (precision + recall)
            else:
                f1 = 0.0

            earned = round(f1 * crit_max)
            passed = (f1 == 1.0)
            info_dict = {
                "passed": passed, "score": earned, "max_score": crit_max,
            }
            if not passed:
                info_dict["reason"] = (
                    f"F1={f1:.3f} precision={precision:.3f} recall={recall:.3f} "
                    f"TP={len(true_positives)} FP={len(false_positives)} "
                    f"FN={len(false_negatives)}"
                )
            eval_criteria[crit_name] = info_dict
            total_score += earned
        else:
            eval_criteria[crit_name] = {
                "passed": False, "score": 0, "max_score": crit_max,
                "reason": "CSV not readable or no rows"
            }

        # ── Criterion 4: anomaly probabilities accurate (20 pts) ───────
        crit_name = "anomaly_probabilities_accurate"
        crit_max = 20
        max_score += crit_max
        if csv_cols_ok and agent_rows:
            gt_prob_map = {r["shipment_id"]: r["anomaly_probability"]
                          for r in ground_truth}
            n_checked = 0
            n_accurate = 0
            for row in agent_rows:
                sid = row["shipment_id"]
                if sid in gt_prob_map:
                    try:
                        agent_prob = float(row["anomaly_probability"])
                        gt_prob = gt_prob_map[sid]
                        if abs(agent_prob - gt_prob) < 0.02:
                            n_accurate += 1
                    except (ValueError, KeyError):
                        pass
                    n_checked += 1

            if n_checked > 0:
                accuracy_ratio = n_accurate / n_checked
                earned = round(accuracy_ratio * crit_max)
                passed = accuracy_ratio == 1.0
                info_dict = {
                    "passed": passed, "score": earned, "max_score": crit_max,
                }
                if not passed:
                    info_dict["reason"] = (
                        f"{n_accurate}/{n_checked} probabilities within tolerance"
                    )
                eval_criteria[crit_name] = info_dict
                total_score += earned
            else:
                eval_criteria[crit_name] = {
                    "passed": False, "score": 0, "max_score": crit_max,
                    "reason": "No matching shipment IDs found"
                }
        else:
            eval_criteria[crit_name] = {
                "passed": False, "score": 0, "max_score": crit_max,
                "reason": "CSV not readable"
            }

        # ── Criterion 5: sort order descending by anomaly_probability (15 pts)
        crit_name = "sort_order_correct"
        crit_max = 15
        max_score += crit_max
        if csv_cols_ok and len(agent_rows) > 1:
            try:
                probs = [float(r["anomaly_probability"]) for r in agent_rows]
                is_sorted = all(probs[i] >= probs[i + 1]
                                for i in range(len(probs) - 1))
                if is_sorted:
                    eval_criteria[crit_name] = {
                        "passed": True, "score": crit_max, "max_score": crit_max
                    }
                    total_score += crit_max
                else:
                    eval_criteria[crit_name] = {
                        "passed": False, "score": 0, "max_score": crit_max,
                        "reason": "Rows not sorted by anomaly_probability descending"
                    }
            except ValueError:
                eval_criteria[crit_name] = {
                    "passed": False, "score": 0, "max_score": crit_max,
                    "reason": "Could not parse anomaly_probability as float"
                }
        elif csv_cols_ok and len(agent_rows) <= 1:
            eval_criteria[crit_name] = {
                "passed": True, "score": crit_max, "max_score": crit_max
            }
            total_score += crit_max
        else:
            eval_criteria[crit_name] = {
                "passed": False, "score": 0, "max_score": crit_max,
                "reason": "CSV not readable"
            }

        # ── Criterion 6: response summary (20 pts) ────────────────────
        crit_name = "response_summary"
        crit_max = 20
        max_score += crit_max
        earned = 0
        reasons = []

        # Check that action mentions the count of flagged shipments
        n_flagged = len(gt_flagged_ids)
        if str(n_flagged) in action:
            earned += 10
        else:
            reasons.append(f"Response does not mention count {n_flagged}")

        # Check that action mentions the highest-risk shipment ID
        if gt_flagged:
            top_ship = gt_flagged[0]["shipment_id"]
            if top_ship in action:
                earned += 10
            else:
                reasons.append(
                    f"Response does not mention highest-risk shipment {top_ship}"
                )
        else:
            earned += 10  # No flagged, so no top to mention

        passed = earned == crit_max
        info_dict = {"passed": passed, "score": earned, "max_score": crit_max}
        if not passed:
            info_dict["reason"] = "; ".join(reasons)
        eval_criteria[crit_name] = info_dict
        total_score += earned

        reward = total_score / max_score if max_score > 0 else 0.0
        info = {
            "eval_criteria": eval_criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ── verify ─────────────────────────────────────────────────────────────

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        import csv as csv_mod
        import io

        tool_call_count = 0

        # Step 1: List workspace files to discover config + dossiers
        ws_files = self.tools["list_workspace_files"]()
        tool_call_count += 1

        # Step 2: Read configuration files
        weights_data = self.tools["read_workspace_file"](
            filename="anomaly_weights.yaml"
        )
        tool_call_count += 1
        scoring = weights_data["content"]["anomaly_scoring"]
        w = scoring["weights"]
        tier_scores = scoring["shipper_tier_scores"]
        blend = scoring["shipper_compliance_blend"]
        dossier_defaults = scoring["dossier_defaults"]
        threshold = scoring["threshold"]

        country_data = self.tools["read_workspace_file"](
            filename="country_risk_tiers.json"
        )
        tool_call_count += 1
        country_risks = country_data["content"]

        evasion_data = self.tools["read_workspace_file"](
            filename="evasion_watchlist.csv"
        )
        tool_call_count += 1
        evasion_lookup = {}
        for row in evasion_data["content"]:
            key = (row["hs_chapter"], row["country_of_origin"])
            evasion_lookup[key] = float(row["match_score"])

        benchmarks_data = self.tools["read_workspace_file"](
            filename="valuation_benchmarks.md"
        )
        tool_call_count += 1
        benchmarks = {}
        for line in benchmarks_data["content"].split("\n"):
            line = line.strip()
            if line.startswith("|") and not line.startswith("|-"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) == 4 and parts[0] != "Category":
                    try:
                        benchmarks[parts[0]] = {
                            "min": float(parts[1]),
                            "max": float(parts[2]),
                            "median": float(parts[3]),
                        }
                    except ValueError:
                        pass

        # Step 3: List and read dossier files
        dossier_list = self.tools["list_dossier_files"]()
        tool_call_count += 1
        dossiers = {}
        for fname in dossier_list["dossier_files"]:
            d = self.tools["read_workspace_file"](filename=fname)
            tool_call_count += 1
            dossiers[d["content"]["shipper_id"]] = d["content"]

        # Step 4: Get today's declarations (paginated)
        page = 1
        all_declarations = []
        while True:
            result = self.tools["get_declarations_by_date"](
                declaration_date="2026-04-20", page=page
            )
            tool_call_count += 1
            all_declarations.extend(result["records"])
            if page >= result["total_pages"]:
                break
            page += 1

        # Step 5: For each shipment, gather shipper profile, HS code, inspections
        shipper_cache = {}
        hs_cache = {}
        inspection_cache = {}

        scored_shipments = []

        for ship in all_declarations:
            sid = ship["shipper_id"]
            if sid not in shipper_cache:
                shipper_cache[sid] = self.tools["get_shipper_profile"](
                    shipper_id=sid
                )
                tool_call_count += 1

            hc = ship["hs_code"]
            if hc not in hs_cache:
                hs_cache[hc] = self.tools["lookup_hs_code"](hs_code=hc)
                tool_call_count += 1

            if sid not in inspection_cache:
                inspection_cache[sid] = self.tools["get_shipper_inspections"](
                    shipper_id=sid
                )
                tool_call_count += 1

            shipper = shipper_cache[sid]
            hs_info = hs_cache[hc]

            # Compute shipper compliance score
            tier_score = tier_scores.get(shipper["compliance_tier"], 0.5)
            violation_rate = (shipper["violation_count"] /
                              max(shipper["total_shipments"], 1))
            violation_component = min(
                violation_rate * blend["violation_rate_multiplier"], 1.0
            )
            shipper_compliance_score = (
                tier_score * blend["tier_weight"] +
                violation_component * blend["violation_rate_weight"]
            )

            # Country risk score
            country_raw = country_risks.get(ship["country_of_origin"], 50)
            country_risk_score = country_raw / 100.0

            # Evasion pattern
            hs_chapter = hs_info.get("chapter", "")
            evasion_key = (hs_chapter, ship["country_of_origin"])
            evasion_score = evasion_lookup.get(evasion_key, 0.0)

            # Valuation anomaly
            category = hs_info.get("category", "")
            unit_price = ship["declared_value"] / max(ship["quantity"], 1)
            bench = benchmarks.get(category)
            if bench:
                median = bench["median"]
                if median > 0:
                    ratio = abs(unit_price - median) / median
                    valuation_score = min(ratio, 1.0)
                else:
                    valuation_score = 0.0
            else:
                valuation_score = 0.0

            # Dossier alerts
            dossier = dossiers.get(sid)
            if dossier:
                alert_sum = (dossier["recent_alert_count"] +
                             dossier["pending_investigations"])
                dossier_score = min(
                    alert_sum / dossier_defaults["alert_divisor"], 1.0
                )
            else:
                dossier_score = dossier_defaults["missing_dossier_score"]

            # Weighted anomaly probability
            anomaly_prob = (
                w["shipper_compliance"] * shipper_compliance_score +
                w["country_risk"] * country_risk_score +
                w["evasion_pattern"] * evasion_score +
                w["valuation_anomaly"] * valuation_score +
                w["dossier_alerts"] * dossier_score
            )

            scored_shipments.append({
                "shipment_id": ship["shipment_id"],
                "shipper_id": ship["shipper_id"],
                "hs_code": ship["hs_code"],
                "country_of_origin": ship["country_of_origin"],
                "declared_value": ship["declared_value"],
                "anomaly_probability": round(anomaly_prob, 4),
            })

        # Filter and sort
        flagged = [s for s in scored_shipments
                   if s["anomaly_probability"] > threshold]
        flagged.sort(key=lambda x: x["anomaly_probability"], reverse=True)

        # Write inspection_shortlist.csv
        output = io.StringIO()
        fieldnames = [
            "shipment_id", "shipper_id", "hs_code",
            "country_of_origin", "declared_value", "anomaly_probability"
        ]
        writer = csv_mod.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in flagged:
            writer.writerow(row)

        self.tools["write_workspace_file"](
            filename="inspection_shortlist.csv",
            content=output.getvalue()
        )
        tool_call_count += 1

        # Build action string
        top_ship = flagged[0]["shipment_id"] if flagged else "none"
        top_prob = flagged[0]["anomaly_probability"] if flagged else 0.0

        action_lines = [
            f"Daily inspection shortlist for 2026-04-20 has been generated.",
            f"Total shipments analyzed: {len(all_declarations)}",
            f"Shipments flagged (anomaly probability > 85%): {len(flagged)}",
            f"",
            f"The highest-risk shipment is {top_ship} with anomaly probability {top_prob:.4f}.",
            f"",
            f"Flagged shipments (sorted by anomaly probability descending):",
        ]
        for s in flagged:
            action_lines.append(
                f"  {s['shipment_id']}: shipper={s['shipper_id']}, "
                f"HS={s['hs_code']}, origin={s['country_of_origin']}, "
                f"value=${s['declared_value']:.2f}, "
                f"anomaly={s['anomaly_probability']:.4f}"
            )
        action_lines.append("")
        action_lines.append(
            f"The shortlist has been saved as inspection_shortlist.csv "
            f"with {len(flagged)} entries."
        )

        action = "\n".join(action_lines)

        assert tool_call_count >= 15, (
            f"Tool call count {tool_call_count} < 15 minimum"
        )

        return self.step(action)
