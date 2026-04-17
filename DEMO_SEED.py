#!/usr/bin/env python3
"""
Verdigris — Demo Knowledge Base Seeder
=======================================
Runs 32 pre-selected reports across all report types to build
a demo-quality Obsidian vault for showcasing Verdigris.

Designed for three demo narratives:
  1. The Field Rep     — ZIP-level prospecting, payback analysis
  2. The Market Manager — State ranking, demand forecasting
  3. International     — Cross-country solar comparison

Features:
  - Progress tracking with tqdm
  - Resume from interruption (skips completed reports)
  - Error recovery (logs failures, continues to next)
  - Completion summary with vault stats

Usage:
  python3 DEMO_SEED.py              # run all
  python3 DEMO_SEED.py --dry-run    # preview without running
  python3 DEMO_SEED.py --reset      # clear progress and re-run all

Requirements:
  - .env configured with all API keys
  - pip install -r requirements.txt
  - Warehouse seeded: python3 data/seed_warehouse.py
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

PROGRESS_FILE = PROJECT_ROOT / ".demo_seed_progress.json"

# ── Demo report manifest ──────────────────────────────────────────────────────

DEMO_REPORTS = [
    # ── Narrative 1: Field rep workflow ──────────────────────────────────────
    # High-rate states — strongest ROI story for reps
    ("California",      "solar_viability",   "High rate + strong sun — top rep market"),
    ("California",      "rate_roi",          "ROI analysis for strongest U.S. market"),
    ("California",      "demand_forecast",   "Demand trend for largest U.S. state"),
    ("California",      "executive_summary", "One-pager for CA decision makers"),

    ("Hawaii",          "solar_viability",   "Highest rates in U.S. — exceptional ROI"),
    ("Hawaii",          "rate_roi",          "Hawaii ROI — strongest payback nationally"),
    ("Hawaii",          "executive_summary", "Hawaii pitch deck one-pager"),

    ("Massachusetts",   "solar_viability",   "High rate Northeast market"),
    ("Massachusetts",   "rate_roi",          "MA rate environment — above national avg"),

    ("Connecticut",     "solar_viability",   "High rate, dense Northeast market"),
    ("New York",        "solar_viability",   "Large dense market, high rates"),

    # ── Narrative 2: Market manager planning ─────────────────────────────────
    # Sun Belt — strong resource, moderate rates
    ("Arizona",         "solar_viability",   "Exceptional irradiance, growing market"),
    ("Arizona",         "demand_forecast",   "Fast-growing demand — urgency for solar"),
    ("Arizona",         "executive_summary", "AZ market brief for VP presentation"),

    ("Nevada",          "solar_viability",   "Strong sun, deregulated market"),
    ("New Mexico",      "solar_viability",   "High irradiance, emerging market"),

    ("Texas",           "solar_viability",   "Largest U.S. solar installer market"),
    ("Texas",           "demand_forecast",   "Texas demand — fastest growing in U.S."),
    ("Texas",           "rate_roi",          "TX rate environment — competitive market"),

    ("North Carolina",  "solar_viability",   "Emerging Southeast market"),
    ("Colorado",        "solar_viability",   "High altitude — strong irradiance"),
    ("Colorado",        "demand_forecast",   "CO demand growth — tech sector driver"),

    # ZIP-level prospecting — rep workflow demo
    ("90210",           "solar_viability",   "Beverly Hills CA — premium residential"),
    ("10001",           "solar_viability",   "Manhattan NY — dense urban market"),
    ("02108",           "solar_viability",   "Boston MA — high rate market"),
    ("89101",           "solar_viability",   "Las Vegas NV — exceptional sun"),

    # ── Narrative 3: International expansion ─────────────────────────────────
    # Europe — high rates via Eurostat (live data)
    ("Germany",         "solar_viability",   "World's most policy-mature solar market"),
    ("United Kingdom",  "solar_viability",   "High Ofgem rates — strong ROI case"),

    # Asia-Pacific
    ("Australia",       "solar_viability",   "Highest irradiance + high rates"),
    ("Japan",           "solar_viability",   "High rates, dense market, policy support"),

    # Emerging markets
    ("India",           "solar_viability",   "1.4B population, fast solar adoption"),
    ("Saudi Arabia",    "solar_viability",   "Exceptional sun, very low rates — contrast"),
]

REPORT_TYPE_LABELS = {
    "solar_viability":   "Solar Viability",
    "rate_roi":          "Rate & ROI",
    "demand_forecast":   "Demand Forecast",
    "executive_summary": "Executive Summary",
    "market_comparison": "Market Comparison",
}


# ── Progress tracking ─────────────────────────────────────────────────────────

def load_progress() -> dict:
    """Loads completed report tracking from disk."""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {"completed": [], "failed": [], "started_at": None}


def save_progress(progress: dict) -> None:
    """Saves progress to disk for resume support."""
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def report_key(location: str, report_type: str) -> str:
    return f"{location.lower().replace(' ', '_')}_{report_type}"


# ── Runner ────────────────────────────────────────────────────────────────────

def run_report(location: str, report_type: str) -> dict:
    """Runs a single report through the full pipeline."""
    from agent.analyst import run
    from agent.report import write

    findings = run(location, report_type)
    if "error" in findings:
        return {"success": False, "error": findings["error"]}

    report_md = write(findings, report_type)
    headline = findings.get("headline", "No headline")

    return {
        "success": True,
        "headline": headline,
        "word_count": len(report_md.split()),
    }


def print_header():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║           Verdigris — Demo Knowledge Base Seeder            ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("  Building a demo vault with 32 reports across 3 narratives:")
    print("  • Narrative 1: Field rep workflow (ZIP codes + payback)")
    print("  • Narrative 2: Market manager planning (state ranking)")
    print("  • Narrative 3: International expansion (EU + APAC)")
    print()
    print(f"  Reports to run: {len(DEMO_REPORTS)}")
    print(f"  Estimated time: {len(DEMO_REPORTS) * 2}–{len(DEMO_REPORTS) * 3} minutes")
    print()


def print_dry_run():
    print_header()
    print("  DRY RUN — no reports will be generated\n")
    print(f"  {'#':<4} {'Location':<22} {'Report Type':<20} {'Notes'}")
    print(f"  {'─'*4} {'─'*22} {'─'*20} {'─'*35}")
    for i, (location, report_type, notes) in enumerate(DEMO_REPORTS, 1):
        label = REPORT_TYPE_LABELS.get(report_type, report_type)
        print(f"  {i:<4} {location:<22} {label:<20} {notes}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Seed Verdigris demo knowledge base with 32 reports"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview report list without running"
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear progress and re-run all reports"
    )
    parser.add_argument(
        "--narrative", type=int, choices=[1, 2, 3],
        help="Run only one narrative (1=rep, 2=manager, 3=international)"
    )
    args = parser.parse_args()

    if args.dry_run:
        print_dry_run()
        return

    print_header()

    # Check prerequisites
    print("  Checking prerequisites...")
    try:
        from data.warehouse import is_seeded
        if not is_seeded():
            print("  ✗ Warehouse not seeded. Run: python3 data/seed_warehouse.py")
            sys.exit(1)
        print("  ✓ Warehouse seeded")
    except Exception as e:
        print(f"  ✗ Warehouse check failed: {e}")
        sys.exit(1)

    try:
        import os
        keys = {
            "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY"),
            "EIA_API_KEY": os.getenv("EIA_API_KEY"),
            "NREL_API_KEY": os.getenv("NREL_API_KEY"),
            "CENSUS_API_KEY": os.getenv("CENSUS_API_KEY"),
        }
        missing = [k for k, v in keys.items() if not v]
        if missing:
            print(f"  ✗ Missing API keys: {', '.join(missing)}")
            sys.exit(1)
        print(f"  ✓ All {len(keys)} API keys present")
    except Exception as e:
        print(f"  ✗ API key check failed: {e}")
        sys.exit(1)

    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    if vault_path:
        print(f"  ✓ Obsidian vault: {vault_path}")
    else:
        print("  ⚠ OBSIDIAN_VAULT_PATH not set — reports won't save to vault")

    print()

    # Load or reset progress
    if args.reset and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        print("  Progress reset — running all reports from scratch\n")

    progress = load_progress()
    if not progress["started_at"]:
        progress["started_at"] = datetime.now().isoformat()

    # Filter by narrative if requested
    reports_to_run = DEMO_REPORTS
    if args.narrative == 1:
        reports_to_run = DEMO_REPORTS[:16]  # Rep workflow
        print("  Running Narrative 1 only: Field rep workflow\n")
    elif args.narrative == 2:
        reports_to_run = DEMO_REPORTS[11:26]  # Manager planning
        print("  Running Narrative 2 only: Market manager planning\n")
    elif args.narrative == 3:
        reports_to_run = DEMO_REPORTS[26:]  # International
        print("  Running Narrative 3 only: International expansion\n")

    # Count skippable
    already_done = [
        r for r in reports_to_run
        if report_key(r[0], r[1]) in progress["completed"]
    ]
    to_run = [
        r for r in reports_to_run
        if report_key(r[0], r[1]) not in progress["completed"]
    ]

    if already_done:
        print(f"  Resuming — {len(already_done)} already complete, "
              f"{len(to_run)} remaining\n")

    if not to_run:
        print("  All reports already complete. Use --reset to re-run.\n")
        _print_summary(progress, reports_to_run)
        return

    # Install tqdm if needed
    try:
        from tqdm import tqdm
    except ImportError:
        print("  Installing tqdm...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "tqdm", "-q"])
        from tqdm import tqdm

    # Run reports
    print(f"  Running {len(to_run)} reports...\n")

    with tqdm(
        total=len(to_run),
        desc="  Progress",
        unit="report",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
    ) as pbar:
        for location, report_type, notes in to_run:
            key = report_key(location, report_type)
            label = REPORT_TYPE_LABELS.get(report_type, report_type)
            pbar.set_description(f"  {location} — {label}")

            try:
                result = run_report(location, report_type)

                if result["success"]:
                    progress["completed"].append(key)
                    tqdm.write(
                        f"  ✓ {location} {label} "
                        f"({result['word_count']} words)"
                    )
                else:
                    progress["failed"].append({
                        "key": key,
                        "error": result["error"],
                        "time": datetime.now().isoformat(),
                    })
                    tqdm.write(
                        f"  ✗ {location} {label}: {result['error'][:60]}"
                    )

            except Exception as e:
                progress["failed"].append({
                    "key": key,
                    "error": str(e),
                    "time": datetime.now().isoformat(),
                })
                tqdm.write(f"  ✗ {location} {label}: {str(e)[:60]}")

            save_progress(progress)
            pbar.update(1)

            # Polite pause between reports
            time.sleep(1.0)

    print()
    _print_summary(progress, reports_to_run)


def _print_summary(progress: dict, reports: list):
    completed = set(progress.get("completed", []))
    failed = progress.get("failed", [])
    total = len(reports)
    n_done = sum(1 for r in reports if report_key(r[0], r[1]) in completed)
    n_failed = len(failed)

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                    Seed Complete                             ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"  ✓ Completed:  {n_done}/{total} reports")
    if n_failed:
        print(f"  ✗ Failed:     {n_failed} reports")
        for f in failed[-5:]:  # show last 5 failures
            print(f"    • {f['key']}: {f['error'][:50]}")
    print()
    print("  Demo vault is ready. Try these questions in the chat:")
    print()
    print("  Narrative 1 — Field rep:")
    print("    'What is the payback period for California?'")
    print("    'What is the solar situation for 90210?'")
    print("    'Which markets have rates above 25 cents per kWh?'")
    print()
    print("  Narrative 2 — Market manager:")
    print("    'Rank all markets we have analyzed'")
    print("    'Where is demand growing fastest?'")
    print("    'Give me an executive summary of Arizona'")
    print()
    print("  Narrative 3 — International:")
    print("    'How does Germany compare to California?'")
    print("    'What is the ROI situation for Australia?'")
    print("    'Which countries have the strongest rate economics?'")
    print()
    if PROGRESS_FILE.exists():
        print(f"  Progress saved to: {PROGRESS_FILE.name}")
        print("  Run with --reset to start fresh.")
    print()


if __name__ == "__main__":
    main()