"""
Data generation for container load planning task.
Generates SQLite database and workspace files for multi-leg voyage optimization.
"""

import os
import json
import csv
import sqlite3
import argparse
import math
import numpy as np
import pandas as pd
from faker import Faker

SCALE = {
    "rows_per_table": 120,       # v2 = 4x base
    "num_workspace_files": 24,   # v2 = base + 2N (8 + 16)
}

PORTS = ["ALPHA", "BRAVO", "CHARLIE", "DELTA"]
PORT_ARRIVALS = {
    "BRAVO": "2025-06-18",
    "CHARLIE": "2025-06-22",
    "DELTA": "2025-06-27",
}


def compute_vessel_layout(n_containers):
    """Compute vessel bay/tier/row layout based on container count."""
    if n_containers <= 60:
        tiers_per_bay, rows_per_bay = 4, 2
    elif n_containers <= 180:
        tiers_per_bay, rows_per_bay = 5, 3
    else:
        tiers_per_bay, rows_per_bay = 6, 4

    cells_per_bay = tiers_per_bay * rows_per_bay
    return tiers_per_bay, rows_per_bay, cells_per_bay


def main(db_path, workspace):
    np.random.seed(42)
    fake = Faker()
    Faker.seed(42)
    import random
    random.seed(42)

    os.makedirs(workspace, exist_ok=True)

    n_containers = SCALE["rows_per_table"]
    n_files = SCALE["num_workspace_files"]
    tiers_per_bay, rows_per_bay, cells_per_bay = compute_vessel_layout(n_containers)

    # --- Generate containers ---
    dest_ports = PORTS[1:]  # BRAVO, CHARLIE, DELTA
    containers = []
    for i in range(n_containers):
        ctype = "20ft" if np.random.random() < 0.6 else "40ft"
        weight = round(float(np.random.uniform(5, 28)), 1)
        dest = str(np.random.choice(dest_ports))
        hazmat = ""
        hazmat_val = float(np.random.random())
        if hazmat_val < 0.12:
            hazmat = str(np.random.choice(["A", "B", "C"]))
        # Hazmat and reefer are mutually exclusive for operational safety
        reefer_val = float(np.random.random())
        is_reefer = 1 if (reefer_val < 0.15 and not hazmat) else 0
        length = 20.0 if ctype == "20ft" else 40.0
        height = float(np.random.choice([8.5, 9.5]))
        owner = fake.company()[:40]

        containers.append({
            "container_id": f"CTN{i+1:04d}",
            "container_type": ctype,
            "weight_tons": weight,
            "length_ft": length,
            "width_ft": 8.0,
            "height_ft": height,
            "destination_port": dest,
            "hazmat_class": hazmat,
            "is_reefer": is_reefer,
            "owner": owner,
        })

    # Count types to determine bay allocation
    n_20ft = sum(1 for c in containers if c["container_type"] == "20ft")
    n_40ft = n_containers - n_20ft

    n_20ft_bays = max(2, math.ceil(n_20ft * 1.5 / cells_per_bay))
    n_40ft_bays = max(2, math.ceil(n_40ft * 1.5 / cells_per_bay))
    n_bays = n_20ft_bays + n_40ft_bays

    bay_sizes = {}
    for b in range(1, n_bays + 1):
        bay_sizes[b] = "20ft" if b <= n_20ft_bays else "40ft"

    # Reefer bays: ~40% of each type, at least 1
    n_reefer_20 = max(1, round(n_20ft_bays * 0.4))
    n_reefer_40 = max(1, round(n_40ft_bays * 0.4))
    reefer_bays = set(range(1, n_reefer_20 + 1))
    reefer_bays |= set(range(n_20ft_bays + 1, n_20ft_bays + n_reefer_40 + 1))

    # --- Generate stowage cells ---
    weight_step = round(14.0 / tiers_per_bay, 2)
    cells = []
    cell_counter = 0
    for bay in range(1, n_bays + 1):
        for tier in range(1, tiers_per_bay + 1):
            for row in range(1, rows_per_bay + 1):
                cell_counter += 1
                max_weight = round(30 - (tier - 1) * weight_step, 1)
                cells.append({
                    "cell_id": f"CELL{cell_counter:04d}",
                    "bay_number": bay,
                    "tier": tier,
                    "row": row,
                    "max_weight_tons": max_weight,
                    "is_reefer_slot": 1 if bay in reefer_bays else 0,
                    "cell_size": bay_sizes[bay],
                })

    # --- Generate transport bookings ---
    transport = []
    for i, c in enumerate(containers):
        dest = c["destination_port"]
        arrival = pd.Timestamp(PORT_ARRIVALS[dest])
        pickup_days = int(np.random.randint(1, 4))
        pickup = arrival + pd.Timedelta(days=pickup_days)
        deadline_hours = int(np.random.randint(6, 24))
        deadline = pickup + pd.Timedelta(hours=deadline_hours)
        vehicle = str(np.random.choice(["truck", "rail", "barge"]))

        transport.append({
            "booking_id": f"TRN{i+1:04d}",
            "container_id": c["container_id"],
            "port_code": dest,
            "vehicle_type": vehicle,
            "pickup_datetime": pickup.strftime("%Y-%m-%d %H:%M"),
            "deadline_datetime": deadline.strftime("%Y-%m-%d %H:%M"),
        })

    # --- Generate current (suboptimal) plan ---
    # Randomly assign containers to cells matching type only (no optimization)
    shuffled_indices = list(range(n_containers))
    np.random.shuffle(shuffled_indices)

    type_cells = {"20ft": [], "40ft": []}
    for cell in cells:
        type_cells[cell["cell_size"]].append(cell)

    current_plan = []
    used_cells = set()
    for idx in shuffled_indices:
        c = containers[idx]
        for cell in type_cells[c["container_type"]]:
            if cell["cell_id"] not in used_cells:
                used_cells.add(cell["cell_id"])
                current_plan.append({
                    "assignment_id": f"ASN{len(current_plan)+1:04d}",
                    "container_id": c["container_id"],
                    "cell_id": cell["cell_id"],
                    "bay_number": cell["bay_number"],
                    "tier": cell["tier"],
                    "row_number": cell["row"],
                })
                break

    # --- Write database ---
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""CREATE TABLE containers (
        container_id TEXT PRIMARY KEY,
        container_type TEXT NOT NULL,
        weight_tons REAL NOT NULL,
        length_ft REAL NOT NULL,
        width_ft REAL NOT NULL,
        height_ft REAL NOT NULL,
        destination_port TEXT NOT NULL,
        hazmat_class TEXT,
        is_reefer INTEGER NOT NULL,
        owner TEXT
    )""")
    for c in containers:
        cursor.execute(
            "INSERT INTO containers VALUES (?,?,?,?,?,?,?,?,?,?)",
            (c["container_id"], c["container_type"], c["weight_tons"],
             c["length_ft"], c["width_ft"], c["height_ft"],
             c["destination_port"], c["hazmat_class"], c["is_reefer"], c["owner"]),
        )

    cursor.execute("""CREATE TABLE stowage_cells (
        cell_id TEXT PRIMARY KEY,
        bay_number INTEGER NOT NULL,
        tier INTEGER NOT NULL,
        row_number INTEGER NOT NULL,
        max_weight_tons REAL NOT NULL,
        is_reefer_slot INTEGER NOT NULL,
        cell_size TEXT NOT NULL
    )""")
    for cell in cells:
        cursor.execute(
            "INSERT INTO stowage_cells VALUES (?,?,?,?,?,?,?)",
            (cell["cell_id"], cell["bay_number"], cell["tier"],
             cell["row"], cell["max_weight_tons"], cell["is_reefer_slot"],
             cell["cell_size"]),
        )

    cursor.execute("""CREATE TABLE transport_bookings (
        booking_id TEXT PRIMARY KEY,
        container_id TEXT NOT NULL,
        port_code TEXT NOT NULL,
        vehicle_type TEXT NOT NULL,
        pickup_datetime TEXT NOT NULL,
        deadline_datetime TEXT NOT NULL,
        FOREIGN KEY (container_id) REFERENCES containers(container_id)
    )""")
    for t in transport:
        cursor.execute(
            "INSERT INTO transport_bookings VALUES (?,?,?,?,?,?)",
            (t["booking_id"], t["container_id"], t["port_code"],
             t["vehicle_type"], t["pickup_datetime"], t["deadline_datetime"]),
        )

    cursor.execute("""CREATE TABLE current_assignments (
        assignment_id TEXT PRIMARY KEY,
        container_id TEXT NOT NULL,
        cell_id TEXT NOT NULL,
        bay_number INTEGER NOT NULL,
        tier INTEGER NOT NULL,
        row_number INTEGER NOT NULL,
        FOREIGN KEY (container_id) REFERENCES containers(container_id),
        FOREIGN KEY (cell_id) REFERENCES stowage_cells(cell_id)
    )""")
    for a in current_plan:
        cursor.execute(
            "INSERT INTO current_assignments VALUES (?,?,?,?,?,?)",
            (a["assignment_id"], a["container_id"], a["cell_id"],
             a["bay_number"], a["tier"], a["row_number"]),
        )

    conn.commit()
    conn.close()

    # --- Generate workspace files ---

    # == Fixed config files ==

    # 1. voyage_route.json
    voyage = {
        "voyage_id": "VOY-2025-0042",
        "vessel_name": "MV Pacific Horizon",
        "loading_port": "ALPHA",
        "legs": [
            {"leg": 1, "from": "ALPHA", "to": "BRAVO",
             "departure": "2025-06-15", "arrival": "2025-06-18"},
            {"leg": 2, "from": "BRAVO", "to": "CHARLIE",
             "departure": "2025-06-19", "arrival": "2025-06-22"},
            {"leg": 3, "from": "CHARLIE", "to": "DELTA",
             "departure": "2025-06-23", "arrival": "2025-06-27"},
        ],
    }
    with open(os.path.join(workspace, "voyage_route.json"), "w") as f:
        json.dump(voyage, f, indent=2)

    # 2. vessel_spec.json
    bay_weight_limit = round(tiers_per_bay * rows_per_bay * 21.0, 1)
    vessel_spec = {
        "vessel_name": "MV Pacific Horizon",
        "num_bays": n_bays,
        "tiers_per_bay": tiers_per_bay,
        "rows_per_bay": rows_per_bay,
        "total_cells": len(cells),
        "bay_weight_limit_tons": bay_weight_limit,
        "reefer_bays": sorted(reefer_bays),
        "bay_size_assignments": {str(b): s for b, s in bay_sizes.items()},
    }
    with open(os.path.join(workspace, "vessel_spec.json"), "w") as f:
        json.dump(vessel_spec, f, indent=2)

    # 3. stacking_rules.txt
    stacking_text = f"""STACKING RULES FOR CONTAINER LOADING
=====================================

Rule 1 - Weight Ordering:
Within each vertical stack (same bay and row), containers must be arranged so that
the weight of each container is greater than or equal to the weight of the container
directly above it. Heavier containers always go on lower tiers.

Rule 2 - Cell Weight Capacity:
Each stowage cell has an individual maximum weight limit. No container placed in a
cell may exceed that cell's capacity. Cell capacities can be queried from the vessel's
stowage cell records.

Rule 3 - Type Matching:
A 20ft container must be placed in a 20ft cell. A 40ft container must be placed in a
40ft cell. No cross-size placement is permitted.

Rule 4 - Reefer Placement:
Any container requiring temperature control must be placed in a reefer-capable cell.
Temperature control may be required either because the container itself is a reefer
unit OR because the cargo inside requires it, even if the container is standard.
Consult the cargo manifests for temperature control requirements beyond the reefer
designation in the container registry.

Rule 5 - Bay Weight Limit:
The combined weight of all containers loaded in a single bay must not exceed the
published bay weight limit of {bay_weight_limit} tons.

Rule 6 - Discharge Sequence Optimization:
Containers destined for earlier discharge ports should be placed on higher tiers
where possible (subject to weight constraints) to minimize re-handling operations
at intermediate ports.
"""
    with open(os.path.join(workspace, "stacking_rules.txt"), "w") as f:
        f.write(stacking_text)

    # 4. hazmat_policy.md
    hazmat_md = """# Hazardous Materials Stowage Separation Policy

**Policy Version:** 2025-01
**Effective Date:** 2025-01-01

## Bay Isolation Rule

Containers carrying hazardous materials of different classes must not be stowed in
the same bay. All hazmat containers within a single bay must belong to the same
hazmat class. Non-hazardous containers may be placed in any bay regardless of
whether hazmat containers are also present.

## Recognized Hazmat Classes

| Class | Description           |
|-------|-----------------------|
| A     | Flammable Liquids     |
| B     | Corrosive Substances  |
| C     | Toxic Materials       |

## Enforcement

Any loading plan that places containers of two or more different hazmat classes in
the same bay is considered non-compliant and must be rectified before departure.
"""
    with open(os.path.join(workspace, "hazmat_policy.md"), "w") as f:
        f.write(hazmat_md)

    # == Scalable cargo batch files ==
    # These contain requires_temp_control info NOT in the database.
    containers_per_file = max(1, n_containers // n_files)
    for file_idx in range(n_files):
        start = file_idx * containers_per_file
        if file_idx == n_files - 1:
            end = n_containers
        else:
            end = start + containers_per_file
        batch = containers[start:end]

        rows_out = []
        for c in batch:
            # requires_temp_control: ~18% of non-reefer, non-hazmat containers
            # Always consume the random value to keep state consistent
            rtc_val = float(np.random.random())
            rtc = False
            if c["is_reefer"] == 0 and not c["hazmat_class"] and rtc_val < 0.18:
                rtc = True

            rows_out.append({
                "container_id": c["container_id"],
                "booking_ref": f"BK-{fake.bothify('######')}",
                "cargo_category": str(np.random.choice([
                    "DRY_GOODS", "MACHINERY", "ELECTRONICS",
                    "PHARMACEUTICAL", "FOOD_PRODUCTS", "CHEMICALS", "TEXTILES",
                ])),
                "requires_temp_control": str(rtc).lower(),
            })

        df = pd.DataFrame(rows_out)
        df.to_csv(
            os.path.join(workspace, f"cargo_batch_{file_idx+1:03d}.csv"),
            index=False,
        )

    print(f"Database: {n_containers} containers, {len(cells)} cells ({n_bays} bays), "
          f"{len(transport)} bookings, {len(current_plan)} assignments")
    print(f"Workspace: {n_files} cargo batch files + 4 config files")
    print(f"Layout: {n_bays} bays x {tiers_per_bay} tiers x {rows_per_bay} rows = {len(cells)} cells")
    print(f"Types: {n_20ft} 20ft containers, {n_40ft} 40ft containers")
    print(f"Bays: {n_20ft_bays} 20ft bays, {n_40ft_bays} 40ft bays")
    print(f"Reefer bays: {sorted(reefer_bays)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
