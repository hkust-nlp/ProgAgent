"""
Environment for Clinical Trial DDI Signal Detection task.
"""

import os
import csv
import json
import glob
import sqlite3
from typing import Tuple, Dict, List, Any

import yaml
import pandas as pd


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


# ---------------------------------------------------------------------------
# Task_Env
# ---------------------------------------------------------------------------

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
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description="Returns the list of cohorts in the clinical trial, including cohort identifiers, names, assigned study drugs, and target indications.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def list_cohorts(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT cohort_id, cohort_name, study_drug, target_indication FROM cohorts ORDER BY cohort_id")
        rows = cur.fetchall()
        conn.close()
        return [
            {"cohort_id": r[0], "cohort_name": r[1], "study_drug": r[2], "target_indication": r[3]}
            for r in rows
        ]

    @tool(
        description="Returns all participants enrolled in a given cohort, including their demographic information and current trial phase assignment.",
        parameters={
            "type": "object",
            "properties": {
                "cohort_id": {
                    "type": "integer",
                    "description": "The cohort identifier.",
                },
            },
            "required": ["cohort_id"],
        },
    )
    def get_cohort_participants(self, cohort_id: int) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT participant_id, age, sex, weight_kg, enrollment_date, current_phase "
            "FROM participants WHERE cohort_id = ? ORDER BY participant_id",
            (int(cohort_id),),
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "participant_id": r[0],
                "age": r[1],
                "sex": r[2],
                "weight_kg": r[3],
                "enrollment_date": r[4],
                "current_phase": r[5],
            }
            for r in rows
        ]

    @tool(
        description="Returns all concomitant medications for a given participant, including drug name, dose, route, and the weeks during which the medication is active.",
        parameters={
            "type": "object",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "The participant identifier, e.g. 'PT0001'.",
                },
            },
            "required": ["participant_id"],
        },
    )
    def get_participant_medications(self, participant_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT med_id, drug_name, dose_mg, route, start_week, end_week "
            "FROM concomitant_medications WHERE participant_id = ? ORDER BY med_id",
            (participant_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "med_id": r[0],
                "drug_name": r[1],
                "dose_mg": r[2],
                "route": r[3],
                "start_week": r[4],
                "end_week": r[5],
            }
            for r in rows
        ]

    @tool(
        description="Returns adverse events for a given participant. Optionally filter by reporting week.",
        parameters={
            "type": "object",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "The participant identifier.",
                },
                "week": {
                    "type": "integer",
                    "description": "If provided, return only adverse events from this reporting week.",
                },
            },
            "required": ["participant_id"],
        },
    )
    def get_adverse_events(self, participant_id: str, week: int = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if week is not None:
            cur.execute(
                "SELECT ae_id, event_type, severity_grade, onset_week, resolved, description "
                "FROM adverse_events WHERE participant_id = ? AND onset_week = ? ORDER BY ae_id",
                (participant_id, int(week)),
            )
        else:
            cur.execute(
                "SELECT ae_id, event_type, severity_grade, onset_week, resolved, description "
                "FROM adverse_events WHERE participant_id = ? ORDER BY ae_id",
                (participant_id,),
            )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "ae_id": r[0],
                "event_type": r[1],
                "severity_grade": r[2],
                "onset_week": r[3],
                "resolved": r[4],
                "description": r[5],
            }
            for r in rows
        ]

    @tool(
        description="Returns pharmacokinetic samples for a given participant. Optionally filter by reporting week.",
        parameters={
            "type": "object",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "The participant identifier.",
                },
                "week": {
                    "type": "integer",
                    "description": "If provided, return only PK samples from this reporting week.",
                },
            },
            "required": ["participant_id"],
        },
    )
    def get_pk_samples(self, participant_id: str, week: int = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if week is not None:
            cur.execute(
                "SELECT sample_id, week, analyte, concentration_ng_ml, time_post_dose_hr "
                "FROM pk_samples WHERE participant_id = ? AND week = ? ORDER BY sample_id",
                (participant_id, int(week)),
            )
        else:
            cur.execute(
                "SELECT sample_id, week, analyte, concentration_ng_ml, time_post_dose_hr "
                "FROM pk_samples WHERE participant_id = ? ORDER BY sample_id",
                (participant_id,),
            )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "sample_id": r[0],
                "week": r[1],
                "analyte": r[2],
                "concentration_ng_ml": r[3],
                "time_post_dose_hr": r[4],
            }
            for r in rows
        ]

    @tool(
        description="Returns the sorted list of reporting week numbers covered by the trial data.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def get_reporting_weeks(self) -> List[int]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT onset_week FROM adverse_events "
            "UNION "
            "SELECT DISTINCT week FROM pk_samples "
            "ORDER BY 1"
        )
        weeks = [r[0] for r in cur.fetchall()]
        conn.close()
        return weeks

    # ------------------------------------------------------------------
    # Ground-truth computation  (used by both step and verify)
    # ------------------------------------------------------------------

    def _load_workspace_configs(self):
        """Load all config / reference files from workspace."""
        ddi_ref = pd.read_csv(os.path.join(self.workspace, "ddi_reference.csv"))
        with open(os.path.join(self.workspace, "phase_rules.yaml")) as f:
            phase_rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "pk_normal_ranges.json")) as f:
            pk_ranges = json.load(f)
        with open(os.path.join(self.workspace, "flagging_config.json")) as f:
            flagging_config = json.load(f)

        # Dose adjustments from all site reports
        adj_frames = []
        for fp in sorted(glob.glob(os.path.join(self.workspace, "site_report_*.csv"))):
            df = pd.read_csv(fp)
            if len(df) > 0:
                adj_frames.append(df)
        if adj_frames:
            dose_adj = pd.concat(adj_frames, ignore_index=True)
        else:
            dose_adj = pd.DataFrame(
                columns=["participant_id", "drug_name", "adjusted_dose_mg",
                          "adjustment_week", "reason"]
            )

        return ddi_ref, phase_rules, pk_ranges, flagging_config, dose_adj

    def _compute_ground_truth(self):
        """Compute the full set of flagged entries and cohort flags."""
        ddi_ref, phase_rules, pk_ranges, flagging_config, dose_adj = \
            self._load_workspace_configs()

        conn = sqlite3.connect(self.db_path)
        participants = pd.read_sql("SELECT * FROM participants", conn)
        medications = pd.read_sql("SELECT * FROM concomitant_medications", conn)
        adverse_events = pd.read_sql("SELECT * FROM adverse_events", conn)
        pk_samples = pd.read_sql("SELECT * FROM pk_samples", conn)
        cohorts = pd.read_sql("SELECT * FROM cohorts", conn)
        conn.close()

        # Build DDI lookup  (sorted key)
        ddi_lookup = {}
        for _, row in ddi_ref.iterrows():
            key = tuple(sorted([row["drug_a"], row["drug_b"]]))
            ddi_lookup[key] = {
                "interaction_type": row["interaction_type"],
                "risk_level": row["risk_level"],
                "min_dose": {
                    row["drug_a"]: float(row["min_dose_a"]),
                    row["drug_b"]: float(row["min_dose_b"]),
                },
            }

        cohort_drug_map = dict(zip(cohorts["cohort_id"], cohorts["study_drug"]))
        phases_cfg = phase_rules["phases"]

        # Reporting weeks
        all_weeks = sorted(
            set(adverse_events["onset_week"].unique())
            | set(pk_samples["week"].unique())
        )

        flagged_entries = []

        for _, p in participants.iterrows():
            pid = p["participant_id"]
            cid = int(p["cohort_id"])
            phase = int(p["current_phase"])
            study_drug = cohort_drug_map[cid]

            phase_info = phases_cfg[phase]
            ae_thresh = int(phase_info["ae_severity_threshold"])
            pk_mult = float(phase_info["pk_deviation_multiplier"])

            p_meds = medications[medications["participant_id"] == pid]
            drug_list = list(p_meds["drug_name"].unique())

            for di in range(len(drug_list)):
                for dj in range(di + 1, len(drug_list)):
                    key = tuple(sorted([drug_list[di], drug_list[dj]]))
                    if key not in ddi_lookup:
                        continue
                    ddi_info = ddi_lookup[key]
                    drug_a, drug_b = key  # alphabetical

                    for week in all_weeks:
                        # --- active check ---
                        def _active_dose(drug):
                            for _, med in p_meds[p_meds["drug_name"] == drug].iterrows():
                                sw = int(med["start_week"])
                                ew = med["end_week"]
                                if sw <= week and (pd.isna(ew) or int(ew) >= week):
                                    return float(med["dose_mg"])
                            return None

                        base_dose_a = _active_dose(drug_a)
                        base_dose_b = _active_dose(drug_b)
                        if base_dose_a is None or base_dose_b is None:
                            continue

                        # effective dose after adjustments
                        def _eff_dose(drug, base):
                            adj = dose_adj[
                                (dose_adj["participant_id"] == pid)
                                & (dose_adj["drug_name"] == drug)
                                & (dose_adj["adjustment_week"] <= week)
                            ]
                            if len(adj) > 0:
                                latest = adj.loc[adj["adjustment_week"].idxmax()]
                                return float(latest["adjusted_dose_mg"])
                            return base

                        eff_a = _eff_dose(drug_a, base_dose_a)
                        eff_b = _eff_dose(drug_b, base_dose_b)

                        min_a = ddi_info["min_dose"].get(drug_a, 0)
                        min_b = ddi_info["min_dose"].get(drug_b, 0)
                        if eff_a < min_a or eff_b < min_b:
                            continue

                        # --- risk elevation ---
                        risk_level = ddi_info["risk_level"]
                        if flagging_config.get("dose_adjustment_risk_elevation", False):
                            elevated = False
                            adj_a = dose_adj[
                                (dose_adj["participant_id"] == pid)
                                & (dose_adj["drug_name"] == drug_a)
                                & (dose_adj["adjustment_week"] <= week)
                            ]
                            if len(adj_a) > 0:
                                la = adj_a.loc[adj_a["adjustment_week"].idxmax()]
                                if float(la["adjusted_dose_mg"]) > base_dose_a:
                                    elevated = True
                            adj_b = dose_adj[
                                (dose_adj["participant_id"] == pid)
                                & (dose_adj["drug_name"] == drug_b)
                                & (dose_adj["adjustment_week"] <= week)
                            ]
                            if len(adj_b) > 0:
                                lb = adj_b.loc[adj_b["adjustment_week"].idxmax()]
                                if float(lb["adjusted_dose_mg"]) > base_dose_b:
                                    elevated = True
                            if elevated:
                                if risk_level == "low":
                                    risk_level = "moderate"
                                elif risk_level == "moderate":
                                    risk_level = "high"

                        # --- AE check ---
                        p_aes = adverse_events[
                            (adverse_events["participant_id"] == pid)
                            & (adverse_events["onset_week"] == week)
                        ]
                        max_ae = int(p_aes["severity_grade"].max()) if len(p_aes) > 0 else 0
                        ae_flag = max_ae >= ae_thresh

                        # --- PK check ---
                        p_pk = pk_samples[
                            (pk_samples["participant_id"] == pid)
                            & (pk_samples["week"] == week)
                        ]
                        pk_range = pk_ranges.get(study_drug, {})
                        pk_min = float(pk_range.get("min_ng_ml", 0))
                        pk_max_val = float(pk_range.get("max_ng_ml", 1e9))
                        lower_bound = pk_min / pk_mult
                        upper_bound = pk_max_val * pk_mult

                        max_pk_dev = 0.0
                        for _, pkr in p_pk.iterrows():
                            conc = float(pkr["concentration_ng_ml"])
                            if conc > upper_bound:
                                dev = ((conc - upper_bound) / upper_bound) * 100
                            elif conc < lower_bound:
                                dev = ((lower_bound - conc) / lower_bound) * 100
                            else:
                                dev = 0.0
                            if dev > max_pk_dev:
                                max_pk_dev = dev
                        pk_flag = max_pk_dev > 0
                        max_pk_dev = round(max_pk_dev, 1)

                        if not (ae_flag or pk_flag):
                            continue

                        if ae_flag and pk_flag:
                            reason = "AE+PK"
                        elif ae_flag:
                            reason = "AE"
                        else:
                            reason = "PK"

                        flagged_entries.append({
                            "week": int(week),
                            "participant_id": pid,
                            "cohort_id": cid,
                            "drug_a": drug_a,
                            "drug_b": drug_b,
                            "risk_level": risk_level,
                            "max_ae_severity": max_ae,
                            "pk_deviation_pct": max_pk_dev,
                            "flag_reason": reason,
                        })

        # Sort
        flagged_entries.sort(
            key=lambda x: (x["week"], x["cohort_id"], x["participant_id"], x["drug_a"])
        )

        # Cohort flags
        cohort_flag_thresh = int(flagging_config.get("cohort_flag_threshold", 2))
        risk_weights = flagging_config.get("risk_level_weights",
                                           {"high": 3, "moderate": 2, "low": 1})

        cohort_week_data: Dict[str, Dict[str, Any]] = {}
        for e in flagged_entries:
            wk = str(e["week"])
            ck = str(e["cohort_id"])
            cohort_week_data.setdefault(wk, {})
            cohort_week_data[wk].setdefault(ck, {
                "participant_ids": set(),
                "total_risk_score": 0,
            })
            bucket = cohort_week_data[wk][ck]
            bucket["participant_ids"].add(e["participant_id"])
            bucket["total_risk_score"] += risk_weights.get(e["risk_level"], 1)

        cohort_flags: Dict[str, Dict[str, Any]] = {}
        for wk, cohorts_data in cohort_week_data.items():
            for ck, data in cohorts_data.items():
                pids_sorted = sorted(data["participant_ids"])
                if len(pids_sorted) >= cohort_flag_thresh:
                    cohort_flags.setdefault(wk, {})
                    cohort_flags[wk][ck] = {
                        "flagged_count": len(pids_sorted),
                        "participant_ids": pids_sorted,
                        "total_risk_score": data["total_risk_score"],
                    }

        return flagged_entries, cohort_flags

    # ------------------------------------------------------------------
    # step
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
        gt_entries, gt_cohort_flags = self._compute_ground_truth()
        criteria: Dict[str, Dict[str, Any]] = {}

        # ---- 1. weekly_ddi_report.csv exists with correct columns (10 pts) ----
        report_path = os.path.join(self.workspace, "weekly_ddi_report.csv")
        expected_cols = [
            "week", "participant_id", "cohort_id", "drug_a", "drug_b",
            "risk_level", "max_ae_severity", "pk_deviation_pct", "flag_reason",
        ]
        if os.path.exists(report_path):
            try:
                agent_df = pd.read_csv(report_path)
                cols_ok = list(agent_df.columns) == expected_cols
            except Exception:
                agent_df = pd.DataFrame()
                cols_ok = False
        else:
            agent_df = pd.DataFrame()
            cols_ok = False

        criteria["report_file_structure"] = {
            "passed": cols_ok,
            "score": 10 if cols_ok else 0,
            "max_score": 10,
            "reason": "" if cols_ok else "weekly_ddi_report.csv missing or wrong columns",
        }

        # ---- 2. Correct flagged entries (25 pts) ----
        gt_keys = set()
        for e in gt_entries:
            gt_keys.add((e["week"], e["participant_id"], e["drug_a"], e["drug_b"]))

        agent_keys = set()
        if len(agent_df) > 0 and cols_ok:
            for _, r in agent_df.iterrows():
                da, db = sorted([str(r.get("drug_a", "")), str(r.get("drug_b", ""))])
                agent_keys.add((int(r["week"]), str(r["participant_id"]), da, db))

        if len(gt_keys) == 0:
            match_ratio = 1.0 if len(agent_keys) == 0 else 0.0
        else:
            correct = len(gt_keys & agent_keys)
            extra = len(agent_keys - gt_keys)
            penalty = min(extra, correct)  # penalise false positives
            match_ratio = max(0, correct - penalty) / len(gt_keys)

        score2 = round(match_ratio * 25)
        criteria["flagged_entries_accuracy"] = {
            "passed": match_ratio >= 0.95,
            "score": score2,
            "max_score": 25,
            "reason": "" if match_ratio >= 0.95
                      else f"matched {match_ratio:.1%} of expected entries",
        }

        # ---- 3. Correct risk levels and flag reasons (15 pts) ----
        gt_detail = {}
        for e in gt_entries:
            k = (e["week"], e["participant_id"], e["drug_a"], e["drug_b"])
            gt_detail[k] = (e["risk_level"], e["flag_reason"])

        agent_detail = {}
        if len(agent_df) > 0 and cols_ok:
            for _, r in agent_df.iterrows():
                da, db = sorted([str(r.get("drug_a", "")), str(r.get("drug_b", ""))])
                k = (int(r["week"]), str(r["participant_id"]), da, db)
                agent_detail[k] = (str(r.get("risk_level", "")), str(r.get("flag_reason", "")))

        common = gt_keys & agent_keys
        detail_correct = 0
        for k in common:
            if k in gt_detail and k in agent_detail:
                if gt_detail[k] == agent_detail[k]:
                    detail_correct += 1
        detail_ratio = detail_correct / max(len(common), 1)
        score3 = round(detail_ratio * 15)
        criteria["risk_and_reason_accuracy"] = {
            "passed": detail_ratio >= 0.9,
            "score": score3,
            "max_score": 15,
            "reason": "" if detail_ratio >= 0.9
                      else f"risk/reason correct for {detail_ratio:.1%} of matched entries",
        }

        # ---- 4. PK deviation accuracy (15 pts) ----
        gt_pk = {}
        for e in gt_entries:
            k = (e["week"], e["participant_id"], e["drug_a"], e["drug_b"])
            gt_pk[k] = e["pk_deviation_pct"]

        agent_pk = {}
        if len(agent_df) > 0 and cols_ok:
            for _, r in agent_df.iterrows():
                da, db = sorted([str(r.get("drug_a", "")), str(r.get("drug_b", ""))])
                k = (int(r["week"]), str(r["participant_id"]), da, db)
                try:
                    agent_pk[k] = round(float(r.get("pk_deviation_pct", 0)), 1)
                except (ValueError, TypeError):
                    agent_pk[k] = -1

        pk_correct = 0
        for k in common:
            if k in gt_pk and k in agent_pk:
                if abs(gt_pk[k] - agent_pk[k]) <= 0.15:
                    pk_correct += 1
        pk_ratio = pk_correct / max(len(common), 1)
        score4 = round(pk_ratio * 15)
        criteria["pk_deviation_accuracy"] = {
            "passed": pk_ratio >= 0.9,
            "score": score4,
            "max_score": 15,
            "reason": "" if pk_ratio >= 0.9
                      else f"pk_deviation_pct correct for {pk_ratio:.1%} of matched entries",
        }

        # ---- 5. cohort_flags.json structure (10 pts) ----
        cf_path = os.path.join(self.workspace, "cohort_flags.json")
        cf_ok = False
        agent_cf = {}
        if os.path.exists(cf_path):
            try:
                with open(cf_path) as f:
                    agent_cf = json.load(f)
                # Validate structure
                if isinstance(agent_cf, dict):
                    cf_ok = True
                    for wk, wv in agent_cf.items():
                        if not isinstance(wv, dict):
                            cf_ok = False
                            break
                        for ck, cv in wv.items():
                            if not isinstance(cv, dict):
                                cf_ok = False
                                break
                            if "flagged_count" not in cv or "participant_ids" not in cv \
                                    or "total_risk_score" not in cv:
                                cf_ok = False
                                break
            except Exception:
                cf_ok = False

        criteria["cohort_flags_structure"] = {
            "passed": cf_ok,
            "score": 10 if cf_ok else 0,
            "max_score": 10,
            "reason": "" if cf_ok else "cohort_flags.json missing or wrong structure",
        }

        # ---- 6. Cohort flag accuracy (15 pts) ----
        gt_cf_keys = set()
        for wk, wv in gt_cohort_flags.items():
            for ck in wv:
                gt_cf_keys.add((wk, ck))

        agent_cf_keys = set()
        if cf_ok:
            for wk, wv in agent_cf.items():
                for ck in wv:
                    agent_cf_keys.add((str(wk), str(ck)))

        if len(gt_cf_keys) == 0:
            cf_match = 1.0 if len(agent_cf_keys) == 0 else 0.0
        else:
            cf_correct = len(gt_cf_keys & agent_cf_keys)
            cf_extra = len(agent_cf_keys - gt_cf_keys)
            cf_match = max(0, cf_correct - min(cf_extra, cf_correct)) / len(gt_cf_keys)

        score6 = round(cf_match * 15)
        criteria["cohort_flag_accuracy"] = {
            "passed": cf_match >= 0.9,
            "score": score6,
            "max_score": 15,
            "reason": "" if cf_match >= 0.9
                      else f"cohort flags matched {cf_match:.1%}",
        }

        # ---- 7. Response summary (10 pts) ----
        total_flagged = len(gt_entries)
        total_cw_flags = len(gt_cf_keys)

        # Highest-risk cohort across all weeks
        cohort_total_risk: Dict[str, int] = {}
        for wk, wv in gt_cohort_flags.items():
            for ck, cv in wv.items():
                cohort_total_risk[ck] = cohort_total_risk.get(ck, 0) + cv["total_risk_score"]
        if cohort_total_risk:
            best_cohort = max(cohort_total_risk, key=cohort_total_risk.get)
            best_score = cohort_total_risk[best_cohort]
        else:
            best_cohort = "none"
            best_score = 0

        resp = action.lower().replace(" ", "")
        pts7 = 0
        # check total_flagged_entries
        if f"total_flagged_entries:{total_flagged}" in resp:
            pts7 += 4
        # check total_cohort_week_flags
        if f"total_cohort_week_flags:{total_cw_flags}" in resp:
            pts7 += 3
        # check highest_risk_cohort
        if f"highest_risk_cohort:{best_cohort}" in resp and f"score{best_score}" in resp:
            pts7 += 3

        criteria["response_summary"] = {
            "passed": pts7 == 10,
            "score": pts7,
            "max_score": 10,
            "reason": "" if pts7 == 10 else "response missing or incorrect summary stats",
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())
        reward = total_score / max_score

        info = {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }
        return reward, info

    # ------------------------------------------------------------------
    # verify
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

        # ----- 1. Read workspace configs -----
        ddi_ref = pd.read_csv(os.path.join(self.workspace, "ddi_reference.csv"))
        with open(os.path.join(self.workspace, "phase_rules.yaml")) as f:
            phase_rules = yaml.safe_load(f)
        with open(os.path.join(self.workspace, "pk_normal_ranges.json")) as f:
            pk_ranges = json.load(f)
        with open(os.path.join(self.workspace, "flagging_config.json")) as f:
            flagging_config = json.load(f)

        # Read assessment guidelines (for PK deviation formula)
        with open(os.path.join(self.workspace, "assessment_guidelines.txt")) as f:
            _ = f.read()  # agent would parse this; we already know the formula

        # Read all site reports for dose adjustments
        adj_frames = []
        for fp in sorted(glob.glob(os.path.join(self.workspace, "site_report_*.csv"))):
            df = pd.read_csv(fp)
            if len(df) > 0:
                adj_frames.append(df)
        if adj_frames:
            dose_adj = pd.concat(adj_frames, ignore_index=True)
        else:
            dose_adj = pd.DataFrame(
                columns=["participant_id", "drug_name", "adjusted_dose_mg",
                          "adjustment_week", "reason"]
            )

        # Build DDI lookup
        ddi_lookup = {}
        for _, row in ddi_ref.iterrows():
            key = tuple(sorted([row["drug_a"], row["drug_b"]]))
            ddi_lookup[key] = {
                "interaction_type": row["interaction_type"],
                "risk_level": row["risk_level"],
                "min_dose": {
                    row["drug_a"]: float(row["min_dose_a"]),
                    row["drug_b"]: float(row["min_dose_b"]),
                },
            }

        phases_cfg = phase_rules["phases"]
        risk_weights = flagging_config.get("risk_level_weights",
                                           {"high": 3, "moderate": 2, "low": 1})
        cohort_flag_thresh = int(flagging_config.get("cohort_flag_threshold", 2))

        # ----- 2. Gather data via tools -----
        cohorts = self.tools["list_cohorts"]()
        weeks = self.tools["get_reporting_weeks"]()
        cohort_drug_map = {c["cohort_id"]: c["study_drug"] for c in cohorts}

        # Gather all participants + their medications
        all_participants = []
        participant_meds = {}
        for cohort in cohorts:
            cid = cohort["cohort_id"]
            pts = self.tools["get_cohort_participants"](cohort_id=cid)
            for pt in pts:
                pt["cohort_id"] = cid
                all_participants.append(pt)
                pid = pt["participant_id"]
                meds = self.tools["get_participant_medications"](participant_id=pid)
                participant_meds[pid] = meds

        # Identify participants with DDI pairs
        participant_ddi_pairs = {}  # pid -> list of (drug_a, drug_b, ddi_info)
        for pt in all_participants:
            pid = pt["participant_id"]
            meds = participant_meds[pid]
            drugs = list(set(m["drug_name"] for m in meds))
            pairs = []
            for i in range(len(drugs)):
                for j in range(i + 1, len(drugs)):
                    key = tuple(sorted([drugs[i], drugs[j]]))
                    if key in ddi_lookup:
                        pairs.append((key[0], key[1], ddi_lookup[key],
                                      {d["drug_name"]: d for d in meds
                                       if d["drug_name"] in key}))
            if pairs:
                participant_ddi_pairs[pid] = pairs

        # For participants with DDI pairs, get AEs and PK per week
        flagged_entries = []
        for pt in all_participants:
            pid = pt["participant_id"]
            if pid not in participant_ddi_pairs:
                continue
            cid = pt["cohort_id"]
            phase = pt["current_phase"]
            study_drug = cohort_drug_map[cid]

            phase_info = phases_cfg[phase]
            ae_thresh = int(phase_info["ae_severity_threshold"])
            pk_mult = float(phase_info["pk_deviation_multiplier"])

            meds = participant_meds[pid]

            for week in weeks:
                # Get AEs and PK for this participant-week
                aes = self.tools["get_adverse_events"](participant_id=pid, week=week)
                pks = self.tools["get_pk_samples"](participant_id=pid, week=week)

                max_ae = max((ae["severity_grade"] for ae in aes), default=0)
                ae_flag = max_ae >= ae_thresh

                # PK deviation
                pk_range = pk_ranges.get(study_drug, {})
                pk_min = float(pk_range.get("min_ng_ml", 0))
                pk_max_val = float(pk_range.get("max_ng_ml", 1e9))
                lower_bound = pk_min / pk_mult
                upper_bound = pk_max_val * pk_mult

                max_pk_dev = 0.0
                for pkr in pks:
                    conc = float(pkr["concentration_ng_ml"])
                    if conc > upper_bound:
                        dev = ((conc - upper_bound) / upper_bound) * 100
                    elif conc < lower_bound:
                        dev = ((lower_bound - conc) / lower_bound) * 100
                    else:
                        dev = 0.0
                    max_pk_dev = max(max_pk_dev, dev)
                pk_flag = max_pk_dev > 0
                max_pk_dev = round(max_pk_dev, 1)

                if not (ae_flag or pk_flag):
                    continue

                if ae_flag and pk_flag:
                    reason = "AE+PK"
                elif ae_flag:
                    reason = "AE"
                else:
                    reason = "PK"

                # Check each DDI pair for this participant in this week
                for drug_a, drug_b, ddi_info, med_map in participant_ddi_pairs[pid]:

                    # Active check
                    def _active_dose(drug):
                        for m in meds:
                            if m["drug_name"] != drug:
                                continue
                            sw = int(m["start_week"])
                            ew = m["end_week"]
                            if sw <= week and (ew is None or int(ew) >= week):
                                return float(m["dose_mg"])
                        return None

                    base_a = _active_dose(drug_a)
                    base_b = _active_dose(drug_b)
                    if base_a is None or base_b is None:
                        continue

                    # Effective dose
                    def _eff_dose(drug, base):
                        adj = dose_adj[
                            (dose_adj["participant_id"] == pid)
                            & (dose_adj["drug_name"] == drug)
                            & (dose_adj["adjustment_week"] <= week)
                        ]
                        if len(adj) > 0:
                            latest = adj.loc[adj["adjustment_week"].idxmax()]
                            return float(latest["adjusted_dose_mg"])
                        return base

                    eff_a = _eff_dose(drug_a, base_a)
                    eff_b = _eff_dose(drug_b, base_b)

                    min_a = ddi_info["min_dose"].get(drug_a, 0)
                    min_b = ddi_info["min_dose"].get(drug_b, 0)
                    if eff_a < min_a or eff_b < min_b:
                        continue

                    # Risk elevation
                    risk_level = ddi_info["risk_level"]
                    if flagging_config.get("dose_adjustment_risk_elevation", False):
                        elevated = False
                        adj_a = dose_adj[
                            (dose_adj["participant_id"] == pid)
                            & (dose_adj["drug_name"] == drug_a)
                            & (dose_adj["adjustment_week"] <= week)
                        ]
                        if len(adj_a) > 0:
                            la = adj_a.loc[adj_a["adjustment_week"].idxmax()]
                            if float(la["adjusted_dose_mg"]) > base_a:
                                elevated = True
                        adj_b = dose_adj[
                            (dose_adj["participant_id"] == pid)
                            & (dose_adj["drug_name"] == drug_b)
                            & (dose_adj["adjustment_week"] <= week)
                        ]
                        if len(adj_b) > 0:
                            lb = adj_b.loc[adj_b["adjustment_week"].idxmax()]
                            if float(lb["adjusted_dose_mg"]) > base_b:
                                elevated = True
                        if elevated:
                            if risk_level == "low":
                                risk_level = "moderate"
                            elif risk_level == "moderate":
                                risk_level = "high"

                    flagged_entries.append({
                        "week": int(week),
                        "participant_id": pid,
                        "cohort_id": cid,
                        "drug_a": drug_a,
                        "drug_b": drug_b,
                        "risk_level": risk_level,
                        "max_ae_severity": int(max_ae),
                        "pk_deviation_pct": max_pk_dev,
                        "flag_reason": reason,
                    })

        # Sort
        flagged_entries.sort(
            key=lambda x: (x["week"], x["cohort_id"], x["participant_id"], x["drug_a"])
        )

        # ----- 3. Write deliverables -----

        # weekly_ddi_report.csv
        report_cols = [
            "week", "participant_id", "cohort_id", "drug_a", "drug_b",
            "risk_level", "max_ae_severity", "pk_deviation_pct", "flag_reason",
        ]
        report_df = pd.DataFrame(flagged_entries, columns=report_cols)
        report_df.to_csv(
            os.path.join(self.workspace, "weekly_ddi_report.csv"), index=False
        )

        # cohort_flags.json
        cohort_week_data: Dict[str, Dict[str, Any]] = {}
        for e in flagged_entries:
            wk = str(e["week"])
            ck = str(e["cohort_id"])
            cohort_week_data.setdefault(wk, {})
            cohort_week_data[wk].setdefault(ck, {
                "participant_ids": set(),
                "total_risk_score": 0,
            })
            bucket = cohort_week_data[wk][ck]
            bucket["participant_ids"].add(e["participant_id"])
            bucket["total_risk_score"] += risk_weights.get(e["risk_level"], 1)

        cohort_flags: Dict[str, Dict[str, Any]] = {}
        for wk, cd in cohort_week_data.items():
            for ck, data in cd.items():
                pids_sorted = sorted(data["participant_ids"])
                if len(pids_sorted) >= cohort_flag_thresh:
                    cohort_flags.setdefault(wk, {})
                    cohort_flags[wk][ck] = {
                        "flagged_count": len(pids_sorted),
                        "participant_ids": pids_sorted,
                        "total_risk_score": data["total_risk_score"],
                    }

        with open(os.path.join(self.workspace, "cohort_flags.json"), "w") as f:
            json.dump(cohort_flags, f, indent=2)

        # ----- 4. Build action string -----
        total_flagged = len(flagged_entries)
        total_cw_flags = sum(len(wv) for wv in cohort_flags.values())

        cohort_total_risk: Dict[str, int] = {}
        for wk, wv in cohort_flags.items():
            for ck, cv in wv.items():
                cohort_total_risk[ck] = cohort_total_risk.get(ck, 0) + cv["total_risk_score"]
        if cohort_total_risk:
            best_cohort = max(cohort_total_risk, key=cohort_total_risk.get)
            best_score = cohort_total_risk[best_cohort]
        else:
            best_cohort = "none"
            best_score = 0

        action = (
            f"total_flagged_entries: {total_flagged}\n"
            f"total_cohort_week_flags: {total_cw_flags}\n"
            f"highest_risk_cohort: {best_cohort} with score {best_score}"
        )

        return self.step(action)
