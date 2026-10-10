import os
import json
import yaml
import csv
import sqlite3
import glob as glob_mod
from typing import Tuple, Dict, List, Any
from collections import defaultdict


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

    # ── Tool methods ───────────────────────────────────────────────

    @tool(
        description=(
            "List generators with pagination. Returns a page of generator "
            "records including generator_id, name, energy_type, capacity_mw, "
            "location_state, and commissioned_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 20). Default 20.",
                },
            },
            "required": [],
        },
    )
    def list_generators(self, page: int = 1, page_size: int = 20) -> dict:
        page_size = min(page_size, 20)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM generators").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM generators ORDER BY generator_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Get the accreditation certificate for a specific generator. "
            "Returns cert_id, generator_id, issue_date, expiry_date, "
            "certifying_body, and status."
        ),
        parameters={
            "type": "object",
            "properties": {
                "generator_id": {
                    "type": "string",
                    "description": "The generator ID, e.g. 'GEN-0001'.",
                },
            },
            "required": ["generator_id"],
        },
    )
    def get_accreditation(self, generator_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM accreditation_certificates "
            "WHERE generator_id = ?",
            (generator_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"No certificate found for {generator_id}"}
        return dict(row)

    @tool(
        description=(
            "List REC transactions with pagination and optional filters. "
            "Returns transaction_id, rec_serial, generator_id, buyer_id, "
            "trade_date, trade_time, quantity_mwh, price_per_mwh, "
            "energy_type, and vintage_month."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based). Default 1.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Records per page (max 50). Default 50.",
                },
                "generator_id": {
                    "type": "string",
                    "description": "Filter by generator ID.",
                },
                "buyer_id": {
                    "type": "string",
                    "description": "Filter by buyer ID.",
                },
                "vintage_month": {
                    "type": "string",
                    "description": "Filter by vintage month (YYYY-MM).",
                },
            },
            "required": [],
        },
    )
    def list_transactions(
        self,
        page: int = 1,
        page_size: int = 50,
        generator_id: str = None,
        buyer_id: str = None,
        vintage_month: str = None,
    ) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        where_clauses = []
        params: list = []
        if generator_id:
            where_clauses.append("generator_id = ?")
            params.append(generator_id)
        if buyer_id:
            where_clauses.append("buyer_id = ?")
            params.append(buyer_id)
        if vintage_month:
            where_clauses.append("vintage_month = ?")
            params.append(vintage_month)

        where_sql = (" WHERE " + " AND ".join(where_clauses)
                      if where_clauses else "")

        total = conn.execute(
            f"SELECT COUNT(*) FROM rec_transactions{where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM rec_transactions{where_sql} "
            f"ORDER BY transaction_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "records": [dict(r) for r in rows],
        }

    @tool(
        description=(
            "Get detailed information for a single REC transaction by ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "transaction_id": {
                    "type": "string",
                    "description": "The transaction ID, e.g. 'TXN-00001'.",
                },
            },
            "required": ["transaction_id"],
        },
    )
    def get_transaction(self, transaction_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM rec_transactions WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Transaction {transaction_id} not found"}
        return dict(row)

    @tool(
        description=(
            "Get the meter reading for a specific generator and month. "
            "Returns reading_id, generator_id, month, "
            "total_generation_mwh, peak_output_mw, and reading_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "generator_id": {
                    "type": "string",
                    "description": "The generator ID.",
                },
                "month": {
                    "type": "string",
                    "description": "The month in YYYY-MM format.",
                },
            },
            "required": ["generator_id", "month"],
        },
    )
    def get_meter_reading(self, generator_id: str, month: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM meter_readings "
            "WHERE generator_id = ? AND month = ?",
            (generator_id, month),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": (f"No meter reading for {generator_id} "
                              f"in {month}")}
        return dict(row)

    @tool(
        description=(
            "Get buyer information by buyer ID. Returns buyer_id, "
            "company_name, industry_sector, sustainability_tier, "
            "and registered_date."
        ),
        parameters={
            "type": "object",
            "properties": {
                "buyer_id": {
                    "type": "string",
                    "description": "The buyer ID, e.g. 'BUY-0001'.",
                },
            },
            "required": ["buyer_id"],
        },
    )
    def get_buyer(self, buyer_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM buyers WHERE buyer_id = ?",
            (buyer_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Buyer {buyer_id} not found"}
        return dict(row)

    # ── Evaluation ─────────────────────────────────────────────────

    def _compute_ground_truth(self) -> List[dict]:
        """Compute all anomaly records from DB + workspace files."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Load all transactions
        txns = [dict(r) for r in conn.execute(
            "SELECT * FROM rec_transactions ORDER BY transaction_id"
        ).fetchall()]

        # Load accreditation certs keyed by generator_id
        cert_rows = conn.execute(
            "SELECT * FROM accreditation_certificates"
        ).fetchall()
        cert_map = {r["generator_id"]: dict(r) for r in cert_rows}

        # Load meter readings keyed by (generator_id, month)
        mr_rows = conn.execute("SELECT * FROM meter_readings").fetchall()
        mr_map = {(r["generator_id"], r["month"]): dict(r) for r in mr_rows}

        conn.close()

        # Load workspace config
        with open(os.path.join(self.workspace, "trading_rules.json")) as f:
            trading_rules = json.load(f)
        with open(os.path.join(self.workspace,
                               "anomaly_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)

        start_hour = int(
            trading_rules["allowed_trading_hours"]["start"].split(":")[0])
        end_hour = int(
            trading_rules["allowed_trading_hours"]["end"].split(":")[0])
        tolerance = thresholds["over_generation_tolerance"]
        price_mult = thresholds["price_outlier_std_multiplier"]
        severity_map = thresholds["severity_levels"]

        # Load meter validation reports
        val_map = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "meter_validation_batch_*.csv"))
        ):
            with open(fp, newline="") as f:
                for row in csv.DictReader(f):
                    val_map[(row["generator_id"], row["month"])] = (
                        row["validation_status"])

        # Load buyer claims -> find double-counted serials
        serial_claimants = defaultdict(set)
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "buyer_claims_batch_*.yaml"))
        ):
            with open(fp) as f:
                claims = yaml.safe_load(f)
            for entry in claims:
                for serial in entry["claimed_rec_serials"]:
                    serial_claimants[serial].add(entry["buyer_id"])
        double_serials = {
            s for s, buyers in serial_claimants.items() if len(buyers) > 1
        }

        # Load price indices
        price_ref = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "price_index_*.json"))
        ):
            with open(fp) as f:
                for rec in json.load(f):
                    price_ref[(rec["date"], rec["energy_type"])] = (
                        rec["reference_price"], rec["reference_std"])

        # Aggregate transaction qty by (gen, month)
        gen_month_total = defaultdict(float)
        for t in txns:
            gen_month_total[(t["generator_id"],
                             t["vintage_month"])] += t["quantity_mwh"]

        # Check each transaction
        anomalies = []

        for t in txns:
            tid = t["transaction_id"]
            gen_id = t["generator_id"]
            buyer_id = t["buyer_id"]
            trade_date = t["trade_date"]
            rec_serial = t["rec_serial"]
            trade_time = t["trade_time"]
            price = t["price_per_mwh"]
            etype = t["energy_type"]
            vmonth = t["vintage_month"]

            base = {
                "transaction_id": tid,
                "rec_serial": rec_serial,
                "generator_id": gen_id,
                "buyer_id": buyer_id,
                "trade_date": trade_date,
            }

            # 1. EXPIRED_CERT
            cert = cert_map.get(gen_id)
            if cert:
                if (trade_date > cert["expiry_date"]
                        or cert["status"] != "active"):
                    anomalies.append({
                        **base,
                        "anomaly_type": "EXPIRED_CERT",
                        "severity": severity_map["EXPIRED_CERT"],
                        "details": (
                            f"Certificate {cert['cert_id']} status="
                            f"{cert['status']} expiry="
                            f"{cert['expiry_date']}"),
                    })

            # 2. OVER_GENERATION
            mr = mr_map.get((gen_id, vmonth))
            if mr:
                total_sold = gen_month_total[(gen_id, vmonth)]
                if total_sold > mr["total_generation_mwh"] * tolerance:
                    anomalies.append({
                        **base,
                        "anomaly_type": "OVER_GENERATION",
                        "severity": severity_map["OVER_GENERATION"],
                        "details": (
                            f"Sold {total_sold:.2f} MWh vs metered "
                            f"{mr['total_generation_mwh']:.2f} MWh "
                            f"(tolerance {tolerance})"),
                    })

            # 3. OFF_HOURS
            hour = int(trade_time.split(":")[0])
            if hour < start_hour or hour >= end_hour:
                anomalies.append({
                    **base,
                    "anomaly_type": "OFF_HOURS",
                    "severity": severity_map["OFF_HOURS"],
                    "details": (
                        f"Trade at {trade_time} outside "
                        f"{start_hour:02d}:00-{end_hour:02d}:00"),
                })

            # 4. PRICE_OUTLIER
            ref = price_ref.get((trade_date, etype))
            if ref:
                rp, rs = ref
                if abs(price - rp) > price_mult * rs:
                    anomalies.append({
                        **base,
                        "anomaly_type": "PRICE_OUTLIER",
                        "severity": severity_map["PRICE_OUTLIER"],
                        "details": (
                            f"Price {price:.2f} vs ref {rp:.2f} "
                            f"(threshold {price_mult}*{rs:.2f}="
                            f"{price_mult * rs:.2f})"),
                    })

            # 5. FAILED_VALIDATION
            vs = val_map.get((gen_id, vmonth))
            if vs == "FAIL":
                anomalies.append({
                    **base,
                    "anomaly_type": "FAILED_VALIDATION",
                    "severity": severity_map["FAILED_VALIDATION"],
                    "details": (
                        f"Meter validation FAIL for {gen_id} in "
                        f"{vmonth}"),
                })

            # 6. DOUBLE_COUNT
            if rec_serial in double_serials:
                claimants = sorted(serial_claimants[rec_serial])
                anomalies.append({
                    **base,
                    "anomaly_type": "DOUBLE_COUNT",
                    "severity": severity_map["DOUBLE_COUNT"],
                    "details": (
                        f"Serial {rec_serial} claimed by "
                        f"{', '.join(claimants)}"),
                })

        # Sort: severity HIGH > MEDIUM > LOW, then transaction_id
        sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        anomalies.sort(
            key=lambda a: (sev_order.get(a["severity"], 9),
                           a["transaction_id"]))
        return anomalies

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
        ground_truth = self._compute_ground_truth()

        # Build ground truth sets per anomaly type
        gt_by_type = defaultdict(set)
        for a in ground_truth:
            gt_by_type[a["anomaly_type"]].add(a["transaction_id"])

        all_gt_pairs = {(a["transaction_id"], a["anomaly_type"])
                        for a in ground_truth}

        # ── Read agent's anomaly report ────────────────────────────
        report_path = os.path.join(self.workspace, "anomaly_report.csv")
        agent_anomalies = []
        agent_by_type = defaultdict(set)
        agent_all_pairs = set()

        criteria = {}

        if not os.path.exists(report_path):
            criteria["report_file_exists"] = {
                "passed": False, "score": 0, "max_score": 10,
                "reason": "anomaly_report.csv not found in workspace",
            }
        else:
            try:
                with open(report_path, newline="") as f:
                    reader = csv.DictReader(f)
                    expected_cols = {
                        "transaction_id", "rec_serial", "generator_id",
                        "buyer_id", "trade_date", "anomaly_type",
                        "severity", "details",
                    }
                    if reader.fieldnames and expected_cols.issubset(
                            set(reader.fieldnames)):
                        col_ok = True
                    else:
                        col_ok = False
                    for row in reader:
                        agent_anomalies.append(row)
                        tid = row.get("transaction_id", "")
                        atype = row.get("anomaly_type", "")
                        agent_by_type[atype].add(tid)
                        agent_all_pairs.add((tid, atype))
            except Exception as e:
                col_ok = False

            if col_ok and len(agent_anomalies) > 0:
                criteria["report_file_exists"] = {
                    "passed": True, "score": 10, "max_score": 10,
                }
            else:
                reason = ("Missing required columns"
                          if not col_ok
                          else "Report is empty")
                criteria["report_file_exists"] = {
                    "passed": False, "score": 0, "max_score": 10,
                    "reason": reason,
                }

        # Helper for per-type recall scoring
        def _score_type(name, atype, max_pts):
            gt_set = gt_by_type.get(atype, set())
            if not gt_set:
                criteria[name] = {
                    "passed": True, "score": max_pts, "max_score": max_pts,
                }
                return
            agent_set = agent_by_type.get(atype, set())
            hits = len(gt_set & agent_set)
            recall = hits / len(gt_set)
            score = round(recall * max_pts, 1)
            passed = recall >= 0.8
            info_d = {
                "passed": passed,
                "score": score,
                "max_score": max_pts,
            }
            if not passed:
                info_d["reason"] = (
                    f"Detected {hits}/{len(gt_set)} "
                    f"(recall {recall:.2%})")
            criteria[name] = info_d

        _score_type("expired_cert_detection", "EXPIRED_CERT", 20)
        _score_type("over_generation_detection", "OVER_GENERATION", 20)
        _score_type("off_hours_detection", "OFF_HOURS", 15)
        _score_type("failed_validation_detection", "FAILED_VALIDATION", 15)
        _score_type("double_count_detection", "DOUBLE_COUNT", 10)

        # Precision check
        if agent_all_pairs:
            tp = len(agent_all_pairs & all_gt_pairs)
            precision = tp / len(agent_all_pairs)
        else:
            precision = 0.0
        prec_score = round(precision * 10, 1)
        criteria["precision"] = {
            "passed": precision >= 0.7,
            "score": prec_score,
            "max_score": 10,
        }
        if precision < 0.7:
            criteria["precision"]["reason"] = (
                f"Precision {precision:.2%} "
                f"({len(agent_all_pairs)} reported, "
                f"{len(agent_all_pairs & all_gt_pairs)} correct)")

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score if max_score else 0.0, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

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
        # 1. Read workspace config files
        with open(os.path.join(self.workspace, "trading_rules.json")) as f:
            trading_rules = json.load(f)
        with open(os.path.join(self.workspace,
                               "anomaly_thresholds.yaml")) as f:
            thresholds = yaml.safe_load(f)
        with open(os.path.join(self.workspace,
                               "certification_standards.md")) as f:
            _ = f.read()  # read for awareness

        start_hour = int(
            trading_rules["allowed_trading_hours"]["start"].split(":")[0])
        end_hour = int(
            trading_rules["allowed_trading_hours"]["end"].split(":")[0])
        tolerance = thresholds["over_generation_tolerance"]
        price_mult = thresholds["price_outlier_std_multiplier"]
        severity_map = thresholds["severity_levels"]

        # 2. Read meter validation reports
        val_map = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "meter_validation_batch_*.csv"))
        ):
            with open(fp, newline="") as f:
                for row in csv.DictReader(f):
                    val_map[(row["generator_id"], row["month"])] = (
                        row["validation_status"])

        # 3. Read buyer claims -> find double-counted serials
        serial_claimants = defaultdict(set)
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "buyer_claims_batch_*.yaml"))
        ):
            with open(fp) as f:
                claims = yaml.safe_load(f)
            for entry in claims:
                for serial in entry["claimed_rec_serials"]:
                    serial_claimants[serial].add(entry["buyer_id"])
        double_serials = {
            s for s, bset in serial_claimants.items() if len(bset) > 1
        }

        # 4. Read price index files
        price_ref = {}
        for fp in sorted(
            glob_mod.glob(
                os.path.join(self.workspace, "price_index_*.json"))
        ):
            with open(fp) as f:
                for rec in json.load(f):
                    price_ref[(rec["date"], rec["energy_type"])] = (
                        rec["reference_price"], rec["reference_std"])

        # 5. Retrieve all transactions via tool (paginated)
        all_txns = []
        tool_call_count = 0
        page = 1
        while True:
            result = self.tools["list_transactions"](page=page, page_size=50)
            tool_call_count += 1
            all_txns.extend(result["records"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 6. Collect unique generator IDs and get accreditations
        gen_ids = sorted({t["generator_id"] for t in all_txns})
        cert_map = {}
        for gid in gen_ids:
            cert_map[gid] = self.tools["get_accreditation"](
                generator_id=gid)
            tool_call_count += 1

        # 7. Aggregate qty per (gen, month), then get meter readings
        gen_month_total = defaultdict(float)
        for t in all_txns:
            gen_month_total[(t["generator_id"],
                             t["vintage_month"])] += t["quantity_mwh"]

        mr_map = {}
        for (gid, month) in gen_month_total:
            mr_map[(gid, month)] = self.tools["get_meter_reading"](
                generator_id=gid, month=month)
            tool_call_count += 1

        # 8. Detect anomalies
        anomalies = []
        for t in all_txns:
            tid = t["transaction_id"]
            gen_id = t["generator_id"]
            buyer_id = t["buyer_id"]
            trade_date = t["trade_date"]
            rec_serial = t["rec_serial"]
            trade_time = t["trade_time"]
            price = t["price_per_mwh"]
            etype = t["energy_type"]
            vmonth = t["vintage_month"]

            base = {
                "transaction_id": tid,
                "rec_serial": rec_serial,
                "generator_id": gen_id,
                "buyer_id": buyer_id,
                "trade_date": trade_date,
            }

            # EXPIRED_CERT
            cert = cert_map.get(gen_id, {})
            if "error" not in cert:
                if (trade_date > cert["expiry_date"]
                        or cert["status"] != "active"):
                    anomalies.append({
                        **base,
                        "anomaly_type": "EXPIRED_CERT",
                        "severity": severity_map["EXPIRED_CERT"],
                        "details": (
                            f"Certificate {cert['cert_id']} status="
                            f"{cert['status']} expiry="
                            f"{cert['expiry_date']}"),
                    })

            # OVER_GENERATION
            mr = mr_map.get((gen_id, vmonth), {})
            if "error" not in mr:
                total_sold = gen_month_total[(gen_id, vmonth)]
                if total_sold > mr["total_generation_mwh"] * tolerance:
                    anomalies.append({
                        **base,
                        "anomaly_type": "OVER_GENERATION",
                        "severity": severity_map["OVER_GENERATION"],
                        "details": (
                            f"Sold {total_sold:.2f} MWh vs metered "
                            f"{mr['total_generation_mwh']:.2f} MWh "
                            f"(tolerance {tolerance})"),
                    })

            # OFF_HOURS
            hour = int(trade_time.split(":")[0])
            if hour < start_hour or hour >= end_hour:
                anomalies.append({
                    **base,
                    "anomaly_type": "OFF_HOURS",
                    "severity": severity_map["OFF_HOURS"],
                    "details": (
                        f"Trade at {trade_time} outside "
                        f"{start_hour:02d}:00-{end_hour:02d}:00"),
                })

            # PRICE_OUTLIER
            ref = price_ref.get((trade_date, etype))
            if ref:
                rp, rs = ref
                if abs(price - rp) > price_mult * rs:
                    anomalies.append({
                        **base,
                        "anomaly_type": "PRICE_OUTLIER",
                        "severity": severity_map["PRICE_OUTLIER"],
                        "details": (
                            f"Price {price:.2f} vs ref {rp:.2f} "
                            f"(threshold {price_mult}*{rs:.2f}="
                            f"{price_mult * rs:.2f})"),
                    })

            # FAILED_VALIDATION
            vs = val_map.get((gen_id, vmonth))
            if vs == "FAIL":
                anomalies.append({
                    **base,
                    "anomaly_type": "FAILED_VALIDATION",
                    "severity": severity_map["FAILED_VALIDATION"],
                    "details": (
                        f"Meter validation FAIL for {gen_id} in "
                        f"{vmonth}"),
                })

            # DOUBLE_COUNT
            if rec_serial in double_serials:
                claimants = sorted(serial_claimants[rec_serial])
                anomalies.append({
                    **base,
                    "anomaly_type": "DOUBLE_COUNT",
                    "severity": severity_map["DOUBLE_COUNT"],
                    "details": (
                        f"Serial {rec_serial} claimed by "
                        f"{', '.join(claimants)}"),
                })

        # Sort: severity HIGH > MEDIUM > LOW, then transaction_id
        sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        anomalies.sort(
            key=lambda a: (sev_order.get(a["severity"], 9),
                           a["transaction_id"]))

        # 9. Write anomaly_report.csv
        report_path = os.path.join(self.workspace, "anomaly_report.csv")
        fieldnames = [
            "transaction_id", "rec_serial", "generator_id", "buyer_id",
            "trade_date", "anomaly_type", "severity", "details",
        ]
        with open(report_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(anomalies)

        # 10. Construct action summary
        type_counts = defaultdict(int)
        for a in anomalies:
            type_counts[a["anomaly_type"]] += 1
        unique_txns = len({a["transaction_id"] for a in anomalies})

        action = (
            f"Anomaly report generated with {len(anomalies)} anomaly "
            f"records across {unique_txns} unique transactions. "
            f"Breakdown by type: "
            + ", ".join(f"{k}: {v}" for k, v in sorted(type_counts.items()))
            + ". Report saved as anomaly_report.csv."
        )

        assert tool_call_count >= 15, (
            f"Only {tool_call_count} tool calls made; need >= 15")

        return self.step(action)
