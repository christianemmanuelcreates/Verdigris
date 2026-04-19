#!/usr/bin/env python3
"""
Verdigris Test Suite
Run before every GitHub push to catch regressions.

Usage:
    python3 test_suite.py
    python3 test_suite.py --fast    # skip slow API tests
"""

import sys
import os
import traceback
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TEAL  = "\033[38;2;78;205;196m"
GOLD  = "\033[38;2;201;169;110m"
GREEN = "\033[38;2;123;198;122m"
RED   = "\033[38;2;232;99;99m"
DIM   = "\033[38;2;45;90;90m"
RESET = "\033[0m"

FAST_MODE = "--fast" in sys.argv
passed = []
failed = []
skipped = []

def t(text, color=TEAL):
    return f"{color}{text}{RESET}"

def run_test(name, fn, slow=False):
    if slow and FAST_MODE:
        skipped.append(name)
        print(f"  {t('·', DIM)}  {t(name, DIM)} {t('skipped (--fast)', DIM)}")
        return
    try:
        fn()
        passed.append(name)
        print(f"  {t('✓', GREEN)}  {t(name, GREEN)}")
    except Exception as e:
        failed.append(name)
        print(f"  {t('✗', RED)}  {t(name, RED)}")
        print(f"       {t(str(e)[:120], DIM)}")

def section(title):
    print(f"\n{t(title, GOLD)}")
    print(t("─" * 50, DIM))

# ── SECTION 1 — Environment ───────────────────────────────
section("1. Environment")

def test_env_file():
    assert Path(".env").exists(), ".env file not found"

def test_vault_path():
    path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    assert path, "OBSIDIAN_VAULT_PATH not set"
    assert Path(path).exists(), f"Vault path does not exist: {path}"

def test_vault_reports():
    path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    reports = list(Path(path, "Reports").glob("*.md"))
    assert len(reports) > 0, "No reports in vault"

def test_openrouter_key():
    key = os.getenv("OPENROUTER_API_KEY", "")
    assert key, "OPENROUTER_API_KEY not set"

def test_eia_key():
    key = os.getenv("EIA_API_KEY", "")
    assert key, "EIA_API_KEY not set — U.S. rates unavailable"

run_test("env file exists", test_env_file)
run_test("vault path configured", test_vault_path)
run_test("vault has reports", test_vault_reports)
run_test("OpenRouter key set", test_openrouter_key)
run_test("EIA key set", test_eia_key)

# ── SECTION 2 — Data Layer ────────────────────────────────
section("2. Data Layer")

def test_warehouse_exists():
    assert Path("verdigris_warehouse.db").exists(), \
        "Warehouse not found — run data/seed_warehouse.py"

def test_warehouse_eia_rates():
    import sqlite3
    conn = sqlite3.connect("verdigris_warehouse.db")
    rows = conn.execute(
        "SELECT COUNT(*) FROM eia_rates"
    ).fetchone()[0]
    conn.close()
    assert rows > 1000, f"Only {rows} EIA rate rows — expected 18000+"

def test_warehouse_tables():
    import sqlite3
    conn = sqlite3.connect("verdigris_warehouse.db")
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    required = {"eia_rates", "eia_consumption", "wb_country_data"}
    missing = required - set(tables)
    assert not missing, f"Missing warehouse tables: {missing}"

def test_intl_rates_static():
    from data.intl_rates import get_current_rate
    rate = get_current_rate("GB")
    assert rate > 0, "UK rate should be > 0"
    assert rate < 100, f"UK rate {rate} seems too high"

def test_intl_rates_history():
    from data.intl_rates import get_intl_rate_history
    hist = get_intl_rate_history("AU")
    assert hist.get("residential"), "Australia should have residential history"
    assert 2015 in hist["residential"], "Should have 2015 data"

def test_vault_retrieval():
    from memory.search import find_relevant_notes
    notes = find_relevant_notes("solar viability")
    assert len(notes) > 0, "find_relevant_notes returned nothing"

run_test("warehouse exists", test_warehouse_exists)
run_test("warehouse EIA rates populated", test_warehouse_eia_rates)
run_test("warehouse required tables present", test_warehouse_tables)
run_test("intl_rates static lookup", test_intl_rates_static)
run_test("intl_rates historical data", test_intl_rates_history)
run_test("vault retrieval working", test_vault_retrieval)

# ── SECTION 3 — ML Models ─────────────────────────────────
section("3. ML Models")

def test_lcoe_computation():
    from models.clustering import compute_lcoe_table, LocationFeatures
    lf = LocationFeatures(
        name="Test",
        irradiance=5.0,
        rate_cents_kwh=20.0,
        density=500,
        viability_score=60,
        payback_years=7.0,
    )
    result = compute_lcoe_table(lf, is_us=True)
    assert len(result.rows_res) == 3, "Should have 3 residential rows"
    assert len(result.rows_com) == 3, "Should have 3 commercial rows"
    assert result.lcoe_cents_kwh > 0, "LCOE should be positive"
    assert result.lcoe_cents_kwh_noitc > result.lcoe_cents_kwh, \
        "LCOE without ITC should be higher"

def test_rate_trajectory_us():
    from models.clustering import compute_rate_trajectory
    result = compute_rate_trajectory(
        "Texas", is_us=True, state_abbr="TX"
    )
    assert result.cagr > 0, "Texas CAGR should be positive"
    assert 2015 in result.historical, "Should have 2015 data"
    assert 2024 in result.historical, "Should have 2024 data"
    assert len(result.projected) > 0, "Should have projections"

def test_rate_trajectory_international():
    from models.clustering import compute_rate_trajectory
    result = compute_rate_trajectory(
        "Germany", is_us=False, iso2="DE"
    )
    assert result.source != "Estimated", \
        "Germany should use Eurostat, not estimated"
    assert len(result.historical) > 5, \
        "Germany should have 5+ years of history"

def test_location_extraction():
    from memory.search import _extract_location_from_question
    assert _extract_location_from_question(
        "payback for Texas"
    ) == "Texas"
    assert _extract_location_from_question(
        "Would you like me to generate reports?"
    ) == ""
    assert _extract_location_from_question(
        "Tell me about Hawaii"
    ) == "Hawaii"

def test_analysis_classification():
    from memory.search import _is_analysis
    assert _is_analysis("what is the payback for Texas")
    assert _is_analysis("show me the roi for Hawaii")
    assert not _is_analysis("would you like me to generate reports")
    assert not _is_analysis("what are some common trends")

run_test("LCOE computation", test_lcoe_computation)
run_test("rate trajectory U.S.", test_rate_trajectory_us)
run_test("rate trajectory international", 
         test_rate_trajectory_international, slow=True)
run_test("location extraction", test_location_extraction)
run_test("analysis classification", test_analysis_classification)

# ── SECTION 4 — Agent Pipeline ────────────────────────────
section("4. Agent Pipeline (slow — uses API)")

def test_analyst_texas():
    from agent.analyst import run
    findings = run("Texas", "solar_viability")
    assert "error" not in findings, \
        f"Analyst failed for Texas: {findings.get('error')}"
    assert findings.get("headline"), "Missing headline"
    assert findings.get("findings"), "Missing findings list"
    assert findings.get("is_us") is not None, "Missing is_us flag"
    # Score is embedded in headline — verify headline contains a score
    headline = findings.get("headline", "")
    assert any(c.isdigit() for c in headline), \
        f"Headline contains no numeric score: {headline}"

def test_demand_forecast_state_only():
    from agent.analyst import run
    result = run("Dallas", "demand_forecast")
    assert "error" in result, \
        "Dallas demand forecast should fail — city not state"

def test_intl_rates_api():
    from data.intl_rates import get_intl_rate_history
    hist = get_intl_rate_history("DE")
    assert hist.get("is_live"), "Germany should use live Eurostat data"
    res = hist.get("residential", {})
    assert len(res) >= 5, "Should have 5+ years of Eurostat data"

run_test("analyst pipeline — Texas", test_analyst_texas, slow=True)
run_test("demand forecast blocks cities", 
         test_demand_forecast_state_only, slow=True)
run_test("Eurostat live API", test_intl_rates_api, slow=True)

# ── SECTION 5 — Imports ───────────────────────────────────
section("5. Critical Imports")

def test_import_app():
    import importlib.util
    spec = importlib.util.spec_from_file_location("app", "app.py")
    assert spec is not None

def test_import_clustering():
    from models.clustering import (
        run_full_market_analysis,
        compute_lcoe_table,
        compute_rate_trajectory,
        LCOEResult,
        RateTrajectoryResult,
    )

def test_import_intl_rates():
    from data.intl_rates import (
        get_current_rate,
        get_current_commercial_rate,
        get_intl_rate_history,
        STATIC_RATES,
        EU_ISO2,
    )

def test_import_search():
    from memory.search import (
        chat,
        find_relevant_notes,
        _analysis_payback,
        _execute_escalation,
        _extract_location_from_question,
        _is_analysis,
    )

def test_no_stale_get_intl_rate():
    """Ensure old function name is not imported directly anywhere."""
    import ast
    stale = []
    for py_file in Path(".").rglob("*.py"):
        if ".venv" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if (node.module == "data.intl_rates"
                            and any(
                                alias.name == "get_intl_rate"
                                and alias.asname is None
                                for alias in node.names
                            )):
                        stale.append(str(py_file))
        except Exception:
            pass
    assert not stale, \
        f"Stale get_intl_rate import in: {stale}"

run_test("app.py loadable", test_import_app)
run_test("clustering imports", test_import_clustering)
run_test("intl_rates imports", test_import_intl_rates)
run_test("search imports", test_import_search)
run_test("no stale get_intl_rate imports", test_no_stale_get_intl_rate)

# ── RESULTS ───────────────────────────────────────────────
total = len(passed) + len(failed) + len(skipped)
print(f"\n{t('─' * 50, DIM)}")
print(f"{t('RESULTS', GOLD)}\n")
print(f"  {t(str(len(passed)), GREEN)} passed  "
      f"{t(str(len(failed)), RED)} failed  "
      f"{t(str(len(skipped)), DIM)} skipped  "
      f"{t(f'/ {total} total', DIM)}")

if failed:
    print(f"\n  {t('Failed tests:', RED)}")
    for name in failed:
        print(f"    {t('·', RED)} {name}")
    print(f"\n  {t('Fix these before pushing to GitHub.', RED)}\n")
    sys.exit(1)
else:
    print(f"\n  {t('✓ All tests passed — safe to push.', GREEN)}\n")
    sys.exit(0)
