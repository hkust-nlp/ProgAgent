"""Pilot duty-time compliance and fatigue-risk environment."""

from typing import Tuple, Dict, List, Any
import sqlite3
import os
import re
import json
import csv
import math
from datetime import datetime, timedelta, date


# ---------------------------------------------------------------------------
# YAML helper – works with or without PyYAML
# ---------------------------------------------------------------------------
try:
    import yaml as _yaml
except ImportError:
    _yaml = None


def _safe_load_yaml(path):
    with open(path, "r") as fh:
        text = fh.read()
    if _yaml is not None:
        return _yaml.safe_load(text)
    # ---- minimal fallback parser for our simple config YAML ----
    result: dict = {}
    section = None
    for raw in text.split("\n"):
        line = raw.split("#")[0].rstrip()
        if not line:
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, val = stripped.split(":", 1)
        key = key.strip()
        val = val.strip()
        if indent == 0:
            if val == "":
                section = key
                result[section] = {}
            else:
                section = None
                try:
                    result[key] = float(val)
                except ValueError:
                    result[key] = val
        else:
            if section is not None:
                try:
                    result[section][key] = float(val)
                except ValueError:
                    result[section][key] = val
    return result


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------

def tool(description: str, parameters: dict):
    def decorator(func):
        func._tool_info = {
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# =========================================================================
# Task_Env
# =========================================================================

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

    # ===================== DB helper =====================

    def _db_query(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    # ===================== TOOLS =====================

    @tool(
        description="List pilots with pagination. Returns pilot IDs, names, and employee numbers.",
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number (1-based)",
                    "minimum": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page (max 20)",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["page", "page_size"],
        },
    )
    def list_pilots(self, page: int, page_size: int):
        page_size = min(int(page_size), 20)
        page = int(page)
        offset = (page - 1) * page_size
        total = self._db_query("SELECT COUNT(*) AS cnt FROM pilots")[0]["cnt"]
        rows = self._db_query(
            "SELECT pilot_id, name, employee_number FROM pilots "
            "ORDER BY pilot_id LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        return {
            "pilots": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size),
        }

    @tool(
        description="Get full details for a single pilot by ID.",
        parameters={
            "type": "object",
            "properties": {
                "pilot_id": {
                    "type": "integer",
                    "description": "Pilot unique ID",
                }
            },
            "required": ["pilot_id"],
        },
    )
    def get_pilot_details(self, pilot_id: int):
        rows = self._db_query(
            "SELECT * FROM pilots WHERE pilot_id = ?", (int(pilot_id),)
        )
        return rows[0] if rows else {"error": f"Pilot {pilot_id} not found"}

    @tool(
        description="Get crew pairings (scheduled duty assignments) for a pilot in a date range.",
        parameters={
            "type": "object",
            "properties": {
                "pilot_id": {
                    "type": "integer",
                    "description": "Pilot unique ID",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD",
                },
            },
            "required": ["pilot_id", "start_date", "end_date"],
        },
    )
    def get_pilot_pairings(self, pilot_id: int, start_date: str, end_date: str):
        rows = self._db_query(
            "SELECT pairing_id, pairing_code, report_time, release_time, "
            "duty_type, origin, destination "
            "FROM crew_pairings "
            "WHERE pilot_id = ? AND date(report_time) >= ? AND date(report_time) <= ? "
            "ORDER BY report_time",
            (int(pilot_id), start_date, end_date),
        )
        return {"pilot_id": int(pilot_id), "pairings": rows}

    @tool(
        description="Get actual flight log entries for a pilot in a date range.",
        parameters={
            "type": "object",
            "properties": {
                "pilot_id": {
                    "type": "integer",
                    "description": "Pilot unique ID",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD",
                },
            },
            "required": ["pilot_id", "start_date", "end_date"],
        },
    )
    def get_pilot_flight_logs(self, pilot_id: int, start_date: str, end_date: str):
        rows = self._db_query(
            "SELECT log_id, pairing_id, flight_number, "
            "scheduled_departure, actual_departure, "
            "scheduled_arrival, actual_arrival, origin, destination "
            "FROM flight_logs "
            "WHERE pilot_id = ? "
            "AND date(scheduled_departure) >= ? AND date(scheduled_departure) <= ? "
            "ORDER BY scheduled_departure",
            (int(pilot_id), start_date, end_date),
        )
        return {"pilot_id": int(pilot_id), "flights": rows}

    @tool(
        description="Get rest-period declarations for a pilot in a date range.",
        parameters={
            "type": "object",
            "properties": {
                "pilot_id": {
                    "type": "integer",
                    "description": "Pilot unique ID",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD",
                },
            },
            "required": ["pilot_id", "start_date", "end_date"],
        },
    )
    def get_pilot_rest_records(self, pilot_id: int, start_date: str, end_date: str):
        rows = self._db_query(
            "SELECT declaration_id, rest_start, rest_end, location, "
            "facility_type, self_reported_quality "
            "FROM rest_declarations "
            "WHERE pilot_id = ? AND date(rest_start) >= ? AND date(rest_start) <= ? "
            "ORDER BY rest_start",
            (int(pilot_id), start_date, end_date),
        )
        return {"pilot_id": int(pilot_id), "rest_records": rows}

    @tool(
        description="Get full details of a single crew pairing by pairing ID.",
        parameters={
            "type": "object",
            "properties": {
                "pairing_id": {
                    "type": "integer",
                    "description": "Pairing unique ID",
                }
            },
            "required": ["pairing_id"],
        },
    )
    def get_pairing_details(self, pairing_id: int):
        rows = self._db_query(
            "SELECT * FROM crew_pairings WHERE pairing_id = ?", (int(pairing_id),)
        )
        return rows[0] if rows else {"error": f"Pairing {pairing_id} not found"}

    # ===================== CONFIG / DATA LOADERS =====================

    def _load_config(self):
        cfg = os.path.join(self.workspace, "config")
        reg = _safe_load_yaml(os.path.join(cfg, "regulatory_limits.yaml"))
        sev = _safe_load_yaml(os.path.join(cfg, "severity_thresholds.yaml"))
        with open(os.path.join(cfg, "fatigue_risk_weights.json")) as f:
            frw = json.load(f)
        with open(os.path.join(cfg, "duty_type_rules.json")) as f:
            dtr = json.load(f)
        return {"regulatory": reg, "severity": sev, "fatigue_weights": frw, "duty_type_rules": dtr}

    def _load_amendments(self):
        """Return dict  pairing_code -> new_release_time."""
        amd_dir = os.path.join(self.workspace, "amendments")
        out: Dict[str, str] = {}
        if not os.path.isdir(amd_dir):
            return out
        for fn in sorted(os.listdir(amd_dir)):
            if fn.endswith(".json"):
                with open(os.path.join(amd_dir, fn)) as f:
                    for a in json.load(f):
                        out[a["pairing_code"]] = a["new_release_time"]
        return out

    def _load_prior_hours(self):
        """Return dict  (pilot_id, date_str) -> duty_hours."""
        ph_dir = os.path.join(self.workspace, "prior_hours")
        out: Dict[tuple, float] = {}
        if not os.path.isdir(ph_dir):
            return out
        for fn in sorted(os.listdir(ph_dir)):
            if fn.endswith(".csv"):
                with open(os.path.join(ph_dir, fn)) as f:
                    for row in csv.DictReader(f):
                        key = (int(row["pilot_id"]), row["date"])
                        out[key] = out.get(key, 0) + float(row["duty_hours"])
        return out

    # ===================== ANALYSIS HELPERS =====================

    @staticmethod
    def _get_fdp_limit(report_hour: int, reg: dict) -> float:
        fdp = reg["max_fdp"]
        if 5 <= report_hour <= 6:
            return fdp["early_start_0500_0659"]
        elif 7 <= report_hour <= 13:
            return fdp["normal_0700_1359"]
        else:
            return fdp["late_start_1400_0459"]

    @staticmethod
    def _classify_fdp_severity(excess: float, sev: dict) -> str:
        t = sev["fdp_exceeded"]
        if excess >= t["HIGH"]:
            return "HIGH"
        if excess >= t["MEDIUM"]:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _classify_rest_severity(rest_hours: float, sev: dict) -> str:
        t = sev["insufficient_rest"]
        if rest_hours < t["HIGH"]:
            return "HIGH"
        if rest_hours < t["MEDIUM"]:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _classify_cum_severity(excess: float, sev: dict, key: str) -> str:
        t = sev[key]
        if excess >= t["HIGH"]:
            return "HIGH"
        if excess >= t["MEDIUM"]:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _risk_level(score: float, threshold: float) -> str:
        if score > threshold + 10:
            return "CRITICAL"
        if score > threshold:
            return "HIGH"
        if score > 60:
            return "MODERATE"
        return "LOW"

    def _compute_pilot_fatigue(self, pairings, flights, rests, daily_hours, frw, reg):
        """Return (risk_score, primary_factor)."""
        w = frw["weights"]
        tod_pen = frw["time_of_day_penalty"]

        # 1. time-of-day
        tod_vals = []
        for pp in pairings:
            rh = datetime.fromisoformat(pp["report_time"]).hour
            for bucket, pen in tod_pen.items():
                lo, hi = map(int, bucket.split("-"))
                if lo <= rh < hi:
                    tod_vals.append(pen)
                    break
        tod_score = (sum(tod_vals) / len(tod_vals) * 100) if tod_vals else 0

        # 2. cumulative-hours ratio (worst 7-day window in Jan)
        max_7d = 0
        for day_num in range(1, 32):
            d = date(2025, 1, day_num)
            total = sum(
                daily_hours.get((d - timedelta(days=i)).strftime("%Y-%m-%d"), 0)
                for i in range(7)
            )
            max_7d = max(max_7d, total)
        cum_score = min(max_7d / reg["max_7day_duty_hours"] * 100, 100)

        # 3. rest quality
        quals = [r["self_reported_quality"] for r in rests]
        if quals:
            avg_q = sum(quals) / len(quals)
            bl = frw["rest_quality_baseline"]
            rq_score = max(0, (bl - avg_q) / bl * 100)
        else:
            rq_score = 50

        # 4. consecutive early starts
        max_c = cur_c = 0
        for pp in pairings:
            if datetime.fromisoformat(pp["report_time"]).hour < 7:
                cur_c += 1
                max_c = max(max_c, cur_c)
            else:
                cur_c = 0
        early_score = min(max_c / frw["max_consecutive_early_for_full_penalty"], 1.0) * 100

        # 5. sectors ratio (worst 7-day window)
        f_dates = [
            datetime.fromisoformat(fl["scheduled_departure"]).date() for fl in flights
        ]
        max_s7 = 0
        for day_num in range(1, 32):
            d = date(2025, 1, day_num)
            cnt = sum(1 for fd in f_dates if d - timedelta(days=6) <= fd <= d)
            max_s7 = max(max_s7, cnt)
        sec_score = min(max_s7 / frw["reference_sectors_per_week"] * 100, 100)

        components = {
            "time_of_day": w["time_of_day"] * tod_score,
            "cumulative_hours": w["cumulative_hours_ratio"] * cum_score,
            "rest_quality": w["rest_quality"] * rq_score,
            "consecutive_early_starts": w["consecutive_early_starts"] * early_score,
            "sectors_flown": w["sectors_flown_ratio"] * sec_score,
        }
        total = sum(components.values())
        primary = max(components, key=components.get)
        return min(total, 100.0), primary

    # -----------------------------------------------------------------

    def _compute_analysis(self, pilots, pairings_by_pilot, flights_by_pilot,
                          rests_by_pilot, amendments, prior_hours, config):
        """
        Core analysis shared by step & verify.

        All inputs are plain lists / dicts – source-agnostic.
        Returns (violations_list, fatigue_list).
        """
        reg = config["regulatory"]
        sev = config["severity"]
        dtr = config["duty_type_rules"]
        frw = config["fatigue_weights"]

        violations = []
        fatigue_scores = []

        for pilot in pilots:
            pid = pilot["pilot_id"]
            emp = pilot["employee_number"]
            name = pilot["name"]

            p_pairings = list(pairings_by_pilot.get(pid, []))
            p_flights = list(flights_by_pilot.get(pid, []))
            p_rests = list(rests_by_pilot.get(pid, []))

            # Apply amendments
            for pp in p_pairings:
                code = pp["pairing_code"]
                if code in amendments:
                    pp["release_time"] = amendments[code]
            p_pairings.sort(key=lambda x: x["report_time"])

            # --- FDP violations ---
            for pp in p_pairings:
                dt_rule = dtr.get(pp["duty_type"], {})
                if not dt_rule.get("counts_toward_fdp", True):
                    continue
                rpt = datetime.fromisoformat(pp["report_time"])
                rel = datetime.fromisoformat(pp["release_time"])
                fdp_h = (rel - rpt).total_seconds() / 3600
                limit = self._get_fdp_limit(rpt.hour, reg)
                if fdp_h > limit:
                    excess = fdp_h - limit
                    violations.append({
                        "pilot_id": pid,
                        "employee_number": emp,
                        "pilot_name": name,
                        "violation_type": "FDP_EXCEEDED",
                        "violation_date": rpt.strftime("%Y-%m-%d"),
                        "pairing_code": pp["pairing_code"],
                        "details": f"FDP of {fdp_h:.2f}h exceeds {limit:.1f}h limit",
                        "severity": self._classify_fdp_severity(excess, sev),
                    })

            # --- Rest violations (gap between consecutive pairings) ---
            for i in range(len(p_pairings) - 1):
                rel = datetime.fromisoformat(p_pairings[i]["release_time"])
                nxt_rpt = datetime.fromisoformat(p_pairings[i + 1]["report_time"])
                gap_h = (nxt_rpt - rel).total_seconds() / 3600
                min_rest = reg["min_rest_period_hours"]
                if 0 < gap_h < min_rest:
                    violations.append({
                        "pilot_id": pid,
                        "employee_number": emp,
                        "pilot_name": name,
                        "violation_type": "INSUFFICIENT_REST",
                        "violation_date": rel.strftime("%Y-%m-%d"),
                        "pairing_code": p_pairings[i]["pairing_code"],
                        "details": (
                            f"Rest of {gap_h:.2f}h between "
                            f"{p_pairings[i]['pairing_code']} and "
                            f"{p_pairings[i+1]['pairing_code']} "
                            f"below {min_rest:.1f}h minimum"
                        ),
                        "severity": self._classify_rest_severity(gap_h, sev),
                    })

            # --- Cumulative violations ---
            daily = {}
            for k, v in prior_hours.items():
                if k[0] == pid:
                    daily[k[1]] = daily.get(k[1], 0) + v
            for pp in p_pairings:
                rpt = datetime.fromisoformat(pp["report_time"])
                rel = datetime.fromisoformat(pp["release_time"])
                dur = (rel - rpt).total_seconds() / 3600
                mult = dtr.get(pp["duty_type"], {}).get("cumulative_multiplier", 1.0)
                ds = rpt.strftime("%Y-%m-%d")
                daily[ds] = daily.get(ds, 0) + dur * mult

            best7 = best28 = None
            for dn in range(1, 32):
                cd = date(2025, 1, dn)
                t7 = sum(daily.get((cd - timedelta(days=j)).strftime("%Y-%m-%d"), 0) for j in range(7))
                if t7 > reg["max_7day_duty_hours"]:
                    exc = t7 - reg["max_7day_duty_hours"]
                    if best7 is None or exc > best7[0]:
                        best7 = (exc, cd, t7)
                t28 = sum(daily.get((cd - timedelta(days=j)).strftime("%Y-%m-%d"), 0) for j in range(28))
                if t28 > reg["max_28day_duty_hours"]:
                    exc = t28 - reg["max_28day_duty_hours"]
                    if best28 is None or exc > best28[0]:
                        best28 = (exc, cd, t28)

            if best7:
                exc, vd, tot = best7
                violations.append({
                    "pilot_id": pid, "employee_number": emp, "pilot_name": name,
                    "violation_type": "7DAY_LIMIT_EXCEEDED",
                    "violation_date": vd.strftime("%Y-%m-%d"),
                    "pairing_code": "N/A",
                    "details": f"7-day duty hours of {tot:.2f}h exceed {reg['max_7day_duty_hours']:.1f}h limit",
                    "severity": self._classify_cum_severity(exc, sev, "cumulative_7day"),
                })
            if best28:
                exc, vd, tot = best28
                violations.append({
                    "pilot_id": pid, "employee_number": emp, "pilot_name": name,
                    "violation_type": "28DAY_LIMIT_EXCEEDED",
                    "violation_date": vd.strftime("%Y-%m-%d"),
                    "pairing_code": "N/A",
                    "details": f"28-day duty hours of {tot:.2f}h exceed {reg['max_28day_duty_hours']:.1f}h limit",
                    "severity": self._classify_cum_severity(exc, sev, "cumulative_28day"),
                })

            # --- Fatigue risk ---
            if p_pairings:
                score, pf = self._compute_pilot_fatigue(
                    p_pairings, p_flights, p_rests, daily, frw, reg
                )
                level = self._risk_level(score, reg["fatigue_risk_threshold"])
                if level in ("CRITICAL", "HIGH", "MODERATE"):
                    fatigue_scores.append({
                        "pilot_id": pid,
                        "employee_number": emp,
                        "pilot_name": name,
                        "risk_score": round(score, 2),
                        "risk_level": level,
                        "primary_factor": pf,
                    })

        # Sort
        sev_ord = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        violations.sort(key=lambda v: (sev_ord.get(v["severity"], 3), v["pilot_id"], v["violation_date"]))
        fatigue_scores.sort(key=lambda f: -f["risk_score"])
        return violations, fatigue_scores

    # ===================== STEP =====================

    def step(self, action: str) -> Tuple[float, Dict[str, Any]]:
        """
        Evaluate task completion by inspecting the workspace and the agent's final response.
        """
        config = self._load_config()
        amendments = self._load_amendments()
        prior_hours = self._load_prior_hours()

        # Gather data from DB
        all_pilots = self._db_query("SELECT * FROM pilots ORDER BY pilot_id")
        all_pairings = self._db_query("SELECT * FROM crew_pairings ORDER BY pilot_id, report_time")
        all_flights = self._db_query("SELECT * FROM flight_logs ORDER BY pilot_id, scheduled_departure")
        all_rests = self._db_query("SELECT * FROM rest_declarations ORDER BY pilot_id, rest_start")

        def _group(rows, key="pilot_id"):
            d: dict = {}
            for r in rows:
                d.setdefault(r[key], []).append(r)
            return d

        pairings_by = _group(all_pairings)
        flights_by = _group(all_flights)
        rests_by = _group(all_rests)

        expected_viol, expected_fat = self._compute_analysis(
            all_pilots, pairings_by, flights_by, rests_by,
            amendments, prior_hours, config,
        )

        criteria: Dict[str, dict] = {}

        # ---- 1. non_compliance_report.csv format (10 pts) ----
        rpt_path = os.path.join(self.workspace, "non_compliance_report.csv")
        expected_cols = {"pilot_id", "employee_number", "pilot_name",
                         "violation_type", "violation_date", "pairing_code",
                         "details", "severity"}
        rpt_rows = []
        rpt_ok = False
        if os.path.isfile(rpt_path):
            try:
                with open(rpt_path) as f:
                    reader = csv.DictReader(f)
                    rpt_rows = list(reader)
                    if reader.fieldnames and expected_cols.issubset(set(reader.fieldnames)):
                        rpt_ok = True
            except Exception:
                pass
        criteria["report_format"] = {
            "passed": rpt_ok,
            "score": 10 if rpt_ok else 0,
            "max_score": 10,
            "reason": "" if rpt_ok else "non_compliance_report.csv missing or wrong columns",
        }

        # Helper: build key sets from expected & reported
        def _viol_keys(rows, vtype, key_fn):
            return {key_fn(r) for r in rows if r.get("violation_type") == vtype or r.get("violation_type", "") == vtype}

        def _rpt_key_fdp(r):
            return (str(r.get("pilot_id", "")), r.get("pairing_code", ""))

        def _rpt_key_rest(r):
            return (str(r.get("pilot_id", "")), r.get("pairing_code", ""))

        def _rpt_key_cum(r):
            return str(r.get("pilot_id", ""))

        # ---- 2. FDP violations (20 pts) ----
        exp_fdp = {(str(v["pilot_id"]), v["pairing_code"]) for v in expected_viol if v["violation_type"] == "FDP_EXCEEDED"}
        rep_fdp = _viol_keys(rpt_rows, "FDP_EXCEEDED", _rpt_key_fdp)
        if len(exp_fdp) == 0:
            fdp_score = 20 if len(rep_fdp) == 0 else 10
        else:
            fdp_score = round(len(exp_fdp & rep_fdp) / len(exp_fdp) * 20)
        criteria["fdp_violations"] = {
            "passed": fdp_score == 20,
            "score": fdp_score,
            "max_score": 20,
            "reason": f"matched {len(exp_fdp & rep_fdp)}/{len(exp_fdp)} expected FDP violations",
        }

        # ---- 3. Rest violations (15 pts) ----
        exp_rest = {(str(v["pilot_id"]), v["pairing_code"]) for v in expected_viol if v["violation_type"] == "INSUFFICIENT_REST"}
        rep_rest = _viol_keys(rpt_rows, "INSUFFICIENT_REST", _rpt_key_rest)
        if len(exp_rest) == 0:
            rest_score = 15 if len(rep_rest) == 0 else 8
        else:
            rest_score = round(len(exp_rest & rep_rest) / len(exp_rest) * 15)
        criteria["rest_violations"] = {
            "passed": rest_score == 15,
            "score": rest_score,
            "max_score": 15,
            "reason": f"matched {len(exp_rest & rep_rest)}/{len(exp_rest)} expected rest violations",
        }

        # ---- 4. Cumulative violations (15 pts) ----
        exp_7d = {str(v["pilot_id"]) for v in expected_viol if v["violation_type"] == "7DAY_LIMIT_EXCEEDED"}
        exp_28d = {str(v["pilot_id"]) for v in expected_viol if v["violation_type"] == "28DAY_LIMIT_EXCEEDED"}
        rep_7d = _viol_keys(rpt_rows, "7DAY_LIMIT_EXCEEDED", _rpt_key_cum)
        rep_28d = _viol_keys(rpt_rows, "28DAY_LIMIT_EXCEEDED", _rpt_key_cum)
        exp_cum = exp_7d | exp_28d
        rep_cum = rep_7d | rep_28d
        if len(exp_cum) == 0:
            cum_score = 15 if len(rep_cum) == 0 else 8
        else:
            cum_score = round(len(exp_cum & rep_cum) / len(exp_cum) * 15)
        criteria["cumulative_violations"] = {
            "passed": cum_score == 15,
            "score": cum_score,
            "max_score": 15,
            "reason": f"matched {len(exp_cum & rep_cum)}/{len(exp_cum)} expected cumulative violations",
        }

        # ---- 5. Fatigue risk assessment (20 pts) ----
        fat_path = os.path.join(self.workspace, "fatigue_risk_assessment.csv")
        fat_rows = []
        fat_format_ok = False
        fat_cols = {"pilot_id", "employee_number", "pilot_name",
                    "risk_score", "risk_level", "primary_factor"}
        if os.path.isfile(fat_path):
            try:
                with open(fat_path) as f:
                    rdr = csv.DictReader(f)
                    fat_rows = list(rdr)
                    if rdr.fieldnames and fat_cols.issubset(set(rdr.fieldnames)):
                        fat_format_ok = True
            except Exception:
                pass

        fat_score = 0
        if fat_format_ok:
            fat_score += 5  # format correct
            # Match pilots & scores
            exp_fat_map = {str(fs["pilot_id"]): fs for fs in expected_fat}
            rep_fat_map = {str(fr.get("pilot_id", "")): fr for fr in fat_rows}
            if len(exp_fat_map) > 0:
                match_cnt = 0
                level_cnt = 0
                for pid, efs in exp_fat_map.items():
                    if pid in rep_fat_map:
                        try:
                            rep_sc = float(rep_fat_map[pid]["risk_score"])
                        except (ValueError, KeyError):
                            continue
                        if abs(rep_sc - efs["risk_score"]) <= 5.0:
                            match_cnt += 1
                        if rep_fat_map[pid].get("risk_level") == efs["risk_level"]:
                            level_cnt += 1
                fat_score += round(match_cnt / len(exp_fat_map) * 10)
                fat_score += round(level_cnt / len(exp_fat_map) * 5)
            else:
                fat_score += 15 if len(fat_rows) == 0 else 8
        criteria["fatigue_assessment"] = {
            "passed": fat_score == 20,
            "score": fat_score,
            "max_score": 20,
            "reason": f"fatigue assessment score {fat_score}/20",
        }

        # ---- 6. Roster adjustments (10 pts) ----
        adj_path = os.path.join(self.workspace, "roster_adjustments.json")
        adj_score = 0
        if os.path.isfile(adj_path):
            try:
                with open(adj_path) as f:
                    adj = json.load(f)
                if isinstance(adj, list) and len(adj) > 0:
                    adj_score += 5  # valid JSON list
                    violated_pids = {str(v["pilot_id"]) for v in expected_viol}
                    adj_pids = {str(a.get("pilot_id", "")) for a in adj}
                    if violated_pids and (adj_pids & violated_pids):
                        adj_score += round(len(adj_pids & violated_pids) / len(violated_pids) * 5)
                    elif not violated_pids:
                        adj_score += 5
            except Exception:
                pass
        criteria["roster_adjustments"] = {
            "passed": adj_score == 10,
            "score": adj_score,
            "max_score": 10,
            "reason": f"roster adjustments score {adj_score}/10",
        }

        # ---- 7. Summary in action string (10 pts) ----
        sum_score = 0
        exp_total_viols = len(expected_viol)
        exp_pilot_viols = len({v["pilot_id"] for v in expected_viol})
        exp_high_fat = len([f for f in expected_fat if f["risk_level"] in ("HIGH", "CRITICAL")])

        m = re.search(r"Total violations:\s*(\d+)", action, re.IGNORECASE)
        if m and abs(int(m.group(1)) - exp_total_viols) <= 2:
            sum_score += 3

        m = re.search(r"Pilots with violations:\s*(\d+)", action, re.IGNORECASE)
        if m and abs(int(m.group(1)) - exp_pilot_viols) <= 1:
            sum_score += 3

        m = re.search(r"High/Critical fatigue risk pilots:\s*(\d+)", action, re.IGNORECASE)
        if m and abs(int(m.group(1)) - exp_high_fat) <= 1:
            sum_score += 2

        # Top 3 check – verify the top pilot ID appears (if any)
        if expected_fat:
            top_pid = str(expected_fat[0]["pilot_id"])
            if top_pid in action:
                sum_score += 2
        else:
            sum_score += 2  # no expected fatigue entries → nothing to check

        criteria["summary_response"] = {
            "passed": sum_score == 10,
            "score": sum_score,
            "max_score": 10,
            "reason": f"summary score {sum_score}/10",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ===================== VERIFY =====================

    def verify(self) -> Tuple[float, Dict[str, Any]]:
        """
        Self-test: solve the task using ONLY self.tools and workspace files,
        then call self.step() to check reward.
        """
        config = self._load_config()
        amendments = self._load_amendments()
        prior_hours = self._load_prior_hours()

        # 1. Gather all pilots via tool
        all_pilots = []
        page = 1
        while True:
            result = self.tools["list_pilots"](page=page, page_size=20)
            all_pilots.extend(result["pilots"])
            if page >= result["total_pages"]:
                break
            page += 1

        # 2. For each pilot, get details + pairings + flights + rest
        pilots_full = []
        pairings_by: Dict[int, list] = {}
        flights_by: Dict[int, list] = {}
        rests_by: Dict[int, list] = {}

        for p in all_pilots:
            pid = p["pilot_id"]
            det = self.tools["get_pilot_details"](pilot_id=pid)
            pilots_full.append(det)

            pr = self.tools["get_pilot_pairings"](
                pilot_id=pid, start_date="2025-01-01", end_date="2025-01-31"
            )
            pairings_by[pid] = pr["pairings"]

            fl = self.tools["get_pilot_flight_logs"](
                pilot_id=pid, start_date="2025-01-01", end_date="2025-01-31"
            )
            flights_by[pid] = fl["flights"]

            rs = self.tools["get_pilot_rest_records"](
                pilot_id=pid, start_date="2025-01-01", end_date="2025-01-31"
            )
            rests_by[pid] = rs["rest_records"]

        # 3. Compute analysis
        violations, fatigue_scores = self._compute_analysis(
            pilots_full, pairings_by, flights_by, rests_by,
            amendments, prior_hours, config,
        )

        # 4. Write non_compliance_report.csv
        rpt_path = os.path.join(self.workspace, "non_compliance_report.csv")
        fieldnames = [
            "pilot_id", "employee_number", "pilot_name",
            "violation_type", "violation_date", "pairing_code",
            "details", "severity",
        ]
        with open(rpt_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(violations)

        # 5. Write fatigue_risk_assessment.csv
        fat_path = os.path.join(self.workspace, "fatigue_risk_assessment.csv")
        fat_fields = [
            "pilot_id", "employee_number", "pilot_name",
            "risk_score", "risk_level", "primary_factor",
        ]
        with open(fat_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fat_fields)
            w.writeheader()
            w.writerows(fatigue_scores)

        # 6. Write roster_adjustments.json
        adj = []
        violated_pilots = {}
        for v in violations:
            pid = v["pilot_id"]
            if pid not in violated_pilots:
                violated_pilots[pid] = {
                    "emp": v["employee_number"],
                    "types": set(),
                    "codes": [],
                    "max_sev": v["severity"],
                }
            violated_pilots[pid]["types"].add(v["violation_type"])
            if v["pairing_code"] != "N/A":
                violated_pilots[pid]["codes"].append(v["pairing_code"])
            sev_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            if sev_rank.get(v["severity"], 3) < sev_rank.get(violated_pilots[pid]["max_sev"], 3):
                violated_pilots[pid]["max_sev"] = v["severity"]

        for pid, info in violated_pilots.items():
            atype = "reduce_duties"
            if "INSUFFICIENT_REST" in info["types"]:
                atype = "extend_rest"
            if "7DAY_LIMIT_EXCEEDED" in info["types"] or "28DAY_LIMIT_EXCEEDED" in info["types"]:
                atype = "mandatory_day_off"
            priority = "MEDIUM"
            if info["max_sev"] == "HIGH":
                priority = "URGENT"
            elif info["max_sev"] == "MEDIUM":
                priority = "HIGH"
            adj.append({
                "pilot_id": pid,
                "employee_number": info["emp"],
                "adjustment_type": atype,
                "affected_pairings": list(set(info["codes"]))[:5],
                "reason": ", ".join(sorted(info["types"])),
                "priority": priority,
            })

        adj_path = os.path.join(self.workspace, "roster_adjustments.json")
        with open(adj_path, "w") as f:
            json.dump(adj, f, indent=2)

        # 7. Build action string
        total_viols = len(violations)
        pilot_viols = len({v["pilot_id"] for v in violations})
        high_crit = len([fs for fs in fatigue_scores if fs["risk_level"] in ("HIGH", "CRITICAL")])
        top3 = fatigue_scores[:3]
        top3_str = ", ".join(
            f"{fs['pilot_id']} | {fs['employee_number']} | {fs['risk_score']}"
            for fs in top3
        )

        action = (
            f"Total violations: {total_viols}. "
            f"Pilots with violations: {pilot_viols}. "
            f"High/Critical fatigue risk pilots: {high_crit}. "
            f"Top 3 fatigue risks: {top3_str}."
        )

        return self.step(action)
