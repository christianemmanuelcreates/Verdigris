#!/usr/bin/env python3
"""
Verdigris CLI — Terminal interface for the Verdigris
energy intelligence platform.

Usage:
    python3 cli.py              # show status and help
    python3 cli.py status       # system diagnostic
    python3 cli.py vault        # list vault reports
    python3 cli.py report <location> [report_type]
    python3 cli.py ask <question>
    python3 cli.py seed         # run DEMO_SEED.py
    python3 cli.py run          # launch Streamlit UI
"""

import sys
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TEAL  = "\033[38;2;78;205;196m"
GOLD  = "\033[38;2;201;169;110m"
GREEN = "\033[38;2;123;198;122m"
RED   = "\033[38;2;232;99;99m"
DIM   = "\033[38;2;45;90;90m"
WHITE = "\033[38;2;220;220;220m"
BOLD  = "\033[1m"
RESET = "\033[0m"

def t(text, color=TEAL):
    return f"{color}{text}{RESET}"

def banner():
    print()
    print(t("╔══════════════════════════════════════════════════╗"))
    print(t("║  ") + t("✦", GOLD) + t(" ") + t("VERDIGRIS", GOLD) + t(" — Energy Intelligence Platform", WHITE) + t("      ║"))
    print(t("║    ") + t("Viridian Society · viridian R&D", DIM) + t("                  ║"))
    print(t("╚══════════════════════════════════════════════════╝"))
    print()

def check_key(name, env_var):
    val = os.getenv(env_var, "")
    ok = bool(val)
    symbol = t("✓", GREEN) if ok else t("✗", RED)
    status = t("configured", GREEN) if ok else t("MISSING", RED)
    print(f"  {symbol}  {t(name, GOLD):<22} {status}")
    return ok

def cmd_status():
    banner()
    print(t("SYSTEM STATUS", TEAL) + "\n")

    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    if vault_path and Path(vault_path).exists():
        reports = list(Path(vault_path, "Reports").glob("*.md"))
        print(f"  {t('✓', GREEN)}  {t('Vault', GOLD):<22} "
              f"{t(str(len(reports)) + ' reports', WHITE)} "
              f"{t('→ ' + vault_path, DIM)}")
    else:
        print(f"  {t('✗', RED)}  {t('Vault', GOLD):<22} "
              f"{t('NOT CONFIGURED — set OBSIDIAN_VAULT_PATH in .env', RED)}")

    warehouse = Path("verdigris_warehouse.db")
    if warehouse.exists():
        import sqlite3
        conn = sqlite3.connect(warehouse)
        rows = conn.execute(
            "SELECT COUNT(*) FROM eia_rates"
        ).fetchone()[0]
        conn.close()
        print(f"  {t('✓', GREEN)}  {t('Warehouse', GOLD):<22} "
              f"{t(f'{rows:,} rows', WHITE)}")
    else:
        print(f"  {t('✗', RED)}  {t('Warehouse', GOLD):<22} "
              f"{t('NOT FOUND — run: python3 data/seed_warehouse.py', RED)}")

    print()
    print(t("  API KEYS", DIM))
    check_key("OpenRouter (LLM)",  "OPENROUTER_API_KEY")
    check_key("EIA (U.S. rates)",  "EIA_API_KEY")
    check_key("NREL (PVWatts)",    "NREL_API_KEY")
    check_key("Census (density)",  "CENSUS_API_KEY")
    print(f"  {t('✓', GREEN)}  {t('Eurostat', GOLD):<22} "
          f"{t('no key required', DIM)}")
    print(f"  {t('✓', GREEN)}  {t('NASA POWER', GOLD):<22} "
          f"{t('no key required', DIM)}")
    print()
    print(f"  {t('→', TEAL)}  Browser UI: {t('streamlit run app.py', GOLD)}")
    print(f"  {t('→', TEAL)}  Logs:       {t('logs/verdigris.log', DIM)}")
    print()

def cmd_vault():
    banner()
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    if not vault_path or not Path(vault_path).exists():
        print(t("  Vault not configured. Set OBSIDIAN_VAULT_PATH in .env", RED))
        return
    reports = sorted(
        Path(vault_path, "Reports").glob("*.md"),
        reverse=True
    )
    print(t(f"VAULT — {len(reports)} reports\n", TEAL))
    for r in reports[:20]:
        name = r.stem.replace("-", " ").replace("_", " ")
        print(f"  {t('·', DIM)} {t(name, WHITE)}")
    if len(reports) > 20:
        print(f"\n  {t(f'... and {len(reports)-20} more', DIM)}")
    print()

def cmd_report(args):
    if not args:
        print(t("  Usage: python3 cli.py report <location> [report_type]", GOLD))
        print(t("  Types: solar_viability | demand_forecast | rate_roi | executive_summary", DIM))
        return
    location = args[0]
    report_type = args[1] if len(args) > 1 else "solar_viability"
    banner()
    print(t(f"RUNNING REPORT — {location} / {report_type}\n", TEAL))
    try:
        from agent.analyst import run
        from agent.report import write
        print(f"  {t('→', TEAL)} Fetching data for {t(location, GOLD)}...")
        findings = run(location, report_type)
        if "error" in findings:
            print(f"  {t('✗', RED)} Analysis failed: {findings['error']}")
            return
        print(f"  {t('→', TEAL)} Writing report...")
        report_md = write(findings, report_type)
        headline = findings.get("headline", "Report complete")
        print(f"  {t('✓', GREEN)} {t(headline, WHITE)}")
        print()
        print(t("  ─" * 25, DIM))
        preview = report_md[:600].strip()
        for line in preview.split("\n")[:15]:
            print(f"  {line}")
        print(t("  ─" * 25, DIM))
        print()
        print(f"  {t('→', TEAL)} Full report saved to vault.")
        print(f"  {t('→', TEAL)} Run {t('streamlit run app.py', GOLD)} to view in browser.")
    except Exception as e:
        print(f"  {t('✗', RED)} Error: {e}")
    print()

def cmd_ask(args):
    if not args:
        print(t("  Usage: python3 cli.py ask <question>", GOLD))
        return
    question = " ".join(args)
    banner()
    print(t(f"VAULT QUERY — {question}\n", TEAL))
    try:
        from memory.search import chat
        response = chat(question, [])
        print()
        for line in response.split("\n"):
            clean = line.replace("**", "").replace("*", "")
            if clean.startswith("##"):
                print(f"  {t(clean.replace('#','').strip(), GOLD)}")
            elif clean.startswith("#"):
                print(f"  {t(clean.replace('#','').strip(), TEAL)}")
            elif clean.startswith("Sources:"):
                print(f"  {t(clean, DIM)}")
            else:
                print(f"  {clean}")
        print()
    except Exception as e:
        print(f"  {t('✗', RED)} Error: {e}")

def cmd_help():
    banner()
    print(t("COMMANDS\n", TEAL))
    cmds = [
        ("status",                   "System diagnostic — vault, warehouse, API keys"),
        ("vault",                    "List all reports in the knowledge base"),
        ("report <location>",        "Run a solar viability report"),
        ("report <location> <type>", "Run a specific report type"),
        ("ask <question>",           "Query the vault knowledge base"),
        ("run",                      "Launch the Streamlit UI in browser"),
        ("seed",                     "Seed the demo vault (32 reports, ~$1.50)"),
    ]
    for cmd, desc in cmds:
        print(f"  {t(cmd, GOLD):<35} {t(desc, DIM)}")
    print()
    print(t("REPORT TYPES", TEAL))
    types = [
        ("solar_viability",   "Solar resource, rates, payback, viability score"),
        ("demand_forecast",   "Prophet time series — U.S. states only"),
        ("rate_roi",          "Rate environment and ROI analysis"),
        ("executive_summary", "One-page stakeholder brief"),
    ]
    for rtype, desc in types:
        print(f"  {t(rtype, GOLD):<35} {t(desc, DIM)}")
    print()
    print(t("EXAMPLES", TEAL))
    examples = [
        "python3 cli.py status",
        "python3 cli.py report Hawaii",
        "python3 cli.py report Germany solar_viability",
        'python3 cli.py ask "Which states have the strongest solar economics?"',
        "python3 cli.py run",
    ]
    for ex in examples:
        print(f"  {t('$', DIM)} {t(ex, WHITE)}")
    print()
    print(f"  {t('→', TEAL)} Browser UI: {t('streamlit run app.py', GOLD)}")
    print()

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("help", "--help", "-h"):
        cmd_help()
    elif args[0] == "status":
        cmd_status()
    elif args[0] == "vault":
        cmd_vault()
    elif args[0] == "report":
        cmd_report(args[1:])
    elif args[0] == "ask":
        cmd_ask(args[1:])
    elif args[0] == "run":
        print()
        print(t("  Launching Verdigris in browser...", TEAL))
        print(f"  {t('→', DIM)} {t('streamlit run app.py', GOLD)}")
        print()
        subprocess.run(["streamlit", "run", "app.py"])
    elif args[0] == "seed":
        print()
        print(t("  Seeding demo vault — this takes ~30 minutes", TEAL))
        print()
        subprocess.run(["python3", "DEMO_SEED.py"])
    else:
        print(t(f"\n  Unknown command: {args[0]}", RED))
        print(t("  Run: python3 cli.py help\n", DIM))

if __name__ == "__main__":
    main()
