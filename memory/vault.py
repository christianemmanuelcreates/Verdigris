from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_VOICE_PROFILE = """
Write in a direct, professional tone suitable for energy industry professionals.
Use precise numbers. Avoid hedging language. Lead with the most decision-relevant
finding. Keep recommendations concrete and actionable.
""".strip()


def get_vault_path() -> Path | None:
    """Returns configured Obsidian vault path or None. Never raises."""
    vault_str = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not vault_str:
        LOGGER.warning("OBSIDIAN_VAULT_PATH not set in .env")
        return None
    vault = Path(vault_str).expanduser()
    if not vault.exists():
        LOGGER.warning("Obsidian vault path does not exist: %s", vault)
        return None
    return vault


def write_report(report_data: dict) -> str | None:
    """
    Writes a completed report to the Obsidian vault.

    report_data keys:
        location    str  — e.g. "Texas"
        report_type str  — e.g. "solar_viability"
        content     str  — full Markdown report body from report.py
        findings    dict — findings package from analyst.py
        date        str  — ISO date string e.g. "2026-04-12"

    Creates/updates:
        Reports/YYYY-MM-DD_{location}_{report_type}.md
        Locations/{location}.md
        Index.md

    Returns the path string of the report note, or None on failure.
    Never raises.
    """
    vault = get_vault_path()
    if vault is None:
        LOGGER.warning("Vault not configured — report not saved to Obsidian")
        return None

    try:
        location = report_data.get("location", "Unknown")
        report_type = report_data.get("report_type", "unknown")
        content = report_data.get("content", "")
        findings = report_data.get("findings", {})
        report_date = report_data.get("date", date.today().isoformat())

        loc_slug = _slugify(location)
        type_slug = report_type.replace("_", "-")
        filename = f"{report_date}_{loc_slug}_{type_slug}.md"
        period = report_date[:7]

        # Ensure folders exist
        reports_dir = vault / "Reports"
        locations_dir = vault / "Locations"
        reports_dir.mkdir(parents=True, exist_ok=True)
        locations_dir.mkdir(parents=True, exist_ok=True)

        # Write report note
        report_note = _build_report_note(
            location=location,
            report_type=report_type,
            report_date=report_date,
            period=period,
            content=content,
            findings=findings,
        )
        report_path = reports_dir / filename
        report_path.write_text(report_note, encoding="utf-8")
        LOGGER.info("Report written to: %s", report_path)

        # Update location aggregation note
        _update_location_note(locations_dir, location, report_type,
                               report_date, filename, findings)

        # Update vault index
        _update_index(vault, location, report_type, report_date, filename)

        return str(report_path)

    except Exception as exc:
        LOGGER.error("Failed to write report to vault: %s", exc)
        return None


def load_voice_profile() -> str:
    """
    Loads operator voice profile from vault.
    Falls back to default if vault unavailable. Never raises.
    """
    vault = get_vault_path()
    if vault is None:
        return DEFAULT_VOICE_PROFILE

    # Option A — dedicated file
    voice_path = vault / "Templates" / "voice-profile.md"
    if voice_path.exists():
        try:
            return voice_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            LOGGER.warning("Could not read voice profile: %s", exc)

    # Option B — operator section in Index.md
    index_path = vault / "Index.md"
    if index_path.exists():
        try:
            text = index_path.read_text(encoding="utf-8")
            match = re.search(
                r"## Operator voice\n(.+?)(?=\n##|\Z)", text, re.DOTALL
            )
            if match:
                return match.group(1).strip()
        except Exception as exc:
            LOGGER.warning("Could not read voice from Index.md: %s", exc)

    return DEFAULT_VOICE_PROFILE


def load_index() -> str:
    """Reads Index.md. Returns empty string if missing. Never raises."""
    vault = get_vault_path()
    if vault is None:
        return ""
    index_path = vault / "Index.md"
    if not index_path.exists():
        return ""
    try:
        return index_path.read_text(encoding="utf-8")
    except Exception as exc:
        LOGGER.warning("Could not read Index.md: %s", exc)
        return ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_report_note(
    location: str,
    report_type: str,
    report_date: str,
    period: str,
    content: str,
    findings: dict,
) -> str:
    """Builds the full Markdown note using the report template structure."""
    type_label = report_type.replace("_", " ").title()
    headline = findings.get("headline", "No headline available")
    sources = findings.get("sources", [])
    sources_list = (
        "\n".join(f"- {s}" for s in sources)
        if sources else "- Not recorded"
    )

    # Key findings — plain English sentences
    finding_list = findings.get("findings", [])
    key_findings = "\n".join(
        f"- {f.get('plain_english', f.get('title', ''))}"
        for f in finding_list[:5]
    )

    # Headline metrics table
    metrics_rows = ""
    for f in finding_list:
        title = f.get("title", "")
        number = f.get("number", "")
        benchmark = f.get("benchmark", "")
        if title and number:
            metrics_rows += f"| {title} | {number} | {benchmark} |\n"

    # Extract PVWatts output from connectors if present
    pvwatts = findings.get("connectors", {}).get("pvwatts", {})
    if pvwatts and pvwatts.get("annual_kwh"):
        metrics_rows += (
            f"| PVWatts annual output | "
            f"{pvwatts['annual_kwh']:,.0f} kWh/year | "
            f"4kW standard system |\n"
        )

    # Model accuracy block — only present for demand forecasts
    model_accuracy = ""
    demand = findings.get("models", {}).get("demand", {})
    if demand and isinstance(demand, dict) and "metrics" in demand:
        m = demand["metrics"]
        if isinstance(m, dict):
            r2_pct = round((m.get("r2", 0) or 0) * 100, 1)
            mape = m.get("mape", 0) or 0
            improvement = m.get("improvement_pct", 0) or 0
            model_accuracy = (
                f"\n## Model accuracy\n\n"
                f"Model explains {r2_pct}% of variation. "
                f"Predictions off by {mape:.1f}% on average — "
                f"{improvement:.1f}% better than a naive baseline.\n"
            )

    # YAML frontmatter — machine readable, drives Obsidian graph + dataview
    safe_headline = headline.replace('"', "'")
    frontmatter = (
        f"---\n"
        f"location: {location}\n"
        f"report_type: {report_type}\n"
        f"date: {report_date}\n"
        f"period: {period}\n"
        f"headline: \"{safe_headline}\"\n"
        f"tags: [verdigris, {report_type}, {_slugify(location)}]\n"
        f"---\n"
    )

    # Wikilinks — drives vault graph and chat traversal
    wikilinks = f"[[{location}]] · [[{type_label}]] · [[{period}]]"

    return (
        f"{frontmatter}\n"
        f"# {type_label} — {location}\n\n"
        f"**Date:** {report_date}  \n"
        f"**Location:** {location}  \n"
        f"**Report type:** {type_label}  \n"
        f"**Period:** {period}\n\n"
        f"## Headline\n\n"
        f"{headline}\n\n"
        f"## Headline metrics\n\n"
        f"| Metric | Value | vs. Average |\n"
        f"|--------|-------|-------------|\n"
        f"{metrics_rows}\n"
        f"## Key findings\n\n"
        f"{key_findings}\n"
        f"{model_accuracy}\n"
        f"## Full report\n\n"
        f"{content}\n\n"
        f"## Data sources\n\n"
        f"{sources_list}\n\n"
        f"## Links\n\n"
        f"{wikilinks}\n"
    )


def _update_location_note(
    locations_dir: Path,
    location: str,
    report_type: str,
    report_date: str,
    filename: str,
    findings: dict,
) -> None:
    """Creates or appends to the location aggregation note."""
    loc_path = locations_dir / f"{location}.md"
    headline = findings.get("headline", "")
    type_label = report_type.replace("_", " ").title()
    report_link = f"[[Reports/{filename}|{report_date} — {type_label}]]"
    new_entry = f"- {report_link}: {headline}\n"

    if loc_path.exists():
        existing = loc_path.read_text(encoding="utf-8")
        if filename not in existing:
            if "## Reports" in existing:
                loc_path.write_text(existing + new_entry, encoding="utf-8")
            else:
                loc_path.write_text(
                    existing + f"\n## Reports\n\n{new_entry}",
                    encoding="utf-8"
                )
    else:
        loc_path.write_text(
            f"---\n"
            f"location: {location}\n"
            f"tags: [verdigris, location]\n"
            f"---\n\n"
            f"# {location}\n\n"
            f"All Verdigris reports for this location.\n\n"
            f"## Reports\n\n"
            f"{new_entry}",
            encoding="utf-8"
        )


def _update_index(
    vault: Path,
    location: str,
    report_type: str,
    report_date: str,
    filename: str,
) -> None:
    """Updates or creates vault Index.md with the new report entry."""
    index_path = vault / "Index.md"
    type_label = report_type.replace("_", " ").title()
    new_row = (
        f"| {report_date} | "
        f"[[Reports/{filename}\\|{location} — {type_label}]] |\n"
    )

    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
        if filename not in existing:
            if "## Recent reports" in existing:
                index_path.write_text(existing + new_row, encoding="utf-8")
            else:
                index_path.write_text(
                    existing
                    + "\n## Recent reports\n\n"
                    + "| Date | Report |\n|------|--------|\n"
                    + new_row,
                    encoding="utf-8"
                )
    else:
        index_path.write_text(
            f"# Verdigris — Vault Index\n\n"
            f"Auto-maintained by Verdigris. Do not edit the table manually.\n\n"
            f"## Recent reports\n\n"
            f"| Date | Report |\n"
            f"|------|--------|\n"
            f"{new_row}",
            encoding="utf-8"
        )


def _slugify(text: str) -> str:
    """Converts a string to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")