import sqlite3
import os
import json
import csv
import re
import yaml
from typing import Tuple, Dict, List, Any
from datetime import datetime, timedelta


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

    # =========================================================================
    # TOOLS
    # =========================================================================

    @tool(
        description="Returns a paginated list of clients with basic info (client_id, name, tax_status, account_type).",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-indexed)",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of records per page (max 50)",
                },
            },
            "required": ["page"],
        },
    )
    def list_clients(self, page: int = 1, page_size: int = 20) -> dict:
        page_size = min(page_size, 50)
        offset = (page - 1) * page_size
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM clients")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT client_id, name, tax_status, account_type FROM clients "
            "ORDER BY client_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "page": page,
            "page_size": page_size,
            "total_clients": total,
            "clients": rows,
        }

    @tool(
        description="Returns full details for a single client including tax_status, filing_status, jurisdiction, and account_type.",
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": "The client identifier, e.g. C0001",
                },
            },
            "required": ["client_id"],
        },
    )
    def get_client_details(self, client_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Client {client_id} not found"}
        return dict(row)

    @tool(
        description="Returns lot-level cost basis records for a given client and security. Each record includes lot_id, purchase_date, quantity, cost_basis_per_share, and is_covered.",
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": "The client identifier",
                },
                "security_id": {
                    "type": "string",
                    "description": "The security identifier",
                },
            },
            "required": ["client_id", "security_id"],
        },
    )
    def get_tax_lots(self, client_id: str, security_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tax_lots WHERE client_id = ? AND security_id = ? "
            "ORDER BY cost_basis_per_share DESC",
            (client_id, security_id),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"client_id": client_id, "security_id": security_id, "lots": rows}

    @tool(
        description="Returns year-to-date capital gains records for a client, optionally filtered by security. Includes per-record details and a summary of total short-term and long-term gains.",
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": "The client identifier",
                },
                "security_id": {
                    "type": "string",
                    "description": "Optional security filter",
                },
            },
            "required": ["client_id"],
        },
    )
    def get_ytd_capital_gains(self, client_id: str, security_id: str = None) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if security_id:
            cur.execute(
                "SELECT * FROM capital_gains_ytd WHERE client_id = ? AND security_id = ? "
                "ORDER BY sale_date DESC",
                (client_id, security_id),
            )
        else:
            cur.execute(
                "SELECT * FROM capital_gains_ytd WHERE client_id = ? ORDER BY sale_date DESC",
                (client_id,),
            )
        records = [dict(r) for r in cur.fetchall()]
        st_gains = sum(
            r["realized_gain"]
            for r in records
            if r["holding_period"] == "short_term" and r["realized_gain"] > 0
        )
        lt_gains = sum(
            r["realized_gain"]
            for r in records
            if r["holding_period"] == "long_term" and r["realized_gain"] > 0
        )
        conn.close()
        return {
            "client_id": client_id,
            "summary": {
                "total_short_term_gains": round(st_gains, 2),
                "total_long_term_gains": round(lt_gains, 2),
            },
            "records": records,
        }

    @tool(
        description="Returns recent transaction history (buys and sells) for a client and security since a given date.",
        parameters={
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                    "description": "The client identifier",
                },
                "security_id": {
                    "type": "string",
                    "description": "The security identifier",
                },
                "since_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format; only transactions on or after this date are returned",
                },
            },
            "required": ["client_id", "security_id", "since_date"],
        },
    )
    def get_transaction_history(
        self, client_id: str, security_id: str, since_date: str
    ) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM transaction_history "
            "WHERE client_id = ? AND security_id = ? AND txn_date >= ? "
            "ORDER BY txn_date DESC",
            (client_id, security_id, since_date),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "client_id": client_id,
            "security_id": security_id,
            "since_date": since_date,
            "transactions": rows,
        }

    @tool(
        description="Returns details for a security including ticker, name, sector, asset_class, and current_price.",
        parameters={
            "type": "object",
            "properties": {
                "security_id": {
                    "type": "string",
                    "description": "The security identifier, e.g. SEC0001",
                },
            },
            "required": ["security_id"],
        },
    )
    def get_security_info(self, security_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM securities WHERE security_id = ?", (security_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"error": f"Security {security_id} not found"}
        return dict(row)

    # =========================================================================
    # GROUND TRUTH
    # =========================================================================

    def _read_config(self):
        with open(os.path.join(self.workspace, "tax_rates.json")) as f:
            tax_rates = json.load(f)
        with open(os.path.join(self.workspace, "wash_sale_rules.yaml")) as f:
            wash_rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "rebalancing_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        return tax_rates, wash_rules, policy

    def _read_proposed_trades(self):
        trades = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("proposed_trades_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row["proposed_quantity"] = float(row["proposed_quantity"])
                        row["urgency"] = int(row["urgency"])
                        trades.append(row)
        return trades

    @staticmethod
    def _filing_multiplier(filing_status: str) -> float:
        return {"single": 1.0, "married_joint": 1.25, "married_separate": 0.75}.get(
            filing_status, 1.0
        )

    def _compute_ground_truth(self):
        """Compute the correct execution schedule from DB + workspace."""
        tax_rates, wash_rules, policy = self._read_config()
        trades = self._read_proposed_trades()

        ref_date = datetime.strptime(policy["reference_date"], "%Y-%m-%d")
        base_exec = policy["base_execution_date"]
        defer_date = policy["defer_date"]
        lt_days = policy["holding_period_long_term_days"]
        max_st = policy["max_ytd_short_term_gain_per_client"]
        max_lt = policy["max_ytd_long_term_gain_per_client"]
        lookback = wash_rules["federal"]["lookback_days"]
        since_date = (ref_date - timedelta(days=lookback)).strftime("%Y-%m-%d")

        st_rate = tax_rates["short_term_federal_rate"]
        lt_rate = tax_rates["long_term_federal_rate"]
        state_rates = tax_rates["state_rates"]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        schedule = []
        for trade in trades:
            tid = trade["trade_id"]
            cid = trade["client_id"]
            sid = trade["security_id"]
            action = trade["action"]
            qty = trade["proposed_quantity"]

            cur = conn.cursor()

            # --- client info ---
            cur.execute("SELECT * FROM clients WHERE client_id = ?", (cid,))
            client = dict(cur.fetchone())
            s_rate = state_rates.get(client["jurisdiction"], 0.0)

            # --- TAX_ADVANTAGED check ---
            if client["tax_status"] in ("tax_deferred", "tax_exempt"):
                schedule.append(self._make_entry(
                    tid, cid, sid, action, qty, base_exec,
                    "TAX_ADVANTAGED",
                    f"Account is {client['tax_status']}; no tax impact",
                    "", 0.0,
                ))
                continue

            # --- security price ---
            cur.execute(
                "SELECT current_price FROM securities WHERE security_id = ?", (sid,)
            )
            row = cur.fetchone()
            current_price = row["current_price"] if row else 0.0

            if action == "sell":
                entry = self._eval_sell(
                    cur, tid, cid, sid, qty, client, current_price,
                    ref_date, lt_days, lookback, since_date, base_exec,
                    defer_date, max_st, max_lt, st_rate, lt_rate, s_rate,
                )
            else:  # buy
                entry = self._eval_buy(
                    cur, tid, cid, sid, qty, since_date, lookback,
                    base_exec, ref_date,
                )
            schedule.append(entry)

        conn.close()
        schedule.sort(key=lambda x: (x["execution_date"], x["trade_id"]))
        return schedule

    # --------------------------------------------------------------------- sell
    def _eval_sell(
        self, cur, tid, cid, sid, qty, client, current_price,
        ref_date, lt_days, lookback, since_date, base_exec,
        defer_date, max_st, max_lt, st_rate, lt_rate, s_rate,
    ):
        # Lots sorted by cost_basis_per_share DESC (highest first)
        cur.execute(
            "SELECT * FROM tax_lots WHERE client_id = ? AND security_id = ? "
            "ORDER BY cost_basis_per_share DESC",
            (cid, sid),
        )
        lots = [dict(r) for r in cur.fetchall()]

        # Select lots
        selected = []
        remaining = qty
        for lot in lots:
            if remaining <= 0:
                break
            use = min(lot["quantity"], remaining)
            selected.append((lot, use))
            remaining -= use
        actual_qty = qty - max(remaining, 0)

        if not selected:
            return self._make_entry(
                tid, cid, sid, "sell", actual_qty, base_exec,
                "PASS", "No lots available for this security", "", 0.0,
            )

        # Compute gain components & tax
        total_tax = 0.0
        total_gain = 0.0
        trade_st_gain = 0.0
        trade_lt_gain = 0.0
        has_short = False
        selected_ids = set()

        for lot, use in selected:
            gain = (current_price - lot["cost_basis_per_share"]) * use
            total_gain += gain
            pdate = datetime.strptime(lot["purchase_date"], "%Y-%m-%d")
            held = (ref_date - pdate).days
            if held >= lt_days:
                rate = lt_rate + s_rate
                if gain > 0:
                    trade_lt_gain += gain
            else:
                rate = st_rate + s_rate
                has_short = True
                if gain > 0:
                    trade_st_gain += gain
            total_tax += gain * rate
            selected_ids.add(lot["lot_id"])

        lot_id_str = "|".join(lot["lot_id"] for lot, _ in selected)
        total_tax = round(total_tax, 2)

        # --- flag determination (priority: WASH_SALE > EXCESSIVE_GAIN > SUBOPTIMAL_LOT > PASS) ---
        flag = "PASS"
        flag_reason = "No tax efficiency issues detected"
        exec_date = base_exec

        # 1) Wash sale check (sell at loss + recent buy)
        if total_gain < 0:
            cur.execute(
                "SELECT * FROM transaction_history "
                "WHERE client_id = ? AND security_id = ? AND txn_type = 'buy' "
                "AND txn_date >= ? ORDER BY txn_date DESC",
                (cid, sid, since_date),
            )
            recent_buys = [dict(r) for r in cur.fetchall()]
            if recent_buys:
                flag = "WASH_SALE_RISK"
                latest = recent_buys[0]["txn_date"]
                flag_reason = (
                    f"Recent buy of {sid} on {latest} within "
                    f"{lookback}-day wash sale window; selling at a loss triggers wash sale"
                )
                deferred = (
                    datetime.strptime(latest, "%Y-%m-%d")
                    + timedelta(days=lookback + 1)
                ).strftime("%Y-%m-%d")
                exec_date = max(deferred, base_exec)

        # 2) If gain and not already flagged
        if flag == "PASS" and total_gain >= 0:
            mult = self._filing_multiplier(client["filing_status"])
            adj_st = max_st * mult
            adj_lt = max_lt * mult

            cur.execute(
                "SELECT realized_gain, holding_period FROM capital_gains_ytd "
                "WHERE client_id = ? AND realized_gain > 0",
                (cid,),
            )
            ytd_rows = cur.fetchall()
            ytd_st = sum(r[0] for r in ytd_rows if r[1] == "short_term")
            ytd_lt = sum(r[0] for r in ytd_rows if r[1] == "long_term")

            if (trade_st_gain > 0 and ytd_st + trade_st_gain > adj_st) or (
                trade_lt_gain > 0 and ytd_lt + trade_lt_gain > adj_lt
            ):
                flag = "EXCESSIVE_GAIN"
                flag_reason = (
                    f"YTD ST gains {ytd_st:.2f} + trade ST {trade_st_gain:.2f} "
                    f"vs threshold {adj_st:.2f}; "
                    f"YTD LT gains {ytd_lt:.2f} + trade LT {trade_lt_gain:.2f} "
                    f"vs threshold {adj_lt:.2f}"
                )
                exec_date = defer_date
            else:
                # 3) Suboptimal lot check
                has_unselected_lt = False
                for lot in lots:
                    if lot["lot_id"] not in selected_ids:
                        pdate = datetime.strptime(lot["purchase_date"], "%Y-%m-%d")
                        if (ref_date - pdate).days >= lt_days:
                            has_unselected_lt = True
                            break
                if has_short and has_unselected_lt and total_gain > 0:
                    flag = "SUBOPTIMAL_LOT"
                    flag_reason = (
                        "Short-term lots included in selection while unselected "
                        "long-term lots exist; higher tax rate applies to gains"
                    )

        return self._make_entry(
            tid, cid, sid, "sell", actual_qty, exec_date,
            flag, flag_reason, lot_id_str, total_tax,
        )

    # ---------------------------------------------------------------------- buy
    def _eval_buy(
        self, cur, tid, cid, sid, qty, since_date, lookback,
        base_exec, ref_date,
    ):
        # Check for recent loss sale -> wash sale risk
        cur.execute(
            "SELECT * FROM capital_gains_ytd "
            "WHERE client_id = ? AND security_id = ? AND realized_gain < 0 "
            "AND sale_date >= ? ORDER BY sale_date DESC",
            (cid, sid, since_date),
        )
        loss_records = [dict(r) for r in cur.fetchall()]

        flag = "PASS"
        flag_reason = "No tax efficiency issues detected"
        exec_date = base_exec

        if loss_records:
            flag = "WASH_SALE_RISK"
            latest = loss_records[0]["sale_date"]
            flag_reason = (
                f"Recent loss sale of {sid} on {latest} within "
                f"{lookback}-day window; buying would trigger wash sale on the loss"
            )
            deferred = (
                datetime.strptime(latest, "%Y-%m-%d")
                + timedelta(days=lookback + 1)
            ).strftime("%Y-%m-%d")
            exec_date = max(deferred, base_exec)

        return self._make_entry(
            tid, cid, sid, "buy", qty, exec_date,
            flag, flag_reason, "", 0.0,
        )

    @staticmethod
    def _make_entry(tid, cid, sid, action, qty, exec_date, flag, reason, lots, tax):
        return {
            "trade_id": tid,
            "client_id": cid,
            "security_id": sid,
            "action": action,
            "quantity": round(qty, 2),
            "execution_date": exec_date,
            "flag": flag,
            "flag_reason": reason,
            "recommended_lot_ids": lots,
            "estimated_tax_impact": round(tax, 2),
        }

    # =========================================================================
    # STEP
    # =========================================================================

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
        gt = self._compute_ground_truth()
        gt_map = {e["trade_id"]: e for e in gt}
        total_trades = len(gt)

        criteria = {}

        # --- 1. Schedule file format (10 pts) ---
        sched_path = os.path.join(self.workspace, "execution_schedule.csv")
        expected_cols = [
            "trade_id", "client_id", "security_id", "action", "quantity",
            "execution_date", "flag", "flag_reason", "recommended_lot_ids",
            "estimated_tax_impact",
        ]
        agent_rows = []
        fmt_ok = True
        fmt_reason = ""
        if not os.path.exists(sched_path):
            fmt_ok = False
            fmt_reason = "execution_schedule.csv not found"
        else:
            try:
                with open(sched_path) as f:
                    reader = csv.DictReader(f)
                    file_cols = reader.fieldnames or []
                    missing = [c for c in expected_cols if c not in file_cols]
                    if missing:
                        fmt_ok = False
                        fmt_reason = f"Missing columns: {missing}"
                    for row in reader:
                        agent_rows.append(row)
                    if len(agent_rows) != total_trades:
                        fmt_ok = False
                        fmt_reason += (
                            f"; row count mismatch: expected {total_trades}, "
                            f"got {len(agent_rows)}"
                        )
            except Exception as exc:
                fmt_ok = False
                fmt_reason = f"Error reading CSV: {exc}"

        criteria["schedule_file_format"] = {
            "passed": fmt_ok,
            "score": 10 if fmt_ok else 0,
            "max_score": 10,
            "reason": fmt_reason if not fmt_ok else "",
        }

        # Build agent map
        agent_map = {}
        for r in agent_rows:
            agent_map[r.get("trade_id", "")] = r

        # --- 2. Flag accuracy (25 pts) ---
        flag_correct = 0
        flag_total = total_trades
        for tid, gt_e in gt_map.items():
            ar = agent_map.get(tid)
            if ar and ar.get("flag", "").strip() == gt_e["flag"]:
                flag_correct += 1
        flag_score = round(25 * flag_correct / max(flag_total, 1))
        criteria["flag_accuracy"] = {
            "passed": flag_correct == flag_total,
            "score": flag_score,
            "max_score": 25,
            "reason": (
                f"{flag_correct}/{flag_total} flags correct"
                if flag_correct < flag_total
                else ""
            ),
        }

        # --- 3. Lot recommendation accuracy (20 pts) ---
        lot_total = 0
        lot_correct = 0
        for tid, gt_e in gt_map.items():
            if gt_e["action"] != "sell" or not gt_e["recommended_lot_ids"]:
                continue
            lot_total += 1
            ar = agent_map.get(tid)
            if ar and ar.get("recommended_lot_ids", "").strip() == gt_e["recommended_lot_ids"]:
                lot_correct += 1
        lot_score = round(20 * lot_correct / max(lot_total, 1))
        criteria["lot_recommendation_accuracy"] = {
            "passed": lot_correct == lot_total,
            "score": lot_score,
            "max_score": 20,
            "reason": (
                f"{lot_correct}/{lot_total} lot selections correct"
                if lot_correct < lot_total
                else ""
            ),
        }

        # --- 4. Tax impact accuracy (20 pts) ---
        tax_total = total_trades
        tax_correct = 0
        for tid, gt_e in gt_map.items():
            ar = agent_map.get(tid)
            if ar:
                try:
                    agent_tax = float(ar.get("estimated_tax_impact", "nan"))
                except (ValueError, TypeError):
                    agent_tax = float("nan")
                gt_tax = gt_e["estimated_tax_impact"]
                if abs(gt_tax) < 1e-6:
                    if abs(agent_tax) < 1.0:
                        tax_correct += 1
                elif abs(agent_tax - gt_tax) <= max(1.0, abs(gt_tax) * 0.02):
                    tax_correct += 1
        tax_score = round(20 * tax_correct / max(tax_total, 1))
        criteria["tax_impact_accuracy"] = {
            "passed": tax_correct == tax_total,
            "score": tax_score,
            "max_score": 20,
            "reason": (
                f"{tax_correct}/{tax_total} tax impacts within tolerance"
                if tax_correct < tax_total
                else ""
            ),
        }

        # --- 5. Execution date accuracy (10 pts) ---
        date_correct = 0
        for tid, gt_e in gt_map.items():
            ar = agent_map.get(tid)
            if ar and ar.get("execution_date", "").strip() == gt_e["execution_date"]:
                date_correct += 1
        date_score = round(10 * date_correct / max(total_trades, 1))
        criteria["execution_date_accuracy"] = {
            "passed": date_correct == total_trades,
            "score": date_score,
            "max_score": 10,
            "reason": (
                f"{date_correct}/{total_trades} dates correct"
                if date_correct < total_trades
                else ""
            ),
        }

        # --- 6. Response summary accuracy (15 pts) ---
        gt_flags = {}
        for e in gt:
            gt_flags[e["flag"]] = gt_flags.get(e["flag"], 0) + 1
        gt_flagged = (
            gt_flags.get("WASH_SALE_RISK", 0)
            + gt_flags.get("EXCESSIVE_GAIN", 0)
            + gt_flags.get("SUBOPTIMAL_LOT", 0)
        )
        gt_total_tax = round(sum(e["estimated_tax_impact"] for e in gt), 2)

        expected = {
            "Total trades": total_trades,
            "Flagged trades": gt_flagged,
            "WASH_SALE_RISK": gt_flags.get("WASH_SALE_RISK", 0),
            "EXCESSIVE_GAIN": gt_flags.get("EXCESSIVE_GAIN", 0),
            "SUBOPTIMAL_LOT": gt_flags.get("SUBOPTIMAL_LOT", 0),
            "TAX_ADVANTAGED": gt_flags.get("TAX_ADVANTAGED", 0),
            "PASS": gt_flags.get("PASS", 0),
        }

        summary_hits = 0
        summary_total = len(expected) + 1  # +1 for tax impact
        for label, val in expected.items():
            m = re.search(rf"{re.escape(label)}:\s*(\d+)", action or "")
            if m and int(m.group(1)) == val:
                summary_hits += 1

        tax_m = re.search(
            r"Total estimated tax impact:\s*\$?([\d,.\-]+)", action or ""
        )
        if tax_m:
            try:
                agent_total_tax = float(tax_m.group(1).replace(",", ""))
                if abs(agent_total_tax - gt_total_tax) <= max(1.0, abs(gt_total_tax) * 0.02):
                    summary_hits += 1
            except ValueError:
                pass

        summary_score = round(15 * summary_hits / summary_total)
        criteria["response_summary"] = {
            "passed": summary_hits == summary_total,
            "score": summary_score,
            "max_score": 15,
            "reason": (
                f"{summary_hits}/{summary_total} summary items correct"
                if summary_hits < summary_total
                else ""
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return total_score / max_score, info

    # =========================================================================
    # VERIFY
    # =========================================================================

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
        # --- 1. Read config files ---
        with open(os.path.join(self.workspace, "tax_rates.json")) as f:
            tax_rates = json.load(f)
        with open(os.path.join(self.workspace, "wash_sale_rules.yaml")) as f:
            wash_rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "rebalancing_policy.yaml")) as f:
            policy = yaml.safe_load(f)
        # gain_threshold_adjustments.md -> filing-status multipliers
        # (already encoded in _filing_multiplier, read for proof-of-concept)
        with open(os.path.join(self.workspace, "gain_threshold_adjustments.md")) as f:
            _ = f.read()

        ref_date_str = policy["reference_date"]
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
        base_exec = policy["base_execution_date"]
        defer_date = policy["defer_date"]
        lt_days = policy["holding_period_long_term_days"]
        max_st = policy["max_ytd_short_term_gain_per_client"]
        max_lt = policy["max_ytd_long_term_gain_per_client"]
        lookback = wash_rules["federal"]["lookback_days"]
        since_date = (ref_date - timedelta(days=lookback)).strftime("%Y-%m-%d")

        st_rate_fed = tax_rates["short_term_federal_rate"]
        lt_rate_fed = tax_rates["long_term_federal_rate"]
        state_rates = tax_rates["state_rates"]

        # --- 2. Read proposed trade files ---
        trades = []
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("proposed_trades_batch_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row["proposed_quantity"] = float(row["proposed_quantity"])
                        trades.append(row)

        # --- 3. Gather client list ---
        all_clients = {}
        page = 1
        while True:
            resp = self.tools["list_clients"](page=page, page_size=50)
            for c in resp["clients"]:
                all_clients[c["client_id"]] = c
            if page * 50 >= resp["total_clients"]:
                break
            page += 1

        # --- 4. Collect unique IDs ---
        client_ids_needed = set(t["client_id"] for t in trades)
        security_ids_needed = set(t["security_id"] for t in trades)

        # Client details cache
        client_details = {}
        for cid in client_ids_needed:
            client_details[cid] = self.tools["get_client_details"](client_id=cid)

        # Security info cache
        sec_info = {}
        for sid in security_ids_needed:
            sec_info[sid] = self.tools["get_security_info"](security_id=sid)

        # YTD gains cache (per client)
        ytd_cache = {}
        for cid in client_ids_needed:
            ytd_cache[cid] = self.tools["get_ytd_capital_gains"](client_id=cid)

        # --- 5. Process each trade ---
        schedule = []
        for trade in trades:
            tid = trade["trade_id"]
            cid = trade["client_id"]
            sid = trade["security_id"]
            action = trade["action"]
            qty = trade["proposed_quantity"]

            client = client_details[cid]
            s_rate = state_rates.get(client["jurisdiction"], 0.0)
            current_price = sec_info[sid]["current_price"]

            # TAX_ADVANTAGED
            if client["tax_status"] in ("tax_deferred", "tax_exempt"):
                schedule.append(self._make_entry(
                    tid, cid, sid, action, qty, base_exec,
                    "TAX_ADVANTAGED",
                    f"Account is {client['tax_status']}; no tax impact",
                    "", 0.0,
                ))
                continue

            if action == "sell":
                # Get lots via tool
                lot_resp = self.tools["get_tax_lots"](
                    client_id=cid, security_id=sid
                )
                lots = lot_resp["lots"]  # already sorted by cost desc

                # Select lots
                selected = []
                remaining = qty
                for lot in lots:
                    if remaining <= 0:
                        break
                    use = min(lot["quantity"], remaining)
                    selected.append((lot, use))
                    remaining -= use
                actual_qty = qty - max(remaining, 0)

                if not selected:
                    schedule.append(self._make_entry(
                        tid, cid, sid, "sell", actual_qty, base_exec,
                        "PASS", "No lots available for this security", "", 0.0,
                    ))
                    continue

                # Compute gains & tax
                total_tax = 0.0
                total_gain = 0.0
                trade_st_gain = 0.0
                trade_lt_gain = 0.0
                has_short = False
                selected_ids = set()

                for lot, use in selected:
                    gain = (current_price - lot["cost_basis_per_share"]) * use
                    total_gain += gain
                    pdate = datetime.strptime(lot["purchase_date"], "%Y-%m-%d")
                    held = (ref_date - pdate).days
                    if held >= lt_days:
                        rate = lt_rate_fed + s_rate
                        if gain > 0:
                            trade_lt_gain += gain
                    else:
                        rate = st_rate_fed + s_rate
                        has_short = True
                        if gain > 0:
                            trade_st_gain += gain
                    total_tax += gain * rate
                    selected_ids.add(lot["lot_id"])

                lot_id_str = "|".join(lot["lot_id"] for lot, _ in selected)
                total_tax = round(total_tax, 2)

                flag = "PASS"
                flag_reason = "No tax efficiency issues detected"
                exec_date = base_exec

                # Wash sale (sell at loss + recent buy)
                if total_gain < 0:
                    txn_resp = self.tools["get_transaction_history"](
                        client_id=cid, security_id=sid, since_date=since_date,
                    )
                    recent_buys = [
                        t for t in txn_resp["transactions"] if t["txn_type"] == "buy"
                    ]
                    if recent_buys:
                        flag = "WASH_SALE_RISK"
                        latest = recent_buys[0]["txn_date"]
                        flag_reason = (
                            f"Recent buy of {sid} on {latest} within "
                            f"{lookback}-day wash sale window; "
                            f"selling at a loss triggers wash sale"
                        )
                        deferred = (
                            datetime.strptime(latest, "%Y-%m-%d")
                            + timedelta(days=lookback + 1)
                        ).strftime("%Y-%m-%d")
                        exec_date = max(deferred, base_exec)

                if flag == "PASS" and total_gain >= 0:
                    mult = self._filing_multiplier(client["filing_status"])
                    adj_st = max_st * mult
                    adj_lt = max_lt * mult

                    ytd_data = ytd_cache[cid]
                    ytd_st = ytd_data["summary"]["total_short_term_gains"]
                    ytd_lt = ytd_data["summary"]["total_long_term_gains"]

                    if (trade_st_gain > 0 and ytd_st + trade_st_gain > adj_st) or (
                        trade_lt_gain > 0 and ytd_lt + trade_lt_gain > adj_lt
                    ):
                        flag = "EXCESSIVE_GAIN"
                        flag_reason = (
                            f"YTD ST gains {ytd_st:.2f} + trade ST "
                            f"{trade_st_gain:.2f} vs threshold {adj_st:.2f}; "
                            f"YTD LT gains {ytd_lt:.2f} + trade LT "
                            f"{trade_lt_gain:.2f} vs threshold {adj_lt:.2f}"
                        )
                        exec_date = defer_date
                    else:
                        has_unselected_lt = False
                        for lot in lots:
                            if lot["lot_id"] not in selected_ids:
                                pdate = datetime.strptime(
                                    lot["purchase_date"], "%Y-%m-%d"
                                )
                                if (ref_date - pdate).days >= lt_days:
                                    has_unselected_lt = True
                                    break
                        if has_short and has_unselected_lt and total_gain > 0:
                            flag = "SUBOPTIMAL_LOT"
                            flag_reason = (
                                "Short-term lots included in selection while "
                                "unselected long-term lots exist; higher tax "
                                "rate applies to gains"
                            )

                schedule.append(self._make_entry(
                    tid, cid, sid, "sell", actual_qty, exec_date,
                    flag, flag_reason, lot_id_str, total_tax,
                ))

            else:  # buy
                # Wash sale: recent loss sale of same security
                ytd_data = ytd_cache[cid]
                loss_records = [
                    r for r in ytd_data["records"]
                    if r["security_id"] == sid
                    and r["realized_gain"] < 0
                    and r["sale_date"] >= since_date
                ]
                flag = "PASS"
                flag_reason = "No tax efficiency issues detected"
                exec_date = base_exec

                if loss_records:
                    flag = "WASH_SALE_RISK"
                    latest = max(r["sale_date"] for r in loss_records)
                    flag_reason = (
                        f"Recent loss sale of {sid} on {latest} within "
                        f"{lookback}-day window; buying would trigger "
                        f"wash sale on the loss"
                    )
                    deferred = (
                        datetime.strptime(latest, "%Y-%m-%d")
                        + timedelta(days=lookback + 1)
                    ).strftime("%Y-%m-%d")
                    exec_date = max(deferred, base_exec)

                schedule.append(self._make_entry(
                    tid, cid, sid, "buy", qty, exec_date,
                    flag, flag_reason, "", 0.0,
                ))

        # --- 6. Sort & write schedule ---
        schedule.sort(key=lambda x: (x["execution_date"], x["trade_id"]))

        sched_path = os.path.join(self.workspace, "execution_schedule.csv")
        fieldnames = [
            "trade_id", "client_id", "security_id", "action", "quantity",
            "execution_date", "flag", "flag_reason", "recommended_lot_ids",
            "estimated_tax_impact",
        ]
        with open(sched_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(schedule)

        # --- 7. Build summary response ---
        flag_counts = {}
        for e in schedule:
            flag_counts[e["flag"]] = flag_counts.get(e["flag"], 0) + 1
        flagged = (
            flag_counts.get("WASH_SALE_RISK", 0)
            + flag_counts.get("EXCESSIVE_GAIN", 0)
            + flag_counts.get("SUBOPTIMAL_LOT", 0)
        )
        total_tax = round(sum(e["estimated_tax_impact"] for e in schedule), 2)

        action_str = (
            f"Total trades: {len(schedule)}\n"
            f"Flagged trades: {flagged}\n"
            f"WASH_SALE_RISK: {flag_counts.get('WASH_SALE_RISK', 0)}\n"
            f"EXCESSIVE_GAIN: {flag_counts.get('EXCESSIVE_GAIN', 0)}\n"
            f"SUBOPTIMAL_LOT: {flag_counts.get('SUBOPTIMAL_LOT', 0)}\n"
            f"TAX_ADVANTAGED: {flag_counts.get('TAX_ADVANTAGED', 0)}\n"
            f"PASS: {flag_counts.get('PASS', 0)}\n"
            f"Total estimated tax impact: ${total_tax:.2f}\n"
        )

        return self.step(action_str)
