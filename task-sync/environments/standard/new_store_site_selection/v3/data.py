#!/usr/bin/env python3
"""Data generation for retail site-selection task."""

import argparse
import csv
import json
import math
import os
import sqlite3

import numpy as np
import pandas as pd
import yaml
from faker import Faker

SCALE = {
    "rows_per_table": 400,      # v3 = 8 x 50
    "num_workspace_files": 32,  # v3 = 8 + 3*8
}

# ---------------------------------------------------------------------------
# Zone-name pool (deterministic, large enough for v3 = 400 zones)
# ---------------------------------------------------------------------------
_PREFIXES = [
    "Oakwood", "Pine Valley", "Cedar Ridge", "Maple Grove", "Elm Creek",
    "Riverside", "Lakewood", "Hilltop", "Stonebridge", "Silverdale",
    "Goldfield", "Irongate", "Sunset Cove", "Crystal Springs", "Amber Hills",
    "Coral Bay", "Harbor Point", "Glendale", "Brookside", "Sage Meadow",
    "Summit View", "Ridgewood", "Willow Park", "Aspen Heights", "Birch Hollow",
    "Hazelwood", "Ivy Court", "Fern Glen", "Mossfield", "Eagle Point",
    "Fox Run", "Wolf Creek", "Deer Springs", "Falcon Ridge", "Hawk Landing",
    "Pearl District", "Ruby Terrace", "Jade Gardens", "Onyx Square", "Slate Crossing",
    "Flintwood", "Thornberry", "Ashford", "Bellmont", "Claremont",
    "Davenport", "Eastgate", "Fairhaven", "Greenfield", "Hawthorne",
    "Kensington", "Lancaster", "Montclair", "Northridge", "Orchard Park",
    "Preston", "Queensbury", "Rosewood", "Sherwood", "Tidewater",
    "Upland", "Valencia", "Westbrook", "York Crossing", "Zenith Pointe",
    "Alderton", "Bayfield", "Coventry", "Dunmore", "Edgewood",
    "Foxglove", "Granville", "Hartfield", "Ingram", "Jasperdale",
    "Kelford", "Lindenwood", "Millbrook", "Newbury", "Oakmont",
    "Parklands", "Quail Hollow", "Redstone", "Sandpoint", "Thornhill",
    "Uniondale", "Vineland", "Windermere", "Xander Heights", "Yarmouth",
    "Ashton Gate", "Bramblewood", "Crestview", "Deerfield", "Evergreen",
    "Fieldstone", "Glenbrook", "Heatherwood", "Iron Hill", "Juniper Falls",
    "Kingsley", "Larchmont", "Meadowbrook", "Northgate", "Olive Grove",
    "Pebblewood", "Quarry Ridge", "Ravenwood", "Sprucefield", "Tamarack",
    "Underhill", "Verdant Cove", "Willowmere", "Xylo Heights", "Yewdale",
    "Aldermere", "Blueridge", "Copperfield", "Driftwood", "Elderwood",
    "Fairmont", "Goldenrod", "Hemlock Park", "Ivybridge", "Jasmine Court",
    "Knollwood", "Laurelwood", "Maplecrest", "Nutfield", "Osprey Point",
    "Pinehurst", "Quailridge", "Riverbend", "Stonecrest", "Tulipwood",
    "Upminster", "Velvetgrove", "Wickford", "Xerxes Hill", "Yellowstone Gate",
    "Azalea Park", "Boxwood", "Cedarbrook", "Dawnridge", "Elmhurst",
    "Fawndale", "Ginseng Valley", "Hollyhock", "Indigo Falls", "Juniperwood",
    "Kingsport", "Lilyfield", "Magnolia", "Nightingale", "Orchidwood",
    "Pecanridge", "Quartz Hollow", "Rosemere", "Sycamore", "Tanglewood",
    "Umberfield", "Violetdale", "Wisteriagate", "Xeniawood", "Yuccadale",
    "Zinnia Crossing", "Aldergrove", "Beechwood", "Cypress Point", "Dogwood",
    "Eucalyptus", "Firwood", "Ginkodale", "Hickory", "Irisfield",
    "Jacaranda", "Kumquat Hill", "Lilacwood", "Mulberry", "Nectarfield",
    "Olivewood", "Palmcrest", "Quincedale", "Redwoodgate", "Sassafras",
    "Teakwood", "Ulmfield", "Vineyard Crest", "Walnutdale", "Ximenia Park",
    "Yarrowfield", "Zebrawood Ridge", "Acorndale", "Birchfield", "Cloverhill",
    "Dahlia Point", "Edelweiss", "Forsythia Glen", "Gardenview", "Hibiscus",
    "Ivywood", "Jaderidge", "Kiwifield", "Lotusdale", "Mistletoe",
    "Narcissus", "Oleander", "Primrose", "Quillwood", "Rhododendron",
    "Sunflower", "Thistle Gate", "Umbrella Pine", "Verbena", "Wattle Crest",
    "Xyris Meadow", "Yarrowgate", "Zephyr Ridge", "Anemone", "Buttercup",
    "Chamomile", "Daisyfield", "Echinacea", "Frangipani", "Geranium",
    "Heliotrope", "Impatiens", "Jessamine", "Kalanchoe", "Lavender Hills",
    "Marigold", "Nemophila", "Oxalis", "Petunia", "Quassia",
    "Ranunculus", "Snapdragon", "Tuberose", "Ursinia", "Viola Crest",
    "Wisteria", "Xeranthemum", "Yarrow Bluff", "Zenobia Falls",
    "Agave Point", "Bergamot", "Camellia", "Dianthus", "Euphorbia",
    "Freesia", "Gladiolus", "Hyacinth", "Ixora", "Jonquil",
    "Kangaroo Paw", "Lupin", "Mimosa", "Nerine", "Orchid Gate",
    "Protea", "Queen Anne", "Rudbeckia", "Salvia", "Trillium",
    "Ulex Hill", "Vinca Ridge", "Waratah", "Xanthium", "Yucca Springs",
    "Zephyranthes", "Amaryllis", "Bougainvillea", "Chrysanthemum", "Delphinium",
    "Eremurus", "Foxglove Hill", "Gerbera", "Hellebore", "Iris Cove",
    "Jasmine Hills", "Kniphofia", "Leucadendron", "Mandevilla", "Nigella",
    "Osteospermum", "Phlox Crossing", "Quesnelia", "Ranunculus Hill", "Scabiosa",
    "Tillandsia", "Uvularia", "Vriesea", "Watsonia", "Xiphidium",
    "Yucca Point", "Zamia Ridge", "Alstroemeria", "Begonia", "Coreopsis",
    "Deutzia", "Eryngium", "Fuchsia", "Gazania", "Heuchera",
    "Incarvillea", "Jacobinia", "Kalmia", "Liatris", "Monarda",
    "Nemesia", "Orontium", "Pentas", "Quisqualis", "Roscoea",
    "Strelitzia", "Tigridia", "Urginea", "Veltheimia", "Weigela",
    "Xerochrysum", "Yucca Meadow", "Zauchneria",
]


# ===================================================================
# Database creation
# ===================================================================

def create_database(db_path):
    rng = np.random.RandomState(42)
    Faker.seed(42)
    fake = Faker()
    fake.seed_instance(42)

    n = SCALE["rows_per_table"]

    # ---- zone_demographics ----
    # Build a name pool large enough for any scale
    if n <= len(_PREFIXES):
        name_indices = rng.permutation(len(_PREFIXES))[:n]
        name_pool = [_PREFIXES[i] for i in name_indices]
    else:
        # Use all prefixes then generate extras deterministically
        base = list(_PREFIXES)
        rng_names = np.random.RandomState(42 + 7777)
        suffixes_extra = ["North", "South", "East", "West", "Upper", "Lower", "New", "Old"]
        while len(base) < n:
            idx = rng_names.randint(0, len(_PREFIXES))
            sfx = suffixes_extra[rng_names.randint(0, len(suffixes_extra))]
            candidate = f"{sfx} {_PREFIXES[idx]}"
            if candidate not in base:
                base.append(candidate)
        perm = rng.permutation(len(base))[:n]
        name_pool = [base[i] for i in perm]
    zones = []
    for i in range(n):
        zone_id = f"Z{i+1:03d}"
        zone_name = name_pool[i]
        # ~35% below population threshold
        if rng.random() < 0.35:
            population = int(rng.randint(6000, 15000))
        else:
            population = int(rng.randint(15000, 80000))
        # ~30% below income threshold
        if rng.random() < 0.30:
            median_household_income = int(rng.randint(25000, 40000))
        else:
            median_household_income = int(rng.randint(40000, 130000))
        median_age = round(float(rng.uniform(24, 58)), 1)
        household_count = int(population * rng.uniform(0.30, 0.45))
        employment_rate = round(float(rng.uniform(0.55, 0.96)), 3)
        population_growth_rate = round(float(rng.uniform(-1.5, 6.5)), 2)
        zones.append({
            "zone_id": zone_id, "zone_name": zone_name,
            "population": population,
            "median_household_income": median_household_income,
            "median_age": median_age, "household_count": household_count,
            "employment_rate": employment_rate,
            "population_growth_rate": population_growth_rate,
        })
    zones_df = pd.DataFrame(zones)

    # ---- candidate_sites ----
    CENTER_LAT, CENTER_LON = 40.7128, -74.0060
    site_types = ["street-level", "mall", "standalone", "mixed-use"]
    zone_ids = zones_df["zone_id"].tolist()
    weights = zones_df["population"].values.astype(float)
    weights /= weights.sum()
    assigned_zones = rng.choice(zone_ids, size=n, p=weights)

    sites = []
    for i in range(n):
        site_id = f"S{i+1:03d}"
        lat = round(CENTER_LAT + float(rng.uniform(-0.12, 0.12)), 6)
        lon = round(CENTER_LON + float(rng.uniform(-0.12, 0.12)), 6)
        r = rng.random()
        if r < 0.25:
            area = int(rng.randint(800, 2000))
        elif r < 0.75:
            area = int(rng.randint(2000, 7000))
        else:
            area = int(rng.randint(7000, 18000))
        sites.append({
            "site_id": site_id,
            "site_name": fake.company() + " Retail Space",
            "address": fake.street_address(),
            "zone_id": assigned_zones[i],
            "latitude": lat, "longitude": lon,
            "area_sqft": area,
            "site_type": str(rng.choice(site_types)),
            "parking_spaces": int(rng.randint(0, 80)),
            "frontage_meters": round(float(rng.uniform(5, 35)), 1),
        })
    sites_df = pd.DataFrame(sites)

    # ---- competitors ----
    categories = ["grocery", "fashion", "electronics", "home-goods",
                  "pharmacy", "general-retail"]
    brand_pool = [fake.company() for _ in range(40)]
    competitors = []
    for i in range(n):
        comp_id = f"C{i+1:03d}"
        ref_idx = int(rng.randint(0, len(sites)))
        ref_lat = sites[ref_idx]["latitude"]
        ref_lon = sites[ref_idx]["longitude"]
        prox = rng.random()
        if prox < 0.40:
            off_lat = float(rng.uniform(-0.008, 0.008))
            off_lon = float(rng.uniform(-0.008, 0.008))
        elif prox < 0.70:
            off_lat = float(rng.uniform(-0.018, 0.018))
            off_lon = float(rng.uniform(-0.018, 0.018))
        else:
            off_lat = float(rng.uniform(-0.05, 0.05))
            off_lon = float(rng.uniform(-0.05, 0.05))
        competitors.append({
            "competitor_id": comp_id,
            "brand_name": str(rng.choice(brand_pool)),
            "category": str(rng.choice(categories)),
            "zone_id": str(rng.choice(zone_ids)),
            "latitude": round(ref_lat + off_lat, 6),
            "longitude": round(ref_lon + off_lon, 6),
            "store_size_sqft": int(rng.randint(800, 14000)),
            "estimated_monthly_revenue": int(rng.randint(12000, 280000)),
        })
    competitors_df = pd.DataFrame(competitors)

    # ---- lease_listings (one per site) ----
    leases = []
    for i, s in enumerate(sites):
        rent = round(float(rng.uniform(2.0, 9.5)), 2)
        leases.append({
            "listing_id": f"L{i+1:03d}",
            "site_id": s["site_id"],
            "monthly_rent_per_sqft": rent,
            "lease_term_months": int(rng.choice([12, 24, 36, 48, 60])),
            "security_deposit_months": int(rng.choice([1, 2, 3])),
            "escalation_rate_pct": round(float(rng.uniform(1.5, 5.5)), 2),
            "available_from": f"2025-{int(rng.randint(1,13)):02d}-{int(rng.randint(1,29)):02d}",
        })
    leases_df = pd.DataFrame(leases)

    # ---- traffic_measurements (weekday + weekend per site) ----
    measurements = []
    mid = 0
    for s in sites:
        ped_base = int(rng.randint(80, 1300))
        veh_base = int(rng.randint(40, 650))
        for day_type in ["weekday", "weekend"]:
            mid += 1
            if day_type == "weekend":
                ped = int(ped_base * float(rng.uniform(0.65, 1.45)))
                veh = int(veh_base * float(rng.uniform(0.75, 1.35)))
            else:
                ped = ped_base
                veh = veh_base
            measurements.append({
                "measurement_id": f"T{mid:04d}",
                "site_id": s["site_id"],
                "day_type": day_type,
                "avg_pedestrian_count": ped,
                "avg_vehicle_count": veh,
            })
    measurements_df = pd.DataFrame(measurements)

    # ---- Write to SQLite ----
    conn = sqlite3.connect(db_path)
    zones_df.to_sql("zone_demographics", conn, index=False, if_exists="replace")
    sites_df.to_sql("candidate_sites", conn, index=False, if_exists="replace")
    competitors_df.to_sql("competitors", conn, index=False, if_exists="replace")
    leases_df.to_sql("lease_listings", conn, index=False, if_exists="replace")
    measurements_df.to_sql("traffic_measurements", conn, index=False, if_exists="replace")
    conn.close()

    return zones, sites, competitors, leases, measurements


# ===================================================================
# Workspace creation
# ===================================================================

def _generate_saturation_indices(zones, rng):
    return {z["zone_id"]: int(rng.randint(18, 83)) for z in zones}


def _generate_peak_multipliers(sites, rng):
    return {s["site_id"]: round(float(rng.uniform(0.08, 0.50)), 2) for s in sites}


def _generate_accessibility_ratings(sites, rng):
    return {s["site_id"]: int(rng.randint(1, 11)) for s in sites}


def create_workspace(db_path, workspace, zones, sites, competitors, leases, measurements):
    rng = np.random.RandomState(42 + 1000)
    Faker.seed(42 + 1000)
    fake = Faker()
    fake.seed_instance(42 + 1000)

    n_files = SCALE["num_workspace_files"]
    os.makedirs(workspace, exist_ok=True)

    saturation = _generate_saturation_indices(zones, rng)
    peak_mult = _generate_peak_multipliers(sites, rng)
    access_rat = _generate_accessibility_ratings(sites, rng)

    # ---- Fixed config files ----
    _write_eligibility_rules(workspace)
    _write_scoring_config(workspace)
    _write_footfall_model(workspace)
    _write_threat_levels(workspace)

    # ---- Scalable data files ----
    n_inspection = max(1, n_files * 3 // 8)
    n_market = max(1, n_files * 3 // 8)
    n_traffic = max(1, n_files - n_inspection - n_market)

    _write_inspection_files(workspace, sites, access_rat, n_inspection, fake, rng)
    _write_market_reports(workspace, zones, saturation, n_market, fake, rng)
    _write_traffic_reports(workspace, sites, peak_mult, n_traffic, rng)


# ---------- Fixed config files ----------

def _write_eligibility_rules(ws):
    rules = {
        "min_zone_population": 15000,
        "min_median_income": 40000,
        "min_site_area_sqft": 2000,
        "max_monthly_rent_per_sqft": 6.50,
        "max_competitors_in_radius": 6,
        "competitor_check_radius_km": 2.0,
    }
    with open(os.path.join(ws, "eligibility_rules.json"), "w") as f:
        json.dump(rules, f, indent=2)


def _write_scoring_config(ws):
    cfg = {
        "weights": {
            "demographic": 0.25,
            "traffic": 0.20,
            "competition": 0.20,
            "lease": 0.15,
            "accessibility": 0.20,
        },
        "demographic_scoring": {
            "population_weight": 0.40,
            "income_weight": 0.35,
            "growth_weight": 0.25,
            "population_scale": 100000,
            "income_scale": 120000,
            "growth_scale": 5.0,
        },
        "traffic_scoring": {
            "pedestrian_weight": 0.70,
            "vehicle_weight": 0.30,
            "divisor": 10.0,
        },
        "competition_scoring": {
            "base_score": 100,
            "penalty_per_threat_point": 15,
            "saturation_divisor": 200,
        },
        "lease_scoring": {
            "max_rent_reference": 8.0,
            "term_bonus_threshold_months": 36,
            "term_bonus_points": 5,
            "score_cap": 100,
        },
        "accessibility_scoring": {
            "default_rating": 5,
            "multiplier": 10,
        },
    }
    with open(os.path.join(ws, "scoring_config.yaml"), "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


def _write_footfall_model(ws):
    rows = [
        ["parameter", "value"],
        ["base_capture_rate", "0.12"],
        ["vehicle_conversion_rate", "0.025"],
        ["competition_adj_low", "1.20"],
        ["competition_adj_medium", "1.00"],
        ["competition_adj_high", "0.75"],
        ["competition_threshold_high", "70"],
        ["competition_threshold_low", "40"],
        ["seasonal_factor", "1.05"],
        ["peak_boost_weight", "0.20"],
        ["default_peak_boost", "0.0"],
        ["operating_days", "363"],
    ]
    path = os.path.join(ws, "footfall_model.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def _write_threat_levels(ws):
    levels = {
        "grocery": 1.5,
        "fashion": 1.0,
        "electronics": 0.8,
        "home-goods": 0.7,
        "pharmacy": 0.5,
        "general-retail": 1.2,
    }
    with open(os.path.join(ws, "category_threat_levels.json"), "w") as f:
        json.dump(levels, f, indent=2)


# ---------- Scalable data files ----------

def _write_inspection_files(ws, sites, ratings, n_files, fake, rng):
    chunks = _split_into_chunks(sites, n_files)
    for idx, chunk in enumerate(chunks, 1):
        lines = []
        inspector = fake.name()
        date_start = fake.date_between(start_date="-6m", end_date="today")
        end_date = date_start + pd.Timedelta(days=int(rng.randint(3, 8)))
        lines.append(f"FIELD INSPECTION REPORT - BATCH {idx:02d}")
        lines.append(f"Inspector: {inspector}")
        lines.append(f"Date Range: {date_start.strftime('%B %d')} - "
                      f"{end_date.strftime('%B %d, %Y')}")
        lines.append("=" * 64)
        lines.append("")
        observations = [
            "The property enjoys good street visibility from the main arterial road.",
            "Located on a secondary street with moderate foot traffic.",
            "Situated at a busy intersection with high pedestrian exposure.",
            "The storefront sits in a quieter residential-commercial transition area.",
            "Corner location providing dual-frontage exposure to two major roads.",
        ]
        sidewalks = [
            "Sidewalks are well-maintained with adequate width for pedestrian flow.",
            "Pavement condition is fair; some uneven sections may deter foot traffic.",
            "Wide, recently resurfaced sidewalks with tactile paving at crossings.",
            "Narrow sidewalks with occasional obstructions from street vendors.",
        ]
        parking_notes = [
            "On-site parking lot observed with moderate turnover during midday visit.",
            "Street parking available but limited during peak hours.",
            "Shared parking structure accessible within a short walk.",
            "No dedicated parking; customers rely on metered street spots.",
        ]
        transit_notes = [
            "Bus stop within a few minutes' walk. No direct metro access.",
            "Metro station exit approximately 300m east of the property.",
            "Multiple bus routes serve the block; nearest stop directly opposite.",
            "Limited public transit options; primarily car-dependent area.",
        ]
        extras = [
            "Adjacent construction expected to complete by Q3 2025.",
            "Neighboring anchor tenant drives consistent foot traffic.",
            "Recent zoning change may attract additional commercial development.",
            "Area scheduled for streetscape improvement project next year.",
            "No notable upcoming changes to the immediate surroundings.",
        ]
        for s in chunk:
            sid = s["site_id"]
            sname = s["site_name"]
            rating = ratings[sid]
            visit_date = fake.date_between(start_date="-6m", end_date="today")
            obs = observations[int(rng.randint(0, len(observations)))]
            sw = sidewalks[int(rng.randint(0, len(sidewalks)))]
            pk = parking_notes[int(rng.randint(0, len(parking_notes)))]
            tr = transit_notes[int(rng.randint(0, len(transit_notes)))]
            ex = extras[int(rng.randint(0, len(extras)))]
            facade = ("shows some wear but is structurally sound"
                      if rng.random() < 0.5
                      else "is in excellent condition")
            dock = "is" if rng.random() < 0.6 else "is not"
            lines.append(f"SITE: {sid} | {sname}")
            lines.append(f"Inspection Date: {visit_date.strftime('%Y-%m-%d')}")
            lines.append("")
            lines.append(
                f"General observations: {obs} The building facade {facade}. "
                f"Loading dock access {dock} available from the rear."
            )
            lines.append("")
            lines.append(f"Pedestrian environment: {sw}")
            lines.append("")
            lines.append(f"Vehicular access: {pk}")
            lines.append("")
            lines.append(f"Public transit: {tr}")
            lines.append("")
            lines.append(f"Accessibility Rating: {rating}")
            lines.append("")
            lines.append(f"Additional notes: {ex}")
            lines.append("")
            lines.append("=" * 64)
            lines.append("")
        path = os.path.join(ws, f"site_inspection_batch_{idx:02d}.txt")
        with open(path, "w") as f:
            f.write("\n".join(lines))


def _write_market_reports(ws, zones, saturation, n_files, fake, rng):
    chunks = _split_into_chunks(zones, n_files)
    if n_files <= 26:
        labels = [chr(ord('A') + i) for i in range(n_files)]
    else:
        labels = [f"{i+1:02d}" for i in range(n_files)]
    narratives = [
        "The retail environment reflects a maturing market with established anchor "
        "tenants and {gap} new entry opportunities.",
        "The area is experiencing {pace} commercial growth. It {status}.",
        "Retail conditions are {tone}, with {vacancy} vacancy rates in prime corridors.",
    ]
    recommendations = [
        "New entrants should focus on underserved categories, particularly fresh food and specialty goods.",
        "Premium segment remains underexplored; opportunity for differentiated retail concepts.",
        "Discount and value-oriented formats may struggle against existing competition.",
        "Mixed-use developments present the strongest opportunity for retail tenants.",
        "High foot traffic near transit hubs offers potential despite competitive pressure.",
    ]
    for idx, chunk in enumerate(chunks):
        label = labels[idx]
        zone_id_list = ", ".join(z["zone_id"] for z in chunk)
        lines = []
        lines.append(f"# Market Analysis Report - Region {label}")
        lines.append("")
        lines.append("Prepared by: Metro Retail Analytics Group")
        lines.append("Period: Q4 2024")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(
            f"This report provides market condition assessments for zones "
            f"{zone_id_list} within the metropolitan study area. Analysis is "
            f"based on field surveys, commercial registry data, and consumer "
            f"spending patterns collected during the reporting period."
        )
        lines.append("")
        lines.append("## Zone Assessments")
        lines.append("")
        for z in chunk:
            zid = z["zone_id"]
            zname = z["zone_name"]
            sat = saturation[zid]
            vacancy = round(float(rng.uniform(3.0, 18.0)), 1)
            active_units = int(rng.randint(8, 65))
            avg_foot = int(rng.randint(15000, 80000))
            new_permits = int(rng.randint(0, 12))
            tmpl = narratives[int(rng.randint(0, len(narratives)))]
            gap = "limited" if sat > 55 else "moderate"
            pace = "rapid" if sat < 35 else "steady"
            status = ("remains underserved in several retail categories"
                      if sat < 40
                      else "has reached a moderate level of retail density")
            tone = ("challenging due to high saturation" if sat > 65
                    else "favorable for new entrants")
            vacancy_word = "declining" if sat > 70 else "stable"
            narrative = tmpl.format(
                gap=gap, pace=pace, status=status,
                tone=tone, vacancy=vacancy_word,
            )
            rec = recommendations[int(rng.randint(0, len(recommendations)))]
            lines.append(f"### {zid} - {zname}")
            lines.append("")
            lines.append(narrative)
            lines.append("")
            lines.append("| Indicator | Value |")
            lines.append("|-----------|-------|")
            lines.append(f"| Active Retail Units | {active_units} |")
            lines.append(f"| Vacancy Rate (%) | {vacancy} |")
            lines.append(f"| Market Saturation Index | {sat} |")
            lines.append(f"| Avg Monthly Foot Traffic | {avg_foot:,} |")
            lines.append(f"| New Permits (Last 12mo) | {new_permits} |")
            lines.append("")
            lines.append(rec)
            lines.append("")
            corridors = [fake.street_name() for _ in range(int(rng.randint(2, 4)))]
            lines.append("Key retail corridors:")
            for c in corridors:
                lines.append(f"- {c}")
            lines.append("")
        path = os.path.join(ws, f"market_analysis_region_{label}.md")
        with open(path, "w") as f:
            f.write("\n".join(lines))


def _write_traffic_reports(ws, sites, peak_mult, n_files, rng):
    chunks = _split_into_chunks(sites, n_files)
    note_pool = [
        "Lunch rush traffic pattern",
        "Morning commute surge",
        "Evening commuter spike",
        "Midday shopping peak",
        "School dismissal period overlap",
        "Weekend leisure traffic concentration",
    ]
    for idx, chunk in enumerate(chunks, 1):
        rows = [["site_id", "site_name", "peak_hour_start", "peak_hour_end",
                 "peak_hour_multiplier", "observation_date", "notes"]]
        for s in chunk:
            sid = s["site_id"]
            sname = s["site_name"]
            pm = peak_mult[sid]
            start_h = int(rng.choice([7, 8, 11, 12, 16, 17]))
            end_h = start_h + 2
            obs_date = f"2024-{int(rng.randint(9,13)):02d}-{int(rng.randint(1,29)):02d}"
            note = note_pool[int(rng.randint(0, len(note_pool)))]
            rows.append([sid, sname, f"{start_h:02d}:00", f"{end_h:02d}:00",
                          str(pm), obs_date, note])
        path = os.path.join(ws, f"traffic_report_sector_{idx:02d}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)


def _split_into_chunks(items, n_chunks):
    k, m = divmod(len(items), n_chunks)
    chunks, start = [], 0
    for i in range(n_chunks):
        end = start + k + (1 if i < m else 0)
        chunks.append(items[start:end])
        start = end
    return chunks


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    zones, sites, competitors, leases, measurements = create_database(args.db_path)
    create_workspace(args.db_path, args.workspace,
                     zones, sites, competitors, leases, measurements)


if __name__ == "__main__":
    main()
