"""Generate diverse scenario topics for Agent task synthesis.

Usage:
    python generate_topics.py --num 20
    python generate_topics.py --num 50 --output topics_en_new.json
    python generate_topics.py --disable_filtering --num 30
"""

import argparse
import asyncio
import json
import random
import re
from pathlib import Path
from typing import Dict, List, Tuple

from openai import AsyncOpenAI

# ---------------------------------------------------------------------------
# Domain categories — organized by group for stratified sampling
#
# Design principles:
#   1. No semantic overlap between categories within or across groups
#   2. Each category should naturally support ≥4 tables and multi-step queries
#   3. Consistent granularity: specific enough to guide generation,
#      broad enough to allow diverse scenarios
#   4. Categories that were too abstract or too niche for structured
#      Agent tasks have been removed or merged
# ---------------------------------------------------------------------------

CATEGORY_GROUPS: dict[str, list[str]] = {
    "Operations & Logistics": [
        "Warehouse Fulfillment Logistics",
        "Airport Ground Operations",
        "Port Cargo Scheduling",
        "Pharmaceutical Cold Chain Logistics",
        "Last-Mile Delivery Route Optimization",
        "Supply Chain Risk Monitoring",
        "Freight Forwarding Shipment Tracking",
        "Customs Brokerage Declaration Processing",
    ],
    "Retail & Hospitality": [
        "Chain Restaurant Operations",
        "Hotel Reservation Management",
        "Supermarket Inventory Replenishment",
        "E-commerce Order Fulfillment",
        "E-commerce Promotional Campaign Management",
        "Dynamic Pricing Optimization",
        "Subscription Box Demand Forecasting",
        "Loyalty Program Points Management",
    ],
    "Healthcare": [
        "Hospital Emergency Room Management",
        "Blood Bank Inventory Management",
        "Emergency Dispatch Resource Deployment",
        "Remote Patient Monitoring Alert Triage",
        "Clinical Trial Patient Enrollment",
        "Medical Insurance Claims Adjudication",
        "Pharmaceutical Drug Interaction Monitoring",
        "Hospital Operating Room Scheduling",
    ],
    "Education & Research": [
        "Online Education Platform Operations",
        "University Library Resource Management",
        "Curriculum Prerequisite Tracking",
        "K-12 School Timetabling",
        "Academic Peer Review Workflow Management",
        "Academic Research Grant Administration",
        "University Course Registration System",
    ],
    "IT & Enterprise": [
        "IT Help Desk Ticketing System",
        "Data Center Operations Management",
        "Software Development Project Tracking",
        "Enterprise Recruitment Pipeline Management",
        "Cloud Cost Optimization",
        "Multi-Cloud Resource Orchestration",
        "Cybersecurity Incident Response",
        "Enterprise Access Permission Management",
    ],
    "Software Engineering": [
        "Repository Branch Management",
        "Code Review Assignment Workflow",
        "CI/CD Pipeline Configuration",
        "Dependency Vulnerability Scanning",
        "Microservice Deployment Orchestration",
        "Bug Triage Priority Classification",
        "Feature Flag Rollout Management",
        "API Gateway Rate Limiting Configuration",
    ],
    "Urban & Infrastructure": [
        "Residential Property Management",
        "Municipal Waste Collection Routing",
        "Smart Grid Energy Dispatch",
        "Commercial Construction Project Control",
        "Municipal Permit Processing",
        "Water Resource Distribution Tracking",
        "Urban Traffic Signal Optimization",
    ],
    "Finance & Banking": [
        "Bank Branch Service Management",
        "Multi-Party Contract Lifecycle Management",
        "Investment Portfolio Rebalancing",
        "Loan Origination Processing",
        "Credit Risk Assessment",
        "Cross-Border Payment Settlement",
        "Venture Capital Deal Flow Management",
        "Anti-Money Laundering Transaction Screening",
    ],
    "Government & Public Administration": [
        "Government Service Center Operations",
        "Public Records Request Processing",
        "Municipal Budget Allocation Tracking",
        "Immigration Case Workflow Management",
        "Public Procurement Bidding Management",
        "Social Welfare Benefits Administration",
    ],
    "Consumer Services": [
        "Travel Booking Itinerary Planning",
        "Food Delivery Kitchen Coordination",
        "Delivery Rider Dispatch Optimization",
        "Grocery Shopping Substitution Logic",
        "Real Estate Tenant Screening",
        "Event Ticketing Management",
        "Home Repair Service Marketplace",
    ],
    "Media & Entertainment": [
        "Content Recommendation Engine",
        "Music Royalty Distribution",
        "Gaming Platform Economy Management",
        "Editorial Publishing Workflow",
        "Film Production Scheduling",
        "Esports Tournament Bracket Management",
        "Podcast Distribution Analytics",
    ],
    "Agriculture & Environment": [
        "Agricultural Supply Chain Traceability",
        "Precision Farming Resource Allocation",
        "Environmental Compliance Monitoring",
        "Livestock Health Tracking",
        "Fishery Quota Allocation Tracking",
        "Seed Certification Lot Tracking",
    ],
    "Manufacturing & Industrial": [
        "Discrete Manufacturing Production Planning",
        "Predictive Equipment Maintenance",
        "Bill of Materials Management",
        "Factory Floor Shift Scheduling",
        "Raw Material Procurement Planning",
        "Quality Control Defect Tracking",
    ],
    "Telecommunications": [
        "Network Fault Detection Triage",
        "Cell Tower Capacity Planning",
        "Customer Service Ticket Routing",
        "Telecom Billing Dispute Resolution",
        "Mobile Network Subscriber Churn Prediction",
        "Telecom Interconnect Settlement",
    ],
    "Professional Services": [
        "Legal Case Discovery Document Review",
        "Intellectual Property Licensing Management",
        "Franchise Compliance Monitoring",
        "Consulting Project Resource Allocation",
        "Architecture Firm Project Portfolio Management",
        "Accounting Firm Audit Engagement Management",
    ],
    "Insurance": [
        "Property Insurance Claims Processing",
        "Insurance Underwriting Risk Evaluation",
        "Reinsurance Treaty Management",
        "Fraud Detection Case Investigation",
        "Health Insurance Provider Network Management",
        "Workers Compensation Case Management",
    ],
    "Transportation & Mobility": [
        "Ride-Hailing Driver Dispatch",
        "Railway Timetable Scheduling",
        "Fleet Vehicle Maintenance Scheduling",
        "Electric Vehicle Charging Network Scheduling",
        "Airline Crew Scheduling",
        "Public Bike Sharing Rebalancing",
    ],
    "Sports & Recreation": [
        "Sports Team Roster Management",
        "Match Fixture Scheduling",
        "Athlete Performance Tracking",
        "Stadium Event Operations",
        "Sports League Transfer Window Management",
        "Youth Academy Player Development Pipeline",
    ],
    "Web Research & Information": [
        "Competitive Intelligence Gathering",
        "Product Price Comparison Monitoring",
        "Public Sentiment Tracking",
        "Regulatory Change Monitoring",
        "Job Market Talent Mapping",
    ],
    "Location & Geospatial": [
        "Store Location Suitability Analysis",
        "Delivery Zone Partitioning",
        "Field Service Technician Routing",
        "Evacuation Route Planning",
        "Cell Coverage Gap Analysis",
        "Fleet GPS Geofence Compliance Monitoring",
    ],
    "Financial Analysis & Reporting": [
        "Financial Statement Anomaly Detection",
        "Budget Variance Analysis",
        "Cash Flow Forecasting",
        "Merger Acquisition Valuation Modeling",
        "Tax Provision Calculation",
    ],
    "Energy & Utilities": [
        "Oil Refinery Production Scheduling",
        "Natural Gas Pipeline Flow Optimization",
        "Renewable Energy Certificate Trading",
        "Utility Meter Reading Billing Reconciliation",
        "Power Plant Outage Planning",
    ],
    "Nonprofit & Philanthropy": [
        "Donation Campaign Fundraising Tracking",
        "Volunteer Shift Coordination",
        "Grant Application Review Pipeline",
        "Nonprofit Program Impact Measurement",
        "In-Kind Donation Inventory Distribution",
    ],
}

# Flat list for backward compatibility
CATEGORIES: List[str] = [
    cat for cats in CATEGORY_GROUPS.values() for cat in cats
]


# ---------------------------------------------------------------------------
# Stratified sampling
# ---------------------------------------------------------------------------


def stratified_sample_categories(
    groups: Dict[str, List[str]],
    n: int,
) -> List[str]:
    """
    Sample categories proportionally from each group so that every domain
    is represented rather than letting large groups dominate.

    Strategy:
      1. Each group gets at least 1 slot (if n >= num_groups).
      2. Remaining slots are distributed proportionally to group size.
      3. Within each group, categories are sampled randomly.
    """
    group_names = list(groups.keys())
    num_groups = len(group_names)
    total_cats = sum(len(v) for v in groups.values())
    n = min(n, total_cats)

    if n <= 0:
        return []

    # --- allocate slots per group ---
    # Phase 1: guarantee at least 1 per group (up to n)
    base = min(1, n // num_groups) if num_groups <= n else 0
    slots = {g: base for g in group_names}
    remaining = n - sum(slots.values())

    if base == 0:
        # n < num_groups → just pick n groups each with 1 slot
        chosen_groups = random.sample(group_names, n)
        slots = {g: (1 if g in chosen_groups else 0) for g in group_names}
        remaining = 0

    # Phase 2: distribute remaining proportionally
    if remaining > 0:
        weights = {g: len(groups[g]) for g in group_names}
        total_weight = sum(weights.values())
        fractional = {g: remaining * weights[g] / total_weight for g in group_names}
        # Floor allocation
        extra = {g: int(fractional[g]) for g in group_names}
        for g in group_names:
            slots[g] += extra[g]
        leftover = remaining - sum(extra.values())
        # Distribute leftover by largest fractional remainder
        remainders = sorted(
            group_names,
            key=lambda g: fractional[g] - extra[g],
            reverse=True,
        )
        for g in remainders[:leftover]:
            slots[g] += 1

    # --- sample within each group ---
    result: List[str] = []
    for g in group_names:
        k = min(slots[g], len(groups[g]))
        if k > 0:
            result.extend(random.sample(groups[g], k))

    random.shuffle(result)
    return result[:n]


# ---------------------------------------------------------------------------
# Seed loader
# ---------------------------------------------------------------------------


def load_seed_topics(filepath: str) -> List[str]:
    """Load seed topics from existing topics.json (list of {TOPIC, TASK_FOLDER})."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [
            item.get("TOPIC") or item.get("topic", "")
            for item in data
            if "TOPIC" in item or "topic" in item
        ]
    return []


def select_seed_examples(seed_pool: List[str], n: int = 5) -> List[str]:
    """Randomly select n seed examples from the pool."""
    if not seed_pool:
        return []
    return random.sample(seed_pool, min(n, len(seed_pool)))


# ---------------------------------------------------------------------------
# Topic generation
# ---------------------------------------------------------------------------


async def generate_topics(
    api_key: str,
    model: str,
    category: str,
    seed_examples: List[str],
    num_topics: int,
    base_url: str = "https://openrouter.ai/api/v1",
) -> List[Dict[str, str]]:
    """
    Generate topics for a given category using LLM.

    Returns a list of dicts: [{"topic": "...", "folder": "..."}, ...]
    """
    seed_text = "\n".join(f"- {t}" for t in seed_examples) if seed_examples else "(none)"

    prompt = f"""Here are some existing task examples for reference:
{seed_text}

Generate {num_topics} brand-new task descriptions for the domain "{category}".

Requirements:
- Length: 20-50 words.
- Realistic and plausible in everyday business/operations.
- Involves more than 3 data entities with meaningful data volume.
- Describes an operational workflow that concludes with an actionable verifiable output.

Output a JSON array only. Each element must have:
- "topic": the task topic description.
- "folder": a unique short snake_case directory name.

Output only the JSON array."""

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
    )
    content = response.choices[0].message.content
    if not content:
        print(f"  Warning: generation returned empty content for category '{category}'")
        return []
    raw = content.strip()

    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end > start:
            items = json.loads(raw[start:end])
            return [i for i in items if "topic" in i and "folder" in i]
    except Exception as e:
        print(f"  Warning: failed to parse generation response: {e}")
        print(f"  Raw: {raw[:300]}")
    return []


# ---------------------------------------------------------------------------
# Quality filtering
# ---------------------------------------------------------------------------


async def filter_topics(
    api_key: str,
    model: str,
    topics: List[str],
    category: str,
    threshold: float,
    base_url: str = "https://openrouter.ai/api/v1",
) -> List[Dict]:
    """
    Score each topic on 4 dimensions and apply threshold filter.

    Dimensions:
      - data_richness:  Does it naturally imply ≥4 tables and ≥200 rows of data?
      - entity_clarity: Are the key entities and their relationships identifiable?
      - task_suitability: Is it suitable for a multi-step retrieval/planning Agent task?
      - scenario_authenticity: Are the entities everyday, real-world business objects AND does the task address a genuine operational need?
    """
    topics_json = json.dumps(topics, ensure_ascii=False, indent=2)

    criteria = """
1. **data_richness (0-10)**: Does the scenario naturally imply multiple joinable data sources?
   - 8-10: Implies ≥4 distinct, real-world data sources (logs, timestamps, invoices, sensors, schedules) with clear join keys
   - 4-7: Implies 2-3 data sources, joins are simple or implied
   - 0-3: Implies 1 data source or only abstract "data"

2. **entity_clarity (0-10)**: Are the entities and their functional roles in the decision logic clearly distinguishable?
   - 8-10: Each entity has a distinct role (e.g., constraint, target, context, reference). A third party could write the join logic from the description.
   - 4-7: Entities are listed but their functional roles overlap or are unclear
   - 0-3: Entities are vague or interchangeable

3. **task_suitability (0-10)**: Does the task require multi-step reasoning with a verifiable output, AND scale naturally with data volume?
   - 8-10: Requires: (a) filtering/joining multiple sources, (b) applying business rules/thresholds, (c) producing a filtered list where each item has a traceable justification, AND (d) the workload scales with input volume — the task operates over "all / every / each" items (e.g., "all pending claims", "every adjuster"), and the output is a list or per-item report whose size grows with the data, not a single scalar or fixed-size summary
   - 4-7: Requires 1-2 of the above, or output is a single aggregate (report/summary), or the task targets a fixed small number of items regardless of data size
   - 0-3: Single-step lookup, simple aggregation, or task is about "the 3 files" / "this one record" (no scale axis at all)

4. **scenario_authenticity (0-10)**: Are the entities everyday, real-world business objects AND does this task address a genuine operational need?
   - 8-10: Entities are commonplace in business systems (delivery logs, GPS tracks, attendance records, invoices, thermometers, timetables) AND the task solves a real pain point that operations teams actively track or would want automated (e.g., penalty reconciliation, inventory count adjustment, compliance violation detection, eligibility verification)
   - 4-7: Entities are mostly real but one feels vague or invented, OR the task is plausible but no one is actively losing sleep over it
   - 0-3: Entities feel invented or purely academic ("customer sentiment neural embedding", "blockchain trust score"), OR the task feels like a hypothetical exercise with no real-world stakeholder"""

    prompt = f"""Evaluate these scenario topics for Agent task synthesis quality.
Category: "{category}"
{criteria}

Topics:
{topics_json}

Return ONLY a JSON array:
[
  {{
    "topic": "...",
    "data_richness": 8.5,
    "entity_clarity": 9.0,
    "task_suitability": 8.0,
    "scenario_authenticity": 8.5
  }},
  ...
]"""

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
    )
    content = response.choices[0].message.content
    if not content:
        print(f"  Warning: filter returned empty content for category '{category}', passing all topics")
        return [{"topic": t, "score": None, "passed": True} for t in topics]
    raw = content.strip()

    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end > start:
            scored = json.loads(raw[start:end])
            result = []
            for topic in topics:
                match = next((s for s in scored if s.get("topic") == topic), None)
                if match:
                    dr = match.get("data_richness", 5.0)
                    ec = match.get("entity_clarity", 5.0)
                    ts = match.get("task_suitability", 5.0)
                    sa = match.get("scenario_authenticity", 5.0)
                else:
                    dr = ec = ts = sa = 5.0
                avg = (dr + ec + ts + sa) / 4.0
                passed = all(
                    v >= threshold for v in [dr, ec, ts, sa]
                )
                result.append({
                    "topic": topic,
                    "data_richness": dr,
                    "entity_clarity": ec,
                    "task_suitability": ts,
                    "scenario_authenticity": sa,
                    "score": round(avg, 2),
                    "passed": passed,
                })
            return result
    except Exception as e:
        print(f"  Warning: failed to parse filter response: {e}")
        print(f"  Raw: {raw[:300]}")

    # Fallback: default scores (below threshold → won't pass)
    return [
        {
            "topic": t,
            "data_richness": 5.0,
            "entity_clarity": 5.0,
            "task_suitability": 5.0,
            "scenario_authenticity": 5.0,
            "score": 5.0,
            "passed": False,
        }
        for t in topics
    ]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def save_output(entries: List[Dict], output_file: str) -> None:
    """Save kept topics as JSON list with TOPIC and TASK_FOLDER fields."""
    kept = [e for e in entries if e.get("kept", False)]
    result = [
        {
            "TOPIC": e["topic"],
            "TASK_FOLDER": e["folder"],
        }
        for e in kept
    ]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(result)} topics → {output_file}")


def save_detailed_log(entries: List[Dict], output_file: str) -> None:
    """Save full scoring details for debugging / analysis."""
    log_file = output_file.replace(".json", "_detailed.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f"Detailed log → {log_file}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TOPICS_PER_CATEGORY = 2
SEED_EXAMPLES = 3
FILTER_THRESHOLD = 8.5

# Provider presets
PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "gen_model": "google/gemini-3-flash-preview",
        "filter_model": "google/gemini-3-flash-preview",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": "KIMI_API_KEY",
        "gen_model": "kimi-k2.5",
        "filter_model": "kimi-k2.5",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "gen_model": "deepseek-chat",
        "filter_model": "deepseek-chat",
    },
}


async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate scenario topics for Agent task synthesis"
    )
    parser.add_argument(
        "seed_file",
        nargs="?",
        default="topics/topics.json",
        help="Seed topics JSON file (default: topics/topics.json)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="generated_topics.json",
        help="Output JSON file (default: generated_topics.json)",
    )
    parser.add_argument(
        "--num",
        type=int,
        default=20,
        help="Approximate number of topics to generate (default: 20)",
    )
    parser.add_argument(
        "--disable_filtering",
        action="store_true",
        help="Skip quality filtering (keep all generated topics)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="openrouter",
        choices=list(PROVIDERS.keys()),
        help="API provider to use (default: openrouter)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=FILTER_THRESHOLD,
        help=f"Min score per dimension to keep a topic (default: {FILTER_THRESHOLD})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Max concurrent API requests (default: 10)",
    )
    args = parser.parse_args()

    provider_cfg = PROVIDERS[args.provider]
    base_url = provider_cfg["base_url"]
    api_key = __import__("os").environ.get(provider_cfg["api_key_env"], "")
    if not api_key:
        raise ValueError(f"{provider_cfg['api_key_env']} env var required")
    gen_model = provider_cfg["gen_model"]
    filter_model = provider_cfg["filter_model"]
    print(f"Provider: {args.provider} | Base URL: {base_url}")

    # Load seed pool
    seed_pool: List[str] = []
    seed_file = Path(args.seed_file)
    if seed_file.exists():
        seed_pool = load_seed_topics(str(seed_file))
        print(f"Loaded {len(seed_pool)} seed topics from {seed_file}")
    else:
        print(f"Seed file '{seed_file}' not found — proceeding without seeds")

    # --- Stratified category selection ---
    num_categories = max(1, round(args.num / TOPICS_PER_CATEGORY))
    selected_categories = stratified_sample_categories(CATEGORY_GROUPS, num_categories)
    print(
        f"Selected {len(selected_categories)} categories "
        f"(stratified across {len(CATEGORY_GROUPS)} groups), "
        f"concurrency={args.concurrency}\n"
    )

    semaphore = asyncio.Semaphore(args.concurrency)
    completed = 0
    total = len(selected_categories)
    print_lock = asyncio.Lock()

    async def process_category(
        idx: int, category: str, seed_pool: List[str]
    ) -> Tuple[str, List[Dict]]:
        """Generate and optionally filter topics for one category."""
        async with semaphore:
            seed_examples = select_seed_examples(seed_pool, n=SEED_EXAMPLES)
            candidates = await generate_topics(
                api_key=api_key,
                model=gen_model,
                category=category,
                seed_examples=seed_examples,
                num_topics=TOPICS_PER_CATEGORY,
                base_url=base_url,
            )

            entries: List[Dict] = []

            if not candidates:
                async with print_lock:
                    nonlocal completed
                    completed += 1
                    print(f"[{completed}/{total}] {category} — 0 candidates")
                return category, entries

            topic_texts = [c["topic"] for c in candidates]
            folder_map = {c["topic"]: c["folder"] for c in candidates}

            if args.disable_filtering:
                for c in candidates:
                    entries.append({
                        "topic": c["topic"],
                        "folder": c["folder"],
                        "category": category,
                        "score": None,
                        "kept": True,
                    })
                async with print_lock:
                    completed += 1
                    print(
                        f"[{completed}/{total}] {category} — "
                        f"kept {len(candidates)}/{len(candidates)} (filtering disabled)"
                    )
            else:
                scored = await filter_topics(
                    api_key=api_key,
                    model=filter_model,
                    topics=topic_texts,
                    category=category,
                    threshold=args.threshold,
                    base_url=base_url,
                )
                kept_count = 0
                for s in scored:
                    topic = s["topic"]
                    kept = s["passed"]
                    entries.append({
                        **s,
                        "category": category,
                        "folder": folder_map.get(
                            topic, re.sub(r"\W+", "_", topic[:30]).lower()
                        ),
                        "kept": kept,
                    })
                    if kept:
                        kept_count += 1
                async with print_lock:
                    completed += 1
                    print(
                        f"[{completed}/{total}] {category} — "
                        f"kept {kept_count}/{len(candidates)}"
                    )

            return category, entries

    # Run all categories concurrently
    tasks = [
        process_category(i, cat, seed_pool)
        for i, cat in enumerate(selected_categories, 1)
    ]
    results: List[Tuple[str, List[Dict]]] = await asyncio.gather(*tasks)

    all_entries: List[Dict] = []
    for _category, entries in results:
        all_entries.extend(entries)

    # --- Save ---
    save_output(all_entries, args.output)
    save_detailed_log(all_entries, args.output)
    total_kept = sum(1 for e in all_entries if e.get("kept"))
    print(f"\nTotal kept: {total_kept}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()