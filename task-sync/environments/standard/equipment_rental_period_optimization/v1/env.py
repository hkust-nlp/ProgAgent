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

    # ── tool definitions (OpenAI format) ───────────────────────────────
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

    # ═══════════════════════════════════════════════════════════════════
    #  Tool methods
    # ═══════════════════════════════════════════════════════════════════

    @tool(
        description=(
            "List rental agreements with pagination. Returns a page of "
            "agreements and the total count."
        ),
        parameters={
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "description": "Page number, 1-indexed.",
                },
                "page_size": {
                    "type": "integer",
                    "description": (
                        "Number of items per page (default 20, max 50)."
                    ),
                },
            },
            "required": ["page"],
        },
    )
    def list_rental_agreements(self, page: int, page_size: int = 20) -> dict:
        page_size = max(1, min(int(page_size), 50))
        page = max(1, int(page))
        offset = (page - 1) * page_size

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM rental_agreements"
        ).fetchone()["cnt"]
        rows = conn.execute(
            "SELECT agreement_id, equipment_id, rental_house, "
            "start_date, end_date, daily_rate "
            "FROM rental_agreements ORDER BY agreement_id "
            "LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        conn.close()

        agreements = [
            {
                "agreement_id": r["agreement_id"],
                "equipment_id": r["equipment_id"],
                "rental_house": r["rental_house"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "daily_rate": r["daily_rate"],
            }
            for r in rows
        ]
        return {"agreements": agreements, "total": total, "page": page}

    @tool(
        description=(
            "Get details for a single piece of equipment by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "integer",
                    "description": "The equipment ID.",
                },
            },
            "required": ["equipment_id"],
        },
    )
    def get_equipment_info(self, equipment_id: int) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT equipment_id, name, category, weight_kg "
            "FROM equipment WHERE equipment_id = ?",
            (int(equipment_id),),
        ).fetchone()
        conn.close()
        if row is None:
            return {"error": f"Equipment {equipment_id} not found."}
        return {
            "equipment_id": row["equipment_id"],
            "name": row["name"],
            "category": row["category"],
            "weight_kg": row["weight_kg"],
        }

    @tool(
        description=(
            "Get all scenes that require a specific piece of equipment. "
            "Returns scene IDs, names, shoot dates, and durations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "equipment_id": {
                    "type": "integer",
                    "description": "The equipment ID.",
                },
            },
            "required": ["equipment_id"],
        },
    )
    def get_scenes_for_equipment(self, equipment_id: int) -> list:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT DISTINCT s.scene_id, s.scene_name, s.shoot_date, "
            "s.duration_days "
            "FROM scenes s "
            "JOIN scene_equipment se ON s.scene_id = se.scene_id "
            "WHERE se.equipment_id = ? "
            "ORDER BY s.shoot_date",
            (int(equipment_id),),
        ).fetchall()
        conn.close()
        return [
            {
                "scene_id": r["scene_id"],
                "scene_name": r["scene_name"],
                "shoot_date": r["shoot_date"],
                "duration_days": r["duration_days"],
            }
            for r in rows
        ]

    # ═══════════════════════════════════════════════════════════════════
    #  Ground-truth computation (shared by step & verify)
    # ═══════════════════════════════════════════════════════════════════

    def _compute_ground_truth(self):
        """Compute the expected cost-saving roster from DB + workspace."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # --- DB data ---
        equipment_map = {}
        for r in conn.execute("SELECT * FROM equipment"):
            equipment_map[r["equipment_id"]] = dict(r)

        scene_map = {}
        for r in conn.execute("SELECT * FROM scenes"):
            scene_map[r["scene_id"]] = dict(r)

        equip_scenes = {}
        for r in conn.execute("SELECT scene_id, equipment_id FROM scene_equipment"):
            equip_scenes.setdefault(r["equipment_id"], set()).add(r["scene_id"])

        agreements = []
        for r in conn.execute(
            "SELECT * FROM rental_agreements ORDER BY agreement_id"
        ):
            agreements.append(dict(r))
        conn.close()

        # --- Workspace: contingency policy ---
        with open(os.path.join(self.workspace, "contingency_policy.yaml")) as f:
            policy = yaml.safe_load(f)

        # --- Workspace: rate cards ---
        with open(os.path.join(self.workspace, "rate_cards.json")) as f:
            rate_cards = json.load(f)

        # --- Workspace: return eligibility ---
        with open(os.path.join(self.workspace, "return_eligibility.md")) as f:
            rules_text = f.read()
        min_condition = float(
            re.search(r"Minimum average condition rating required:\s*([\d.]+)", rules_text).group(1)
        )
        min_rental_days = int(
            re.search(r"Minimum rental period \(days\):\s*(\d+)", rules_text).group(1)
        )

        # --- Workspace: schedule blocks → scene attributes ---
        scene_attrs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("schedule_block_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        scene_attrs[int(row["scene_id"])] = {
                            "priority": row["priority"],
                            "weather_dependent": row["weather_dependent"] == "True",
                        }

        # --- Workspace: condition reports ---
        equipment_ratings = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("condition_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reports = json.load(f)
                for entry in reports:
                    eid = entry["equipment_id"]
                    equipment_ratings.setdefault(eid, []).append(
                        entry["condition_rating"]
                    )

        # --- Build roster ---
        roster = []
        for ag in agreements:
            eid = ag["equipment_id"]
            einfo = equipment_map.get(eid)
            if einfo is None:
                continue
            category = einfo["category"]
            rental_house = ag["rental_house"]

            sids = equip_scenes.get(eid, set())
            if not sids:
                continue

            # last needed date
            last_needed = max(
                datetime.strptime(scene_map[sid]["shoot_date"], "%Y-%m-%d")
                + timedelta(days=scene_map[sid]["duration_days"] - 1)
                for sid in sids
            )

            # scene flags
            has_weather = any(
                scene_attrs.get(sid, {}).get("weather_dependent", False)
                for sid in sids
            )
            has_high_priority = any(
                scene_attrs.get(sid, {}).get("priority", "C") == "A"
                for sid in sids
            )

            base_buffer = policy["base_buffer_days"].get(category, 2)
            buffer_days = base_buffer
            if has_weather:
                buffer_days += policy["weather_dependent_addition"]
            if has_high_priority:
                buffer_days += policy["high_priority_addition"]

            adjusted_return = last_needed + timedelta(days=buffer_days)
            contracted_end = datetime.strptime(ag["end_date"], "%Y-%m-%d")

            if adjusted_return >= contracted_end:
                continue

            # condition check
            ratings = equipment_ratings.get(eid, [])
            if not ratings:
                continue
            avg_condition = sum(ratings) / len(ratings)
            if avg_condition < min_condition:
                continue

            # min rental period
            start_dt = datetime.strptime(ag["start_date"], "%Y-%m-%d")
            if (adjusted_return - start_dt).days < min_rental_days:
                continue

            days_saved = (contracted_end - adjusted_return).days
            daily_rate = ag["daily_rate"]
            fee_pct = rate_cards.get(rental_house, {}).get(
                "early_return_fee_pct", 0
            )
            net_savings = round(days_saved * daily_rate * (1 - fee_pct), 2)

            if net_savings <= 0:
                continue

            roster.append({
                "equipment_id": eid,
                "equipment_name": einfo["name"],
                "category": category,
                "rental_house": rental_house,
                "original_return_date": ag["end_date"],
                "last_needed_date": last_needed.strftime("%Y-%m-%d"),
                "buffer_days": buffer_days,
                "adjusted_return_date": adjusted_return.strftime("%Y-%m-%d"),
                "days_saved": days_saved,
                "daily_rate": daily_rate,
                "net_savings": net_savings,
            })

        roster.sort(key=lambda x: (-x["net_savings"], x["equipment_id"]))
        total_savings = round(sum(r["net_savings"] for r in roster), 2)
        return roster, total_savings

    # ═══════════════════════════════════════════════════════════════════
    #  step  –  evaluation
    # ═══════════════════════════════════════════════════════════════════

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
        gt_roster, gt_total = self._compute_ground_truth()
        criteria = {}

        # ── 1. File structure (10 pts) ─────────────────────────────────
        csv_path = os.path.join(self.workspace, "cost_saving_roster.csv")
        expected_cols = [
            "equipment_id", "equipment_name", "category", "rental_house",
            "original_return_date", "last_needed_date", "buffer_days",
            "adjusted_return_date", "days_saved", "daily_rate", "net_savings",
        ]
        if os.path.exists(csv_path):
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                agent_cols = list(reader.fieldnames) if reader.fieldnames else []
                agent_rows = list(reader)
            cols_ok = agent_cols == expected_cols
            criteria["file_structure"] = {
                "passed": cols_ok,
                "score": 10 if cols_ok else 5 if set(expected_cols).issubset(set(agent_cols)) else 0,
                "max_score": 10,
                "reason": "" if cols_ok else f"Expected columns {expected_cols}, got {agent_cols}",
            }
        else:
            agent_rows = []
            criteria["file_structure"] = {
                "passed": False,
                "score": 0,
                "max_score": 10,
                "reason": "cost_saving_roster.csv not found in workspace.",
            }

        # ── 2. Correct qualifying equipment set (25 pts) ───────────────
        gt_ids = {r["equipment_id"] for r in gt_roster}
        try:
            agent_ids = {int(r["equipment_id"]) for r in agent_rows}
        except (KeyError, ValueError):
            agent_ids = set()

        if gt_ids:
            id_overlap = len(gt_ids & agent_ids)
            id_union = len(gt_ids | agent_ids)
            jaccard = id_overlap / id_union if id_union else 0
        else:
            jaccard = 1.0 if not agent_ids else 0.0

        score_ids = round(25 * jaccard)
        criteria["qualifying_equipment"] = {
            "passed": gt_ids == agent_ids,
            "score": score_ids,
            "max_score": 25,
            "reason": "" if gt_ids == agent_ids else (
                f"Expected {len(gt_ids)} items, got {len(agent_ids)}. "
                f"Missing: {sorted(gt_ids - agent_ids)[:10]}, "
                f"Extra: {sorted(agent_ids - gt_ids)[:10]}"
            ),
        }

        # ── 3. Correct adjusted return dates (20 pts) ──────────────────
        gt_dates = {r["equipment_id"]: r["adjusted_return_date"] for r in gt_roster}
        agent_dates = {}
        for r in agent_rows:
            try:
                agent_dates[int(r["equipment_id"])] = r["adjusted_return_date"]
            except (KeyError, ValueError):
                pass

        common_ids = gt_ids & agent_ids
        date_correct = 0
        for eid in common_ids:
            if gt_dates.get(eid) == agent_dates.get(eid):
                date_correct += 1

        date_ratio = date_correct / len(gt_ids) if gt_ids else 1.0
        score_dates = round(20 * date_ratio)
        criteria["adjusted_return_dates"] = {
            "passed": date_ratio == 1.0,
            "score": score_dates,
            "max_score": 20,
            "reason": "" if date_ratio == 1.0 else (
                f"{date_correct}/{len(gt_ids)} dates correct."
            ),
        }

        # ── 4. Correct net savings values (20 pts) ─────────────────────
        gt_savings = {r["equipment_id"]: r["net_savings"] for r in gt_roster}
        agent_savings = {}
        for r in agent_rows:
            try:
                agent_savings[int(r["equipment_id"])] = round(float(r["net_savings"]), 2)
            except (KeyError, ValueError):
                pass

        savings_correct = 0
        for eid in common_ids:
            if abs(gt_savings.get(eid, 0) - agent_savings.get(eid, -1)) < 0.02:
                savings_correct += 1

        sav_ratio = savings_correct / len(gt_ids) if gt_ids else 1.0
        score_savings = round(20 * sav_ratio)
        criteria["net_savings_values"] = {
            "passed": sav_ratio == 1.0,
            "score": score_savings,
            "max_score": 20,
            "reason": "" if sav_ratio == 1.0 else (
                f"{savings_correct}/{len(gt_ids)} savings correct."
            ),
        }

        # ── 5. Correct sort order (10 pts) ─────────────────────────────
        try:
            agent_order = [int(r["equipment_id"]) for r in agent_rows]
        except (KeyError, ValueError):
            agent_order = []
        gt_order = [r["equipment_id"] for r in gt_roster]
        order_ok = agent_order == gt_order
        criteria["sort_order"] = {
            "passed": order_ok,
            "score": 10 if order_ok else 0,
            "max_score": 10,
            "reason": "" if order_ok else "Rows not sorted by net_savings desc / equipment_id asc.",
        }

        # ── 6. Total savings in response (15 pts) ─────────────────────
        nums = re.findall(r"\$?\s*([\d,]+\.?\d*)", action.replace(",", ""))
        total_match = False
        for n in nums:
            try:
                val = float(n)
                if abs(val - gt_total) < 0.02:
                    total_match = True
                    break
            except ValueError:
                pass
        criteria["total_savings_response"] = {
            "passed": total_match,
            "score": 15 if total_match else 0,
            "max_score": 15,
            "reason": "" if total_match else (
                f"Expected total ≈ {gt_total:.2f} in response."
            ),
        }

        total_score = sum(c["score"] for c in criteria.values())
        max_score = sum(c["max_score"] for c in criteria.values())

        return total_score / max_score, {
            "eval_criteria": criteria,
            "total_score": total_score,
            "max_score": max_score,
        }

    # ═══════════════════════════════════════════════════════════════════
    #  verify  –  self-test
    # ═══════════════════════════════════════════════════════════════════

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
        import yaml as _yaml

        # ── 1. Gather all rental agreements via tool ───────────────────
        all_agreements = []
        page = 1
        while True:
            result = self.tools["list_rental_agreements"](page=page, page_size=20)
            all_agreements.extend(result["agreements"])
            if page * 20 >= result["total"]:
                break
            page += 1

        # ── 2. Get equipment info for every rented item ────────────────
        equipment_info = {}
        for ag in all_agreements:
            eid = ag["equipment_id"]
            if eid not in equipment_info:
                equipment_info[eid] = self.tools["get_equipment_info"](
                    equipment_id=eid
                )

        # ── 3. Get scenes for each equipment ───────────────────────────
        equipment_scenes = {}
        for eid in equipment_info:
            equipment_scenes[eid] = self.tools["get_scenes_for_equipment"](
                equipment_id=eid
            )

        # ── 4. Read workspace configuration files ─────────────────────
        with open(os.path.join(self.workspace, "contingency_policy.yaml")) as f:
            policy = _yaml.safe_load(f)

        with open(os.path.join(self.workspace, "rate_cards.json")) as f:
            rate_cards = json.load(f)

        with open(os.path.join(self.workspace, "return_eligibility.md")) as f:
            rules_text = f.read()
        min_condition = float(
            re.search(
                r"Minimum average condition rating required:\s*([\d.]+)",
                rules_text,
            ).group(1)
        )
        min_rental_days = int(
            re.search(
                r"Minimum rental period \(days\):\s*(\d+)", rules_text
            ).group(1)
        )

        # ── 5. Read schedule-block CSVs for scene attributes ───────────
        scene_attrs = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("schedule_block_") and fname.endswith(".csv"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        scene_attrs[int(row["scene_id"])] = {
                            "priority": row["priority"],
                            "weather_dependent": row["weather_dependent"] == "True",
                        }

        # ── 6. Read condition reports ──────────────────────────────────
        equip_ratings = {}
        for fname in sorted(os.listdir(self.workspace)):
            if fname.startswith("condition_report_") and fname.endswith(".json"):
                with open(os.path.join(self.workspace, fname)) as f:
                    reports = json.load(f)
                for entry in reports:
                    eid = entry["equipment_id"]
                    equip_ratings.setdefault(eid, []).append(
                        entry["condition_rating"]
                    )

        # ── 7. Compute early-return roster ─────────────────────────────
        roster = []
        for ag in all_agreements:
            eid = ag["equipment_id"]
            einfo = equipment_info.get(eid, {})
            category = einfo.get("category")
            if category is None:
                continue

            scenes = equipment_scenes.get(eid, [])
            if not scenes:
                continue

            last_needed = max(
                datetime.strptime(s["shoot_date"], "%Y-%m-%d")
                + timedelta(days=s["duration_days"] - 1)
                for s in scenes
            )

            scene_ids = [s["scene_id"] for s in scenes]
            has_weather = any(
                scene_attrs.get(sid, {}).get("weather_dependent", False)
                for sid in scene_ids
            )
            has_high_priority = any(
                scene_attrs.get(sid, {}).get("priority", "C") == "A"
                for sid in scene_ids
            )

            base_buffer = policy["base_buffer_days"].get(category, 2)
            buffer_days = base_buffer
            if has_weather:
                buffer_days += policy["weather_dependent_addition"]
            if has_high_priority:
                buffer_days += policy["high_priority_addition"]

            adjusted_return = last_needed + timedelta(days=buffer_days)
            contracted_end = datetime.strptime(ag["end_date"], "%Y-%m-%d")

            if adjusted_return >= contracted_end:
                continue

            ratings = equip_ratings.get(eid, [])
            if not ratings:
                continue
            avg_cond = sum(ratings) / len(ratings)
            if avg_cond < min_condition:
                continue

            start_dt = datetime.strptime(ag["start_date"], "%Y-%m-%d")
            if (adjusted_return - start_dt).days < min_rental_days:
                continue

            days_saved = (contracted_end - adjusted_return).days
            daily_rate = ag["daily_rate"]
            fee_pct = rate_cards.get(ag["rental_house"], {}).get(
                "early_return_fee_pct", 0
            )
            net_savings = round(days_saved * daily_rate * (1 - fee_pct), 2)

            if net_savings <= 0:
                continue

            roster.append({
                "equipment_id": eid,
                "equipment_name": einfo["name"],
                "category": category,
                "rental_house": ag["rental_house"],
                "original_return_date": ag["end_date"],
                "last_needed_date": last_needed.strftime("%Y-%m-%d"),
                "buffer_days": buffer_days,
                "adjusted_return_date": adjusted_return.strftime("%Y-%m-%d"),
                "days_saved": days_saved,
                "daily_rate": daily_rate,
                "net_savings": net_savings,
            })

        roster.sort(key=lambda x: (-x["net_savings"], x["equipment_id"]))

        # ── 8. Write deliverable CSV ───────────────────────────────────
        fieldnames = [
            "equipment_id", "equipment_name", "category", "rental_house",
            "original_return_date", "last_needed_date", "buffer_days",
            "adjusted_return_date", "days_saved", "daily_rate", "net_savings",
        ]
        csv_path = os.path.join(self.workspace, "cost_saving_roster.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(roster)

        total_savings = round(sum(r["net_savings"] for r in roster), 2)

        action = f"Total estimated net savings: ${total_savings:.2f}"
        return self.step(action)
