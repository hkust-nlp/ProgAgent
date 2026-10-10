import argparse
import sqlite3
import os
import json
import csv
import math
import numpy as np
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 400,        # v2 = 4x base
    "num_workspace_files": 30,    # v2 = base + 2N
}

DATACENTERS = ["DC-EAST", "DC-WEST", "DC-CENTRAL"]
CPU_CORE_OPTIONS = [8, 16, 32, 64]
RAM_OPTIONS = [32, 64, 128, 256]
DISK_OPTIONS = [1, 2, 4, 8]
RATED_POWER_MAP = {8: 250, 16: 400, 32: 650, 64: 1000}

SERVICE_TEMPLATES = [
    "auth-service", "user-api", "payment-gateway", "order-processor",
    "inventory-manager", "search-engine", "notification-service", "logging-daemon",
    "metrics-collector", "cache-proxy", "api-gateway", "web-frontend",
    "data-pipeline", "report-generator", "analytics-engine", "billing-service",
    "shipping-tracker", "config-server", "health-monitor", "session-manager",
    "email-sender", "sms-gateway", "file-storage", "image-processor",
    "queue-worker", "scheduler-service", "backup-agent", "sync-service",
    "rate-limiter", "load-balancer", "dns-resolver", "cert-manager",
    "audit-logger", "token-validator", "event-bus", "task-runner",
    "db-proxy", "secret-store", "feature-flag", "ab-testing",
]

CRITICALITY_LEVELS = ["critical", "high", "medium", "low"]
CRITICALITY_WEIGHTS = [0.08, 0.22, 0.40, 0.30]


def create_tables(cur):
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS servers (
            server_id TEXT PRIMARY KEY,
            hostname TEXT NOT NULL,
            datacenter TEXT NOT NULL,
            rack_id TEXT NOT NULL,
            cpu_cores INTEGER NOT NULL,
            ram_gb INTEGER NOT NULL,
            disk_tb INTEGER NOT NULL,
            os_type TEXT NOT NULL,
            status TEXT NOT NULL,
            commission_date TEXT NOT NULL,
            server_type TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cpu_utilization (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            log_date TEXT NOT NULL,
            avg_cpu_pct REAL NOT NULL,
            peak_cpu_pct REAL NOT NULL,
            min_cpu_pct REAL NOT NULL,
            FOREIGN KEY (server_id) REFERENCES servers(server_id)
        );
        CREATE TABLE IF NOT EXISTS power_consumption (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            reading_date TEXT NOT NULL,
            avg_watts REAL NOT NULL,
            peak_watts REAL NOT NULL,
            FOREIGN KEY (server_id) REFERENCES servers(server_id)
        );
        CREATE TABLE IF NOT EXISTS vm_assignments (
            vm_id TEXT PRIMARY KEY,
            vm_name TEXT NOT NULL,
            host_server_id TEXT NOT NULL,
            vcpus_allocated INTEGER NOT NULL,
            ram_allocated_gb INTEGER NOT NULL,
            disk_allocated_gb INTEGER NOT NULL,
            vm_status TEXT NOT NULL,
            FOREIGN KEY (host_server_id) REFERENCES servers(server_id)
        );
        CREATE TABLE IF NOT EXISTS service_registry (
            service_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            server_id TEXT NOT NULL,
            criticality TEXT NOT NULL,
            port INTEGER NOT NULL,
            protocol TEXT NOT NULL,
            FOREIGN KEY (server_id) REFERENCES servers(server_id)
        );
    """)


def generate_servers(num_servers, rng, fake):
    servers = []
    type_rolls = rng.random(num_servers)
    status_rolls = rng.random(num_servers)
    underutil_rolls = rng.random(num_servers)

    for i in range(num_servers):
        server_id = f"SRV-{i+1:04d}"
        hostname = f"srv-{fake.lexify('??????')}-{i+1:03d}.internal"

        dc = DATACENTERS[i % len(DATACENTERS)]
        num_racks = max(10, num_servers // 5)
        rack_id = f"R-{(i % num_racks) + 1:02d}"

        cpu_cores = int(rng.choice(CPU_CORE_OPTIONS))
        ram_gb = int(rng.choice(RAM_OPTIONS))
        disk_tb = int(rng.choice(DISK_OPTIONS))
        os_type = "Linux" if rng.random() < 0.75 else "Windows"

        # Status: ~85% active, ~10% maintenance, ~5% decommissioned
        sr = status_rolls[i]
        if sr < 0.85:
            status = "active"
        elif sr < 0.95:
            status = "maintenance"
        else:
            status = "decommissioned"

        # Server type: ~75% physical, ~25% vm_host
        server_type = "vm_host" if type_rolls[i] < 0.25 else "physical"

        days_ago = int(rng.integers(365, 365 * 5))
        commission_date = (datetime(2026, 1, 1) - timedelta(days=days_ago)).strftime("%Y-%m-%d")

        # Mark underutilized: ~18% of active servers
        is_underutilized = (status == "active" and underutil_rolls[i] < 0.18)

        servers.append({
            "server_id": server_id,
            "hostname": hostname,
            "datacenter": dc,
            "rack_id": rack_id,
            "cpu_cores": cpu_cores,
            "ram_gb": ram_gb,
            "disk_tb": disk_tb,
            "os_type": os_type,
            "status": status,
            "commission_date": commission_date,
            "server_type": server_type,
            "is_underutilized": is_underutilized,
            "rated_power_watts": RATED_POWER_MAP[cpu_cores],
        })

    return servers


def insert_servers(cur, servers):
    for s in servers:
        cur.execute(
            "INSERT INTO servers VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (s["server_id"], s["hostname"], s["datacenter"], s["rack_id"],
             s["cpu_cores"], s["ram_gb"], s["disk_tb"], s["os_type"],
             s["status"], s["commission_date"], s["server_type"])
        )


def generate_cpu_utilization(cur, servers, rng):
    base_date = datetime(2025, 12, 31)
    rows = []
    for s in servers:
        if s["status"] == "decommissioned":
            # Still generate minimal logs for decommissioned (they existed before)
            pass
        for day_offset in range(90):
            log_date = (base_date - timedelta(days=89 - day_offset)).strftime("%Y-%m-%d")
            if s["is_underutilized"]:
                avg_cpu = float(np.clip(rng.normal(8.0, 2.5), 1.0, 13.5))
            elif s["status"] == "active":
                avg_cpu = float(np.clip(rng.normal(52.0, 15.0), 16.0, 95.0))
            else:
                avg_cpu = float(np.clip(rng.normal(30.0, 20.0), 0.5, 95.0))

            peak_cpu = float(np.clip(avg_cpu + abs(rng.normal(0, 8.0)), avg_cpu, 100.0))
            min_cpu = float(np.clip(avg_cpu - abs(rng.normal(0, 5.0)), 0.0, avg_cpu))
            rows.append((s["server_id"], log_date, round(avg_cpu, 2),
                         round(peak_cpu, 2), round(min_cpu, 2)))

    cur.executemany(
        "INSERT INTO cpu_utilization (server_id, log_date, avg_cpu_pct, peak_cpu_pct, min_cpu_pct) VALUES (?,?,?,?,?)",
        rows
    )


def generate_power_consumption(cur, servers, rng):
    base_date = datetime(2025, 12, 31)
    rows = []
    for s in servers:
        rated = s["rated_power_watts"]
        for day_offset in range(90):
            reading_date = (base_date - timedelta(days=89 - day_offset)).strftime("%Y-%m-%d")
            if s["is_underutilized"]:
                cpu_proxy = float(np.clip(rng.normal(8.0, 2.5), 1.0, 13.5))
            elif s["status"] == "active":
                cpu_proxy = float(np.clip(rng.normal(52.0, 15.0), 16.0, 95.0))
            else:
                cpu_proxy = float(np.clip(rng.normal(30.0, 20.0), 0.5, 95.0))

            # Power model: idle ~20% of rated, scales linearly with CPU
            noise_factor = float(np.clip(rng.normal(1.0, 0.03), 0.90, 1.10))
            avg_watts = rated * (0.20 + (cpu_proxy / 100.0) * 0.80) * noise_factor
            peak_watts = avg_watts * float(np.clip(rng.normal(1.15, 0.05), 1.05, 1.40))

            rows.append((s["server_id"], reading_date, round(avg_watts, 2), round(peak_watts, 2)))

    cur.executemany(
        "INSERT INTO power_consumption (server_id, reading_date, avg_watts, peak_watts) VALUES (?,?,?,?)",
        rows
    )


def generate_vm_assignments(cur, servers, rng, fake):
    vm_hosts = [s for s in servers if s["server_type"] == "vm_host" and s["status"] != "decommissioned"]
    num_servers_total = len(servers)
    target_vms = max(SCALE["rows_per_table"], len(vm_hosts) * 4)

    # Distribute VMs across hosts
    vms_per_host = {}
    remaining = target_vms
    for i, host in enumerate(vm_hosts):
        if i == len(vm_hosts) - 1:
            count = remaining
        else:
            count = max(2, int(rng.integers(3, 6)))
            count = min(count, remaining)
        vms_per_host[host["server_id"]] = count
        remaining -= count
        if remaining <= 0:
            break

    # If remaining > 0, distribute more
    if remaining > 0:
        idx = 0
        while remaining > 0:
            host_id = vm_hosts[idx % len(vm_hosts)]["server_id"]
            vms_per_host[host_id] = vms_per_host.get(host_id, 0) + 1
            remaining -= 1
            idx += 1

    vm_counter = 0
    rows = []
    vm_name_parts = ["web", "app", "db", "cache", "worker", "proxy", "api", "batch", "monitor", "test"]
    for host_id, count in vms_per_host.items():
        host_info = next(s for s in servers if s["server_id"] == host_id)
        for j in range(count):
            vm_counter += 1
            vm_id = f"VM-{vm_counter:04d}"
            part = vm_name_parts[vm_counter % len(vm_name_parts)]
            vm_name = f"{part}-vm-{vm_counter:03d}"
            vcpus = int(rng.choice([1, 2, 4, 8]))
            ram_gb = int(rng.choice([4, 8, 16, 32]))
            disk_gb = int(rng.choice([50, 100, 200, 500]))
            vm_status = "running" if rng.random() < 0.85 else "stopped"
            rows.append((vm_id, vm_name, host_id, vcpus, ram_gb, disk_gb, vm_status))

    cur.executemany(
        "INSERT INTO vm_assignments VALUES (?,?,?,?,?,?,?)", rows
    )


def generate_services(cur, servers, rng):
    active_servers = [s for s in servers if s["status"] == "active"]
    num_services = max(SCALE["rows_per_table"], int(len(active_servers) * 1.5))

    services = []
    svc_counter = 0
    # Assign services to active servers
    # Each active server gets 0-4 services; ensure total >= num_services
    assignments = []
    for s in active_servers:
        count = int(rng.choice([0, 1, 1, 2, 2, 2, 3]))
        assignments.append((s["server_id"], count))

    total_assigned = sum(c for _, c in assignments)
    # Top up if needed
    while total_assigned < num_services:
        idx = int(rng.integers(0, len(assignments)))
        sid, c = assignments[idx]
        assignments[idx] = (sid, c + 1)
        total_assigned += 1

    for server_id, count in assignments:
        for _ in range(count):
            svc_counter += 1
            service_id = f"SVC-{svc_counter:04d}"
            template_idx = (svc_counter - 1) % len(SERVICE_TEMPLATES)
            suffix = (svc_counter - 1) // len(SERVICE_TEMPLATES)
            if suffix == 0:
                service_name = SERVICE_TEMPLATES[template_idx]
            else:
                service_name = f"{SERVICE_TEMPLATES[template_idx]}-{suffix:02d}"

            criticality = str(rng.choice(CRITICALITY_LEVELS, p=CRITICALITY_WEIGHTS))
            port = int(rng.choice([80, 443, 3000, 3306, 5432, 6379, 8080, 8443, 9090, 9200]))
            protocol = str(rng.choice(["TCP", "HTTP", "HTTPS", "gRPC"]))

            services.append({
                "service_id": service_id,
                "service_name": service_name,
                "server_id": server_id,
                "criticality": criticality,
                "port": port,
                "protocol": protocol,
            })

    cur.executemany(
        "INSERT INTO service_registry VALUES (?,?,?,?,?,?)",
        [(s["service_id"], s["service_name"], s["server_id"],
          s["criticality"], s["port"], s["protocol"]) for s in services]
    )

    return services


def generate_service_dependencies(services, rng):
    """Generate a DAG of service dependencies. Returns {svc_id: [dep_svc_id, ...]}."""
    svc_ids = [s["service_id"] for s in services]
    deps = {}
    for i, svc_id in enumerate(svc_ids):
        # Each service can depend on 0-3 earlier services (ensures DAG)
        roll = rng.random()
        if roll < 0.45:
            num_deps = 0
        elif roll < 0.75:
            num_deps = 1
        elif roll < 0.92:
            num_deps = 2
        else:
            num_deps = 3

        if i == 0 or num_deps == 0:
            deps[svc_id] = []
        else:
            max_candidates = min(i, 15)  # look back at most 15 services
            candidates = svc_ids[max(0, i - max_candidates):i]
            num_deps = min(num_deps, len(candidates))
            chosen = rng.choice(candidates, size=num_deps, replace=False).tolist()
            deps[svc_id] = chosen

    return deps


def generate_workspace(workspace, servers, services, service_deps, num_scalable_files, rng, fake):
    # --- Fixed configuration files ---

    # 1. consolidation_policy.yaml
    policy = {
        "cpu_threshold_pct": 15,
        "power_utilization_factor": 0.35,
        "criticality_weights": {
            "critical": 100,
            "high": 50,
            "medium": 20,
            "low": 5,
        },
        "dependency_weight": 30,
        "vm_host_penalty": 200,
        "phase_thresholds": {
            "phase_1_max": 0,
            "phase_2_max": 50,
            "phase_3_max": 200,
        },
    }
    with open(os.path.join(workspace, "consolidation_policy.yaml"), "w") as f:
        # Write YAML manually for clarity (avoid yaml dependency issues)
        f.write("cpu_threshold_pct: 15\n")
        f.write("power_utilization_factor: 0.35\n")
        f.write("criticality_weights:\n")
        f.write("  critical: 100\n")
        f.write("  high: 50\n")
        f.write("  medium: 20\n")
        f.write("  low: 5\n")
        f.write("dependency_weight: 30\n")
        f.write("vm_host_penalty: 200\n")
        f.write("phase_thresholds:\n")
        f.write("  phase_1_max: 0\n")
        f.write("  phase_2_max: 50\n")
        f.write("  phase_3_max: 200\n")

    # 2. datacenter_config.json
    dc_config = {
        "DC-EAST": {"pue": 1.4, "electricity_cost_per_kwh": 0.12},
        "DC-WEST": {"pue": 1.2, "electricity_cost_per_kwh": 0.10},
        "DC-CENTRAL": {"pue": 1.3, "electricity_cost_per_kwh": 0.11},
    }
    with open(os.path.join(workspace, "datacenter_config.json"), "w") as f:
        json.dump(dc_config, f, indent=2)

    # 3. migration_priority_rules.md
    rules_md = """The migration priority score quantifies how difficult it is to decommission a given server. A lower score means the server is easier to retire and should be scheduled earlier.

To compute the score for a server, begin at zero. For every service currently running on that server, look up the service's criticality tier and add the corresponding weight from the consolidation policy's criticality_weights mapping. Next, consult the service dependency maps: for each service on the server, count how many services anywhere in the fleet list it as a direct dependency, then multiply that count by the dependency_weight value from the policy. If the server's type is vm_host, add the vm_host_penalty from the policy.

The sum of these three components is the migration priority score. Use the phase_thresholds section of the consolidation policy to assign a decommission phase: a server whose score equals the phase_1_max value belongs to phase one, a score above phase_1_max up to and including phase_2_max belongs to phase two, above phase_2_max up to and including phase_3_max belongs to phase three, and anything above phase_3_max falls into phase four.
"""
    with open(os.path.join(workspace, "migration_priority_rules.md"), "w") as f:
        f.write(rules_md)

    # --- Scalable data files ---
    num_spec_files = num_scalable_files // 2
    num_dep_files = num_scalable_files - num_spec_files

    # Server specification batch CSVs
    # Distribute all servers across spec files
    servers_shuffled = list(servers)  # keep original order for determinism
    chunk_size_spec = math.ceil(len(servers_shuffled) / num_spec_files)
    for file_idx in range(num_spec_files):
        start = file_idx * chunk_size_spec
        end = min(start + chunk_size_spec, len(servers_shuffled))
        batch = servers_shuffled[start:end]
        fname = f"server_specs_batch_{file_idx + 1:03d}.csv"
        with open(os.path.join(workspace, fname), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["server_id", "rated_power_watts", "cooling_btu_hr",
                             "rack_units", "warranty_end"])
            for s in batch:
                rated = s["rated_power_watts"]
                cooling_btu = round(rated * 3.412, 1)
                rack_units = {8: 1, 16: 1, 32: 2, 64: 4}[s["cpu_cores"]]
                years = int(rng.choice([3, 5]))
                comm = datetime.strptime(s["commission_date"], "%Y-%m-%d")
                warranty_end = (comm + timedelta(days=365 * years)).strftime("%Y-%m-%d")
                writer.writerow([s["server_id"], rated, cooling_btu, rack_units, warranty_end])

    # Service dependency batch JSONs
    svc_ids = list(service_deps.keys())
    chunk_size_dep = math.ceil(len(svc_ids) / num_dep_files)
    for file_idx in range(num_dep_files):
        start = file_idx * chunk_size_dep
        end = min(start + chunk_size_dep, len(svc_ids))
        batch_ids = svc_ids[start:end]
        batch_deps = {sid: service_deps[sid] for sid in batch_ids}
        fname = f"service_deps_batch_{file_idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(batch_deps, f, indent=2)


def main(db_path, workspace):
    np.random.seed(42)
    Faker.seed(42)
    fake = Faker()
    rng = np.random.default_rng(42)

    os.makedirs(workspace, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    create_tables(cur)

    num_servers = SCALE["rows_per_table"]
    num_scalable_files = SCALE["num_workspace_files"]

    # Generate and insert servers
    servers = generate_servers(num_servers, rng, fake)
    insert_servers(cur, servers)

    # Generate CPU utilization logs (90 days per server)
    generate_cpu_utilization(cur, servers, rng)

    # Generate power consumption (90 days per server)
    generate_power_consumption(cur, servers, rng)

    # Generate VM assignments
    generate_vm_assignments(cur, servers, rng, fake)

    # Generate services
    services = generate_services(cur, servers, rng)

    # Generate service dependency DAG
    service_deps = generate_service_dependencies(services, rng)

    # Generate workspace files
    generate_workspace(workspace, servers, services, service_deps,
                       num_scalable_files, rng, fake)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    main(args.db_path, args.workspace)
