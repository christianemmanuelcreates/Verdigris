from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

from memory.vault import load_voice_profile, write_report

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

REPORT_TYPE_LABELS = {
    "solar_viability": "Solar Viability Assessment",
    "demand_forecast": "Energy Demand Forecast",
    "market_comparison": "Market Comparison",
    "rate_roi": "Rate & ROI Analysis",
    "executive_summary": "Executive Summary",
}


def write(findings_package: dict, report_type: str) -> str:
    """
    Takes a findings package from analyst.py and produces a
    formatted Markdown report via the writer LLM.

    Also writes the report to Obsidian vault automatically.

    Returns the Markdown report string.
    Returns an error string if the LLM call fails.
    """
    instructions = _load_config("prompts/report.md")
    voice_profile = load_voice_profile()
    type_label = REPORT_TYPE_LABELS.get(report_type, report_type)

    prompt = _build_prompt(
        findings_package=findings_package,
        report_type=report_type,
        type_label=type_label,
        instructions=instructions,
        voice_profile=voice_profile,
    )

    report_md = _call_llm(prompt)

    if report_md is None:
        return "**Error:** Report generation failed. Check MODEL_WRITER and OPENROUTER_API_KEY."

    # Write to Obsidian vault automatically
    location = findings_package.get("location", "Unknown")
    if isinstance(location, dict):
        location = location.get("name", "Unknown")

    vault_path = write_report({
        "location": location,
        "report_type": report_type,
        "content": report_md,
        "findings": findings_package,
        "date": date.today().isoformat(),
    })

    if vault_path:
        LOGGER.info("Report saved to Obsidian: %s", vault_path)
    else:
        LOGGER.warning("Report not saved to Obsidian — vault unavailable")

    return report_md


def _build_prompt(
    findings_package: dict,
    report_type: str,
    type_label: str,
    instructions: str,
    voice_profile: str,
) -> str:
    """Assembles the writer prompt from all components."""
    findings_str = json.dumps(findings_package, indent=2, default=str)

    return (
        f"{instructions}\n\n"
        f"---\n\n"
        f"## Analyst findings package\n\n"
        f"```json\n{findings_str}\n```\n\n"
        f"---\n\n"
        f"## Report type\n\n"
        f"{type_label}\n\n"
        f"---\n\n"
        f"## Operator voice profile\n\n"
        f"{voice_profile}\n\n"
        f"---\n\n"
        f"Today's date is {date.today().isoformat()}. "
        f"Use this as the report date. "
        f"Now write the {type_label} report. "
        f"Return only the Markdown report body. "
        f"No preamble. No explanation. Start with the report title."
    )


def _call_llm(prompt: str) -> str | None:
    """
    Calls the writer LLM via OpenRouter.
    Returns the Markdown string or None on failure.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("MODEL_WRITER", "google/gemini-2.5-pro")
    base_url = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ).rstrip("/")

    if not api_key:
        LOGGER.error("OPENROUTER_API_KEY not set in .env")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://viridiansociety.com",
        "X-Title": "Verdigris",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the Verdigris report writer. "
                    "Follow the instructions exactly. "
                    "Return only the Markdown report — "
                    "no JSON, no code fences around the report itself, "
                    "no explanation before or after."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except requests.RequestException as exc:
        LOGGER.error("OpenRouter writer request failed: %s", exc)
        return None
    except (KeyError, IndexError) as exc:
        LOGGER.error("Unexpected OpenRouter response structure: %s", exc)
        return None

    # Strip any accidental code fences around the whole report
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    return cleaned


def _load_config(filename: str) -> str:
    """Loads a file from config/ directory. Never raises."""
    path = PROJECT_ROOT / "config" / filename
    if not path.exists():
        LOGGER.error("Config file not found: %s", path)
        return f"[Config file missing: {filename}]"
    return path.read_text(encoding="utf-8")