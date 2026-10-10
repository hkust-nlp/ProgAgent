#!/usr/bin/env python3
"""Data generation for UX conversion bottleneck analysis task."""
import numpy as np
import pandas as pd
from faker import Faker
import sqlite3
import os
import json
import yaml
import csv
import argparse
import random
from datetime import datetime, timedelta

SCALE = {
    "rows_per_table": 320,
    "num_workspace_files": 30,
}

# ── Fix all seeds ──────────────────────────────────────────────
np.random.seed(42)
random.seed(42)
fake = Faker()
Faker.seed(42)

# ── Constants (not scaled) ─────────────────────────────────────
PAGES = [
    "homepage", "search_results", "product_listing", "product_detail",
    "size_guide", "reviews", "cart", "checkout_shipping",
    "checkout_payment", "order_confirmation", "account_settings", "help_center",
]

FUNNEL_STEPS_DEF = [
    (1, "landing", "homepage", 0.92),
    (2, "browse", "search_results", 0.78),
    (3, "product_view", "product_detail", 0.65),
    (4, "add_to_cart", "cart", 0.52),
    (5, "checkout", "checkout_payment", 0.40),
    (6, "purchase", "order_confirmation", 0.35),
]

AB_TESTS_DEF = [
    ("checkout_flow_v2", "checkout_payment",
     "Simplified checkout with fewer form fields"),
    ("search_ranking_update", "search_results",
     "ML-based search ranking algorithm"),
    ("product_page_layout", "product_detail",
     "New product image gallery and layout"),
]

ERROR_TYPES = ["js_error", "api_timeout", "render_fail",
               "validation_error", "network_error"]
SEVERITIES = ["critical", "high", "medium", "low"]
SEVERITY_PROBS = [0.10, 0.25, 0.40, 0.25]
DEVICES = ["mobile", "desktop", "tablet"]
DEVICE_PROBS = [0.50, 0.35, 0.15]
BROWSERS = ["chrome", "firefox", "safari", "edge"]
SEGMENTS = ["new", "returning", "vip"]

ERROR_PAGE_PROBS = np.array([
    0.05, 0.14, 0.06, 0.11, 0.03, 0.05,
    0.10, 0.09, 0.22, 0.04, 0.06, 0.05,
])
ERROR_PAGE_PROBS = ERROR_PAGE_PROBS / ERROR_PAGE_PROBS.sum()

RAGE_PAGE_PROBS = np.array([
    0.05, 0.17, 0.07, 0.10, 0.03, 0.04,
    0.12, 0.08, 0.20, 0.03, 0.05, 0.06,
])
RAGE_PAGE_PROBS = RAGE_PAGE_PROBS / RAGE_PAGE_PROBS.sum()

ISSUE_PAGE_PROBS = np.array([
    0.04, 0.15, 0.05, 0.10, 0.02, 0.04,
    0.11, 0.08, 0.25, 0.03, 0.07, 0.06,
])
ISSUE_PAGE_PROBS = ISSUE_PAGE_PROBS / ISSUE_PAGE_PROBS.sum()

HEATMAP_ZONES = [
    # (page, zone_name, x_min, x_max, y_min, y_max, zone_type)
    ("homepage", "main_cta", 350, 850, 250, 350, "critical"),
    ("homepage", "nav_bar", 0, 1200, 0, 60, "important"),
    ("homepage", "hero_section", 100, 1100, 70, 240, "standard"),
    ("homepage", "footer", 0, 1200, 700, 800, "standard"),
    ("search_results", "search_input", 200, 1000, 10, 60, "critical"),
    ("search_results", "filter_panel", 0, 250, 70, 650, "important"),
    ("search_results", "result_items", 260, 1150, 70, 650, "standard"),
    ("search_results", "sort_dropdown", 900, 1150, 60, 100, "important"),
    ("product_listing", "product_cards", 100, 1100, 100, 650, "important"),
    ("product_listing", "category_nav", 0, 200, 60, 650, "standard"),
    ("product_listing", "load_more_btn", 400, 800, 660, 700, "critical"),
    ("product_detail", "add_to_cart_btn", 600, 900, 300, 360, "critical"),
    ("product_detail", "image_gallery", 50, 550, 80, 450, "important"),
    ("product_detail", "specs_section", 50, 1150, 500, 700, "standard"),
    ("product_detail", "price_display", 600, 900, 200, 260, "important"),
    ("size_guide", "size_chart", 100, 1100, 100, 550, "important"),
    ("size_guide", "unit_toggle", 900, 1100, 60, 100, "critical"),
    ("reviews", "write_review_btn", 800, 1100, 60, 100, "critical"),
    ("reviews", "review_list", 100, 1100, 110, 650, "standard"),
    ("reviews", "rating_filter", 100, 400, 60, 100, "important"),
    ("cart", "checkout_btn", 800, 1100, 600, 660, "critical"),
    ("cart", "quantity_selector", 400, 550, 150, 500, "important"),
    ("cart", "remove_item", 1050, 1150, 150, 500, "important"),
    ("cart", "promo_code_input", 100, 400, 600, 660, "standard"),
    ("checkout_shipping", "address_form", 100, 700, 100, 450, "critical"),
    ("checkout_shipping", "shipping_options", 100, 700, 460, 600, "important"),
    ("checkout_shipping", "continue_btn", 500, 700, 620, 680, "critical"),
    ("checkout_payment", "payment_form", 100, 700, 100, 300, "critical"),
    ("checkout_payment", "place_order_btn", 500, 700, 520, 580, "critical"),
    ("checkout_payment", "card_input", 100, 700, 100, 200, "critical"),
    ("checkout_payment", "billing_address", 100, 700, 310, 450, "important"),
    ("order_confirmation", "order_summary", 100, 800, 100, 400, "standard"),
    ("order_confirmation", "continue_shopping", 400, 700, 450, 510, "important"),
    ("account_settings", "save_btn", 400, 700, 580, 640, "critical"),
    ("account_settings", "profile_form", 100, 700, 100, 400, "important"),
    ("account_settings", "password_section", 100, 700, 410, 570, "important"),
    ("help_center", "search_help", 200, 1000, 60, 110, "critical"),
    ("help_center", "faq_list", 100, 1100, 120, 650, "standard"),
    ("help_center", "contact_btn", 900, 1100, 660, 720, "important"),
]

ERROR_MESSAGES = {
    "js_error": [
        "Uncaught TypeError: Cannot read property of undefined",
        "Uncaught ReferenceError: variable is not defined",
        "Script error in event handler",
        "Maximum call stack size exceeded",
    ],
    "api_timeout": [
        "Request timeout after 30000ms",
        "Gateway timeout 504",
        "Connection refused by upstream",
        "Service temporarily unavailable 503",
    ],
    "render_fail": [
        "Component failed to mount",
        "Hydration mismatch detected",
        "Layout shift threshold exceeded",
        "Image lazy-load failure",
    ],
    "validation_error": [
        "Invalid email format",
        "Required field missing",
        "Card number validation failed",
        "Postal code format invalid",
    ],
    "network_error": [
        "Failed to fetch resource",
        "DNS lookup failed",
        "SSL handshake timeout",
        "Mixed content blocked",
    ],
}

ISSUE_DESCRIPTIONS = {
    "homepage": ["Hero banner CTA unresponsive on first click",
                 "Navigation menu overlap on mobile"],
    "search_results": ["Search results flicker during loading",
                       "Filter selections reset unexpectedly",
                       "Sort dropdown unresponsive"],
    "product_listing": ["Product cards overlap on narrow screens",
                        "Load more button requires multiple clicks"],
    "product_detail": ["Add to cart button hidden below fold on mobile",
                       "Image gallery swipe conflicts with scroll"],
    "size_guide": ["Unit toggle does not update chart",
                   "Size chart renders incorrectly on tablet"],
    "reviews": ["Write review button unclickable on Safari",
                "Rating filter resets on page scroll"],
    "cart": ["Quantity selector difficult to tap on mobile",
             "Checkout button unresponsive during price update"],
    "checkout_shipping": ["Address autocomplete fails silently",
                          "Continue button hidden by keyboard on mobile"],
    "checkout_payment": ["Card input loses focus between fields",
                         "Place order button double-submits",
                         "Payment form validation fires prematurely",
                         "Billing address toggle breaks layout"],
    "order_confirmation": ["Order summary slow to render",
                           "Continue shopping link not visible"],
    "account_settings": ["Save button disabled without visual feedback",
                         "Password change form clears on error"],
    "help_center": ["Help search returns no results for common queries",
                    "Contact button hidden on mobile viewport"],
}


# ── Helpers ────────────────────────────────────────────────────
def _zones_for_page(page):
    return [z for z in HEATMAP_ZONES if z[0] == page]


# ── Generators ─────────────────────────────────────────────────
def generate_users(n):
    rows = []
    base_date = datetime(2024, 1, 1)
    for i in range(n):
        rows.append({
            "user_id": i + 1,
            "username": fake.user_name() + str(i),
            "email": fake.email(),
            "segment": np.random.choice(SEGMENTS, p=[0.45, 0.40, 0.15]),
            "signup_date": (base_date + timedelta(
                days=int(np.random.randint(0, 365))
            )).strftime("%Y-%m-%d"),
        })
    return pd.DataFrame(rows)


def generate_sessions(n, user_ids):
    rows = []
    base_time = datetime(2025, 1, 1, 8, 0, 0)
    for i in range(n):
        uid = int(np.random.choice(user_ids))
        start = base_time + timedelta(
            hours=int(np.random.randint(0, 720)),
            minutes=int(np.random.randint(0, 60)),
        )
        rows.append({
            "session_id": i + 1,
            "user_id": uid,
            "device": np.random.choice(DEVICES, p=DEVICE_PROBS),
            "browser": np.random.choice(BROWSERS),
            "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": int(np.random.randint(30, 1800)),
            "landing_page": np.random.choice(PAGES[:4]),
        })
    return pd.DataFrame(rows)


def generate_ab_assignments(user_ids):
    rows = []
    aid = 1
    for uid in user_ids:
        for test_name, _, _ in AB_TESTS_DEF:
            rows.append({
                "assignment_id": aid,
                "user_id": int(uid),
                "test_name": test_name,
                "variant": np.random.choice(["A", "B"]),
            })
            aid += 1
    return pd.DataFrame(rows)


def generate_error_logs(n, session_ids):
    rows = []
    base_time = datetime(2025, 1, 1, 8, 0, 0)
    for i in range(n):
        page = np.random.choice(PAGES, p=ERROR_PAGE_PROBS)
        etype = np.random.choice(ERROR_TYPES)
        rows.append({
            "error_id": i + 1,
            "session_id": int(np.random.choice(session_ids)),
            "page": page,
            "error_type": etype,
            "severity": np.random.choice(SEVERITIES, p=SEVERITY_PROBS),
            "message": np.random.choice(ERROR_MESSAGES[etype]),
            "timestamp": (base_time + timedelta(
                hours=int(np.random.randint(0, 720)),
                minutes=int(np.random.randint(0, 60)),
                seconds=int(np.random.randint(0, 60)),
            )).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return pd.DataFrame(rows)


def generate_rage_clicks(n, session_ids):
    rows = []
    base_time = datetime(2025, 1, 1, 8, 0, 0)
    for i in range(n):
        page = np.random.choice(PAGES, p=RAGE_PAGE_PROBS)
        zones = _zones_for_page(page)
        if zones:
            wts = np.array([
                3.0 if z[6] == "critical" else 2.0 if z[6] == "important" else 1.0
                for z in zones
            ])
            wts /= wts.sum()
            zone = zones[int(np.random.choice(len(zones), p=wts))]
            x = int(np.random.randint(zone[2], max(zone[3], zone[2] + 1)))
            y = int(np.random.randint(zone[4], max(zone[5], zone[4] + 1)))
            element = zone[1]
        else:
            x = int(np.random.randint(0, 1200))
            y = int(np.random.randint(0, 800))
            element = "unknown"
        rows.append({
            "click_id": i + 1,
            "session_id": int(np.random.choice(session_ids)),
            "page": page,
            "element": element,
            "x_coord": x,
            "y_coord": y,
            "click_count": int(np.random.randint(3, 15)),
            "timestamp": (base_time + timedelta(
                hours=int(np.random.randint(0, 720)),
                minutes=int(np.random.randint(0, 60)),
            )).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return pd.DataFrame(rows)


def generate_funnel_events(n, session_ids):
    step_completion = [0.85, 0.72, 0.68, 0.60, 0.55, 0.80]
    events = []
    eid = 1
    base_time = datetime(2025, 1, 1, 8, 0, 0)

    sids = list(session_ids)
    np.random.shuffle(sids)
    sid_idx = 0

    while len(events) < n:
        if sid_idx < len(sids):
            sid = int(sids[sid_idx])
            sid_idx += 1
        else:
            sid = int(np.random.choice(session_ids))

        session_time = base_time + timedelta(hours=int(np.random.randint(0, 720)))
        active = True
        for step_idx, (order, step_name, page, _target) in enumerate(FUNNEL_STEPS_DEF):
            if not active:
                break
            completed = 1 if np.random.random() < step_completion[step_idx] else 0
            events.append({
                "event_id": eid,
                "session_id": sid,
                "step_name": step_name,
                "page": page,
                "entered": 1,
                "completed": completed,
                "duration_sec": int(np.random.randint(5, 300)),
                "timestamp": (session_time + timedelta(
                    minutes=step_idx * 3
                )).strftime("%Y-%m-%d %H:%M:%S"),
            })
            eid += 1
            if not completed:
                active = False

    return pd.DataFrame(events)  # >= n rows


# ── Workspace generation ───────────────────────────────────────
def generate_workspace(workspace, db_path):
    os.makedirs(workspace, exist_ok=True)
    conn = sqlite3.connect(db_path)

    # ---- Fixed config files (not counted in SCALE) ----

    # 1. priority_config.yaml
    config = {
        "weights": {
            "error_score": 0.30,
            "rage_click_score": 0.25,
            "abandonment_rate": 0.20,
            "ab_impact": 0.15,
            "confirmed_issues": 0.10,
        },
        "normalization": {
            "error_score_cap": 200,
            "rage_click_score_cap": 150,
            "confirmed_issue_cap": 50,
        },
        "confirmed_issue_bonus": 5.0,
        "zone_weights": {
            "critical": 3.0,
            "important": 1.5,
            "standard": 1.0,
        },
    }
    with open(os.path.join(workspace, "priority_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # 2. severity_weights.json
    with open(os.path.join(workspace, "severity_weights.json"), "w") as f:
        json.dump({"critical": 10, "high": 7, "medium": 4, "low": 1}, f, indent=2)

    # 3. funnel_definition.csv
    with open(os.path.join(workspace, "funnel_definition.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["step_order", "step_name", "page", "target_conversion_rate"])
        for order, name, page, target in FUNNEL_STEPS_DEF:
            w.writerow([order, name, page, target])

    # 4. ab_test_hypotheses.yaml
    ab_cfg = {"tests": {}}
    for name, target, desc in AB_TESTS_DEF:
        ab_cfg["tests"][name] = {
            "description": desc,
            "target_page": target,
            "control_variant": "A",
            "treatment_variant": "B",
        }
    with open(os.path.join(workspace, "ab_test_hypotheses.yaml"), "w") as f:
        yaml.dump(ab_cfg, f, default_flow_style=False, sort_keys=False)

    # 5. heatmap_zones.csv
    with open(os.path.join(workspace, "heatmap_zones.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["page", "zone_name", "x_min", "x_max", "y_min", "y_max", "zone_type"])
        for z in HEATMAP_ZONES:
            w.writerow(z)

    # 6. scoring_methodology.md
    methodology = """\
# Priority Scoring Methodology

Each page receives a composite priority score on a 0-to-100 scale.
The score is built from five weighted components whose weights are
defined in priority_config.yaml.

## Error Score
For each page, sum the product of each individual error event's
severity weight (from severity_weights.json) across all error log
entries recorded on that page. Normalise by dividing by the
error_score_cap value from priority_config.yaml and cap at 1.0.

## Rage Click Score
For each rage-click event on a page, determine which heatmap zone
the click coordinates (x_coord, y_coord) fall within using the
bounding boxes in heatmap_zones.csv (a coordinate matches a zone
when x_min <= x_coord <= x_max AND y_min <= y_coord <= y_max; use
the first matching zone). Multiply the event's click_count by the
zone_weight for that zone's type (from priority_config.yaml
zone_weights). If a click does not fall within any defined zone,
use a zone_weight of 1.0. Sum across all rage-click events on the
page. Normalise by dividing by rage_click_score_cap and cap at 1.0.

## Abandonment Rate
For pages that correspond to a funnel step (see funnel_definition.csv),
compute abandonment_rate = 1 - (total_completed / total_entered) from
funnel event data. Pages that are not funnel steps have
abandonment_rate = 0.

## A/B Impact
For pages targeted by an A/B test (see ab_test_hypotheses.yaml),
compute the problem rate for each variant as
  (error_count + rage_click_count) / session_count
on that specific page. session_count is the number of sessions whose
user was assigned to that variant for the relevant test, error_count
is errors on the target page from those sessions, and rage_click_count
is rage-click events on the target page from those sessions. The
ab_impact is abs(problem_rate_A - problem_rate_B), capped at 1.0.
Pages not targeted by any A/B test have ab_impact = 0.

## Confirmed Issues
Count confirmed UX issues for each page from the session replay
annotation files. Multiply by confirmed_issue_bonus, divide by
confirmed_issue_cap (both from priority_config.yaml), and cap at 1.0.

## Final Formula
priority_score = (
    w_error * norm_error +
    w_rage * norm_rage +
    w_abandon * abandonment_rate +
    w_ab * norm_ab_impact +
    w_confirmed * norm_confirmed
) * 100

Where each w_* is the corresponding weight from priority_config.yaml.
"""
    with open(os.path.join(workspace, "scoring_methodology.md"), "w") as f:
        f.write(methodology)

    # ---- Scalable data files: session replay annotation batches ----
    num_files = SCALE["num_workspace_files"]
    sessions_df = pd.read_sql("SELECT session_id FROM sessions", conn)
    all_sids = sessions_df["session_id"].tolist()

    # Deterministic shuffle with a fresh RNG
    rng_replay = np.random.RandomState(42)
    shuffled = list(all_sids)
    rng_replay.shuffle(shuffled)

    batch_size = max(len(shuffled) // num_files, 1)
    replay_base = datetime(2025, 2, 1)

    for batch_idx in range(num_files):
        start = batch_idx * batch_size
        end = start + batch_size if batch_idx < num_files - 1 else len(shuffled)
        batch_sids = shuffled[start:end]

        annotations = []
        for sid in batch_sids:
            if np.random.random() < 0.30:
                issue_page = np.random.choice(PAGES, p=ISSUE_PAGE_PROBS)
                extra = list(np.random.choice(
                    PAGES, size=int(np.random.randint(1, 4)), replace=False))
                reviewed = sorted(set([issue_page] + extra))
                descs = ISSUE_DESCRIPTIONS.get(issue_page,
                                               ["Generic UX issue observed"])
                annotations.append({
                    "session_id": int(sid),
                    "pages_reviewed": reviewed,
                    "issues_found": [{
                        "page": issue_page,
                        "confirmed_ux_issue": True,
                        "description": str(np.random.choice(descs)),
                    }],
                })
            else:
                reviewed = sorted(list(np.random.choice(
                    PAGES, size=int(np.random.randint(1, 3)), replace=False)))
                annotations.append({
                    "session_id": int(sid),
                    "pages_reviewed": reviewed,
                    "issues_found": [],
                })

        batch_data = {
            "batch_id": batch_idx + 1,
            "replay_date": (replay_base + timedelta(days=batch_idx)).strftime("%Y-%m-%d"),
            "annotations": annotations,
        }
        fname = f"session_replay_batch_{batch_idx + 1:03d}.json"
        with open(os.path.join(workspace, fname), "w") as f:
            json.dump(batch_data, f, indent=2)

    conn.close()


# ── Main ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db_path", required=True)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    n = SCALE["rows_per_table"]

    users_df = generate_users(n)
    sessions_df = generate_sessions(n, users_df["user_id"].tolist())
    ab_df = generate_ab_assignments(users_df["user_id"].tolist())
    errors_df = generate_error_logs(n, sessions_df["session_id"].tolist())
    rage_df = generate_rage_clicks(n, sessions_df["session_id"].tolist())
    funnel_df = generate_funnel_events(n, sessions_df["session_id"].tolist())

    # Write to DB
    if os.path.exists(args.db_path):
        os.remove(args.db_path)
    conn = sqlite3.connect(args.db_path)

    users_df.to_sql("users", conn, index=False)
    sessions_df.to_sql("sessions", conn, index=False)
    ab_df.to_sql("ab_assignments", conn, index=False)
    errors_df.to_sql("error_logs", conn, index=False)
    rage_df.to_sql("rage_clicks", conn, index=False)
    funnel_df.to_sql("funnel_events", conn, index=False)

    conn.commit()
    conn.close()

    generate_workspace(args.workspace, args.db_path)
    print(f"Database: {args.db_path}")
    print(f"  users:          {len(users_df)} rows")
    print(f"  sessions:       {len(sessions_df)} rows")
    print(f"  ab_assignments: {len(ab_df)} rows")
    print(f"  error_logs:     {len(errors_df)} rows")
    print(f"  rage_clicks:    {len(rage_df)} rows")
    print(f"  funnel_events:  {len(funnel_df)} rows")
    print(f"Workspace: {args.workspace}  ({SCALE['num_workspace_files']} replay files + 6 config files)")


if __name__ == "__main__":
    main()
