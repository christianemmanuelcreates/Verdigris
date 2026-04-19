from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from memory.vault import get_vault_path, load_index

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Token budget — hard limit for vault context in any single LLM call
MAX_CONTEXT_TOKENS = 4_000
WORDS_PER_TOKEN = 0.75  # conservative estimate

# Intent classification keywords
ANALYSIS_KEYWORDS = {
    "payback", "roi", "return", "lcoe", "cost", "invest",
    "scenario", "sensitivity", "what if", "if rates", "if price",
    "rank", "ranking", "compare all", "best market", "which market",
    "correlation", "trend across", "all markets", "all states",
    "forecast", "predict", "projection",
    "rise", "increase by", "higher rate", "lower rate",
    "decrease by", "if rate", "rate increase", "rate decrease",
    "rate rises", "rate drops", "rate change",
    "similar markets", "markets like", "comparable to",
    "cluster", "find markets", "where else", "market analysis",
    "opportunity", "deploy", "deployment", "decision tree",
    "go no-go", "regression", "what drives",
}

ESCALATION_KEYWORDS = {
    "run a report", "generate report", "new report", "analyze",
    "solar viability", "demand forecast", "rate roi", "executive summary",
    "market comparison", "run analysis on",
}


# ── Public API ────────────────────────────────────────────────────────────────

def find_relevant_notes(
    query: str,
    max_notes: int = 10,
) -> list[dict]:
    """
    Three-tier vault retrieval:
    Tier 1 — Index.md scan (always)
    Tier 2 — Frontmatter + filename keyword match
    Tier 3 — Wikilink traversal (1 hop from matched notes)

    Returns list of dicts:
    {
        "title": str,
        "path": str,
        "relevance": str,   # "index_match" | "keyword" | "wikilink"
        "content": str,     # first 500 chars of note
        "score": int        # higher = more relevant
    }
    """
    vault = get_vault_path()
    if vault is None:
        return []

    query_lower = query.lower()
    query_terms = set(re.findall(r"\w+", query_lower))

    results: dict[str, dict] = {}

    # Tier 1 — Index scan
    index_content = load_index()
    if index_content:
        for line in index_content.splitlines():
            match = re.search(r"\[\[([^\]]+)\]\]", line)
            if match:
                title = match.group(1)
                if any(term in title.lower() for term in query_terms):
                    note_path = _find_note_by_title(vault, title)
                    if note_path:
                        results[str(note_path)] = {
                            "title": title,
                            "path": str(note_path),
                            "relevance": "index_match",
                            "content": _read_note_preview(note_path),
                            "score": 3,
                        }

    # Tier 2 — Keyword match across Reports/ and Locations/
    for folder in ["Reports", "Locations", "Insights"]:
        folder_path = vault / folder
        if not folder_path.exists():
            continue
        for note_path in folder_path.glob("*.md"):
            if str(note_path) in results:
                continue
            text = note_path.read_text(encoding="utf-8", errors="ignore")
            text_lower = text.lower()
            match_count = sum(1 for term in query_terms
                              if len(term) > 3 and term in text_lower)
            if match_count >= 2:
                title = _extract_title(text, note_path.stem)
                results[str(note_path)] = {
                    "title": title,
                    "path": str(note_path),
                    "relevance": "keyword",
                    "content": _read_note_preview(note_path),
                    "score": match_count,
                }

    # Tier 3 — Wikilink traversal from top results
    top_results = sorted(results.values(), key=lambda x: -x["score"])[:3]
    for result in top_results:
        note_path = Path(result["path"])
        try:
            text = note_path.read_text(encoding="utf-8", errors="ignore")
            wikilinks = re.findall(r"\[\[([^\]|]+)", text)
            for link in wikilinks[:5]:
                linked_path = _find_note_by_title(vault, link)
                if linked_path and str(linked_path) not in results:
                    results[str(linked_path)] = {
                        "title": link,
                        "path": str(linked_path),
                        "relevance": "wikilink",
                        "content": _read_note_preview(linked_path),
                        "score": 1,
                    }
        except Exception:
            pass

    # Sort by score descending, cap at max_notes
    ranked = sorted(results.values(), key=lambda x: -x["score"])
    return ranked[:max_notes]


def chat(question: str, history: list[dict]) -> str:
    """
    Main chat entry point. Four modes:

    1. recall      — answer from vault notes
    2. comparison  — synthesize across multiple vault notes
    3. analysis    — run warehouse/model computation inline
    4. escalation  — trigger full analyst + report pipeline

    Returns Markdown string response.
    """
    question_lower = question.lower()

    # Analysis runs first — prevents location misidentification
    if _is_analysis(question_lower):
        result = _execute_analysis(question, question_lower)
        if result:
            return result

    # Auto-detect ZIP code input — run fresh report automatically
    import re as _re
    zip_match = _re.search(r'\b(\d{5})\b', question)
    if zip_match:
        zip_code = zip_match.group(1)
        # Check if we already have a report for this ZIP
        vault = get_vault_path()
        existing = []
        if vault and (vault / "Reports").exists():
            existing = list((vault / "Reports").glob(f"*{zip_code}*"))
        if not existing:
            # No existing report — run one automatically
            return _execute_escalation(zip_code, "solar_viability")
        # Report exists — fall through to vault recall

    # Escalation only if not an analysis question
    if _is_escalation(question_lower):
        location, report_type = _extract_escalation_params(question)
        if location:
            return _execute_escalation(location, report_type)

    # Default: vault retrieval + LLM answer
    notes = find_relevant_notes(question, max_notes=10)
    context = _build_chat_context(notes)
    index = load_index()

    return _call_chat_llm(question, history, context, index)


# ── Intent detection ──────────────────────────────────────────────────────────

def _is_escalation(q: str) -> bool:
    return any(kw in q for kw in ESCALATION_KEYWORDS)


def _is_analysis(q: str) -> bool:
    """
    Requires analysis keywords to appear with location
    context or explicit question words to avoid false
    positives on general conversation.
    """
    if not any(kw in q for kw in ANALYSIS_KEYWORDS):
        return False
    # Must also contain a question signal or location signal
    question_signals = {
        "what", "how", "show", "calculate", "compute",
        "tell me", "give me", "find", "run", "get",
        "for ", "of ", "payback", "roi", "lcoe",
    }
    return any(sig in q for sig in question_signals)


def _extract_escalation_params(question: str) -> tuple[str, str]:
    """Extract location and report type from escalation request."""
    report_map = {
        "solar viability": "solar_viability",
        "demand forecast": "demand_forecast",
        "market comparison": "market_comparison",
        "rate roi": "rate_roi",
        "roi": "rate_roi",
        "executive summary": "executive_summary",
    }
    report_type = "solar_viability"  # default
    for phrase, rtype in report_map.items():
        if phrase in question.lower():
            report_type = rtype
            break

    # Simple location extraction — look for capitalized words
    words = question.split()
    candidates = [w.strip(",.?!") for w in words
                  if w[0].isupper() and len(w) > 2
                  and w.lower() not in {"run", "generate", "create",
                                        "analyze", "report", "what",
                                        "the", "for", "and"}]
    location = " ".join(candidates[:2]) if candidates else ""
    return location, report_type


# ── Inline analysis engine ────────────────────────────────────────────────────

def _execute_analysis(question: str, q_lower: str) -> str | None:
    """
    Routes analytical questions to appropriate computation.
    Returns Markdown string or None if analysis not applicable.
    """

    # Analysis 1 — Payback / ROI calculation
    if any(kw in q_lower for kw in {"payback", "roi", "return", "lcoe"}):
        return _analysis_payback(question)

    # Analysis 2 — Scenario / sensitivity analysis
    if any(kw in q_lower for kw in
           {"scenario", "sensitivity", "what if", "if rates", "if price"}):
        return _analysis_scenario(question, q_lower)

    # Analysis 3 — Market ranking across vault
    if any(kw in q_lower for kw in
           {"rank", "ranking", "best market", "compare all",
            "which market", "all markets", "all states"}):
        return _analysis_market_ranking()

    # Analysis 4 — Correlation or trend across markets
    if any(kw in q_lower for kw in
           {"correlation", "trend across", "all markets", "all states"}):
        return _analysis_market_ranking()

    # Analysis 5 — Full market intelligence (all 4 models)
    if any(kw in q_lower for kw in
           {"similar markets", "markets like", "comparable to",
            "cluster", "market analysis", "opportunity",
            "deploy", "what drives", "decision tree",
            "regression", "go no-go", "where else"}):
        location = _extract_location_from_question(question)
        if not location:
            return (
                "Which location would you like to run a full market "
                "analysis on? Include the location in your question — "
                "for example: 'Run a market analysis for California'"
            )
        try:
            from models.clustering import run_full_market_analysis
            result = run_full_market_analysis(location)
            return result["markdown_report"]
        except Exception as e:
            return f"Market analysis failed: {e}"

    return None


def _analysis_payback(question: str) -> str:
    """
    Calculates simple payback period and 10-year ROI from vault data.
    Reads most recent solar viability report for the relevant location.
    """
    vault = get_vault_path()
    if vault is None:
        return "Vault not configured — cannot run payback analysis."

    # Extract location from question
    location = _extract_location_from_question(question)

    # Find most recent solar viability report for this location
    report = _find_latest_report(vault, location, "solar-viability")
    if not report:
        if location:
            return (
                f"No solar viability report found for {location}. "
                f"Run a solar viability report first, then ask for payback analysis."
            )
        return (
            "No solar viability reports found in vault. "
            "Run a solar viability report first."
        )

    # Extract key metrics from report frontmatter + content
    metrics = _extract_metrics_from_report(report)
    rate = metrics.get("rate_cents_kwh")
    annual_kwh = metrics.get("annual_kwh")
    location_name = metrics.get("location", location or "this location")

    if not rate or not annual_kwh:
        return (
            f"Could not extract rate or solar output from {location_name} report. "
            "The report may be missing PVWatts data."
        )

    # System size comparison — 4kW, 8kW, 12kW
    COST_PER_KW = 3_000   # $3,000/kW installed
    ITC_RATE    = 0.30    # 30% federal ITC
    DEGRADATION = 0.005   # 0.5%/year

    system_sizes = [
        {"kw": 4,  "label": "4 kW (small residential)"},
        {"kw": 8,  "label": "8 kW (standard residential)"},
        {"kw": 12, "label": "12 kW (large residential)"},
    ]

    lines = [
        f"## Payback & ROI Analysis — {location_name}",
        f"*Source: vault report data · Rate: {rate:.2f}¢/kWh · "
        f"Output basis: {annual_kwh:,.0f} kWh/yr (4kW PVWatts)*\n",
        f"| System | Gross Cost | Net (ITC) | Annual Output | "
        f"Annual Savings | Payback | 10yr ROI |",
        f"|--------|-----------|-----------|---------------|"
        f"---------------|---------|----------|",
    ]

    best_payback = None
    best_label   = ""

    for sys in system_sizes:
        kw          = sys["kw"]
        gross       = kw * COST_PER_KW
        net         = gross * (1 - ITC_RATE)
        itc_saving  = gross - net
        # Scale annual output proportionally from PVWatts 4kW base
        sys_kwh     = annual_kwh * (kw / 4)
        savings     = sys_kwh * (rate / 100)
        payback     = net / savings if savings > 0 else None
        ten_savings = sum(
            sys_kwh * ((1 - DEGRADATION) ** yr) * (rate / 100)
            for yr in range(10)
        )
        roi_10      = ((ten_savings - net) / net) * 100

        pb_str = f"{payback:.1f} yr" if payback else "—"
        lines.append(
            f"| {sys['label']} "
            f"| ${gross:,.0f} "
            f"| ${net:,.0f} (-${itc_saving:,.0f} ITC) "
            f"| {sys_kwh:,.0f} kWh "
            f"| ${savings:,.0f} "
            f"| {pb_str} "
            f"| {roi_10:.1f}% |"
        )

        if best_payback is None or (payback and payback < best_payback):
            best_payback = payback
            best_label   = sys["label"]

    lines.extend([
        f"\n**Key metrics at {rate:.1f}¢/kWh:**",
        f"- All system sizes share the same payback period — "
        f"cost and output scale proportionally",
        f"- Payback: **{best_payback:.1f} years** after 30% ITC",
        f"- Larger systems multiply absolute savings — "
        f"choose based on roof space and consumption",
        f"\n*Assumptions: ${COST_PER_KW:,}/kW installed cost, "
        f"30% ITC, 0.5%/yr panel degradation, flat rates. "
        f"Output scaled from PVWatts 4kW simulation. "
        f"Actual results vary by roof, shading, and system design.*",
    ])

    result = "\n".join(lines)
    _save_insight(vault, f"payback_{_slugify(location_name)}", result)
    return result


def _analysis_scenario(question: str, q_lower: str) -> str:
    """
    Runs rate sensitivity / scenario analysis on a location.
    Shows how viability score changes under different rate assumptions.
    """
    from models.solar_score import score as solar_score

    vault = get_vault_path()
    if vault is None:
        return "Vault not configured — cannot run scenario analysis."

    location = _extract_location_from_question(question)
    report = _find_latest_report(vault, location, "solar-viability")

    if not report:
        return (
            f"No solar viability report found for {location or 'this location'}. "
            "Run a solar viability report first."
        )

    metrics = _extract_metrics_from_report(report)
    irradiance = metrics.get("irradiance")
    rate = metrics.get("rate_cents_kwh")
    density = metrics.get("density", 250.0)
    location_name = metrics.get("location", location or "this location")

    if not irradiance or not rate:
        return "Could not extract irradiance or rate from report for scenario analysis."

    scenarios = [
        ("Rate -20% (low)", rate * 0.80),
        ("Rate -10%", rate * 0.90),
        (f"Base ({rate:.1f}¢)", rate),
        ("Rate +10%", rate * 1.10),
        ("Rate +20% (high)", rate * 1.20),
    ]

    lines = [
        f"## Rate Sensitivity Analysis — {location_name}",
        f"*Irradiance: {irradiance:.2f} kWh/m²/day | "
        f"Density: {density:,.0f}/sq mi*\n",
        f"| Scenario | Rate (¢/kWh) | Viability Score | Label |",
        f"|----------|-------------|-----------------|-------|",
    ]

    for label, scenario_rate in scenarios:
        result = solar_score({
            "irradiance": irradiance,
            "rate": scenario_rate,
            "density": density,
        })
        marker = " ← current" if "Base" in label else ""
        lines.append(
            f"| {label} | {scenario_rate:.1f} | "
            f"{result['score']} | {result['label']}{marker} |"
        )

    base_score = solar_score(
        {"irradiance": irradiance, "rate": rate, "density": density}
    )["score"]
    high_score = solar_score(
        {"irradiance": irradiance, "rate": rate * 1.20, "density": density}
    )["score"]
    low_score = solar_score(
        {"irradiance": irradiance, "rate": rate * 0.80, "density": density}
    )["score"]

    lines.extend([
        f"\n**Key insight:** A 20% rate increase shifts "
        f"{location_name} from {base_score}/100 to {high_score}/100. "
        f"A 20% rate decrease drops it to {low_score}/100. "
        f"{'High rate sensitivity — this market is rate-driven.' if (high_score - low_score) > 15 else 'Moderate rate sensitivity — irradiance is the primary driver.'}",
        f"\n*Assumptions: all other inputs held constant.*",
    ])

    result_text = "\n".join(lines)
    _save_insight(vault, f"scenario_{_slugify(location_name)}", result_text)
    return result_text


def _analysis_market_ranking() -> str:
    """
    Ranks all analyzed markets by viability score from vault report frontmatter.
    No API calls — reads Markdown files only.
    """
    vault = get_vault_path()
    if vault is None:
        return "Vault not configured — cannot run market ranking."

    reports_dir = vault / "Reports"
    if not reports_dir.exists():
        return "No reports found in vault. Run some reports first."

    markets = []
    for note_path in reports_dir.glob("*solar-viability*.md"):
        try:
            text = note_path.read_text(encoding="utf-8", errors="ignore")
            metrics = _extract_metrics_from_report(note_path)
            location = metrics.get("location") or note_path.stem
            score = metrics.get("viability_score")
            rate = metrics.get("rate_cents_kwh")
            irradiance = metrics.get("irradiance")
            date = metrics.get("date", "")
            if location and score is not None:
                markets.append({
                    "location": location,
                    "score": score,
                    "rate": rate,
                    "irradiance": irradiance,
                    "date": date,
                })
        except Exception:
            continue

    if not markets:
        return (
            "No solar viability reports with extractable scores found. "
            "Ensure reports include a viability score in their findings."
        )

    markets.sort(key=lambda x: -(x["score"] or 0))

    lines = [
        "## Market Ranking — All Analyzed Locations",
        f"*{len(markets)} markets ranked by solar viability score*\n",
        "| Rank | Location | Score | Rate (¢/kWh) | Irradiance | Date |",
        "|------|----------|-------|-------------|------------|------|",
    ]

    for i, m in enumerate(markets, 1):
        rate_str = f"{m['rate']:.1f}" if m.get("rate") else "—"
        irr_str = f"{m['irradiance']:.2f}" if m.get("irradiance") else "—"
        lines.append(
            f"| {i} | {m['location']} | {m['score']}/100 | "
            f"{rate_str} | {irr_str} | {m['date']} |"
        )

    if markets:
        top = markets[0]
        lines.extend([
            f"\n**Top market:** {top['location']} ({top['score']}/100)",
            f"**Key driver:** "
            f"{'High electricity rates' if (top.get('rate') or 0) > 20 else 'Strong solar resource'}",
        ])

    if len(markets) >= 2:
        avg_score = sum(m["score"] for m in markets) / len(markets)
        lines.append(f"**Portfolio average:** {avg_score:.1f}/100")

    result_text = "\n".join(lines)
    _save_insight(vault, "market_ranking", result_text)
    return result_text


# ── Escalation ────────────────────────────────────────────────────────────────

def _execute_escalation(location: str, report_type: str) -> str:
    """
    Returns a sentinel string that app.py intercepts to trigger
    the full report pipeline with visible thinking states.
    Format: __ESCALATE__:location:report_type
    """
    if not location:
        return (
            "To run a report, specify a location. "
            "Example: 'Run a solar viability report for Texas'"
        )
    return f"__ESCALATE__:{location}:{report_type}"


# ── LLM chat call ─────────────────────────────────────────────────────────────

def _call_chat_llm(
    question: str,
    history: list[dict],
    context: str,
    index: str,
) -> str:
    """Calls the fast chat model with vault context."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("MODEL_FAST", "deepseek/deepseek-v3")
    base_url = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ).rstrip("/")

    if not api_key:
        return "OPENROUTER_API_KEY not set — cannot answer questions."

    chat_prompt = _load_config("prompts/chat.md")[:3000]

    # Build system message with vault context
    system = (
        f"{chat_prompt}\n\n"
        f"## Vault index\n{index[:1000]}\n\n"
        f"## Retrieved notes\n{context}"
    )

    messages = [{"role": "system", "content": system}]
    # Include last 6 history turns
    for turn in history[-6:]:
        messages.append(turn)
    messages.append({"role": "user", "content": question})

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://viridiansociety.com",
                "X-Title": "Verdigris",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.4,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        LOGGER.error("Chat LLM call failed: %s", exc)
        return f"Chat failed: {exc}"


# ── Context builder ───────────────────────────────────────────────────────────

def _build_chat_context(notes: list[dict]) -> str:
    """
    Assembles retrieved notes into a context string.
    Enforces 4,000 token budget.
    """
    if not notes:
        return "No relevant notes found in vault."

    parts = []
    total_words = 0
    budget_words = int(MAX_CONTEXT_TOKENS * WORDS_PER_TOKEN)

    for note in notes:
        header = (
            f"### {note['title']} "
            f"[{note['relevance']}]\n"
        )
        content = note.get("content", "")
        block = header + content + "\n"
        block_words = len(block.split())

        if total_words + block_words > budget_words:
            break

        parts.append(block)
        total_words += block_words

    return "\n".join(parts) if parts else "No notes within token budget."


# ── Helper functions ──────────────────────────────────────────────────────────

def _find_note_by_title(vault: Path, title: str) -> Path | None:
    """Finds a note file by title across all vault folders."""
    # Clean pipe aliases [[Note|Alias]] → "Note"
    title = title.split("|")[0].strip()
    slug = title.replace(" ", "-").replace("/", "-")

    for folder in ["Reports", "Locations", "Insights", ""]:
        search_dir = vault / folder if folder else vault
        if not search_dir.exists():
            continue
        # Exact match
        for ext in [".md"]:
            p = search_dir / f"{title}{ext}"
            if p.exists():
                return p
            p = search_dir / f"{slug}{ext}"
            if p.exists():
                return p
        # Partial match
        for p in search_dir.glob("*.md"):
            if title.lower() in p.stem.lower():
                return p
    return None


def _read_note_preview(note_path: Path, chars: int = 500) -> str:
    """Reads first N chars of a note, skipping frontmatter."""
    try:
        text = note_path.read_text(encoding="utf-8", errors="ignore")
        # Skip YAML frontmatter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                text = text[end + 3:].strip()
        return text[:chars]
    except Exception:
        return ""


def _extract_title(text: str, fallback: str) -> str:
    """Extracts the first H1 heading from note text."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _extract_location_from_question(question: str) -> str:
    """
    Extracts a likely location name from a question.
    Never returns common question/sentence words as locations.
    """
    # Words that are never locations
    NOT_LOCATIONS = {
        "what", "where", "when", "how", "why", "who",
        "would", "could", "should", "will", "can", "may",
        "please", "tell", "show", "give", "find", "run",
        "the", "this", "that", "these", "those", "there",
        "here", "some", "any", "all", "most", "many",
        "like", "just", "also", "then", "than", "more",
        "solar", "viability", "payback", "report", "analysis",
        "market", "energy", "rate", "cost", "data", "vault",
        "zipcode", "zip", "code", "location",
        "area", "city", "state", "country", "region",
        "place", "address", "number", "above", "below",
    }

    # Check for ZIP code first — highest confidence
    zip_match = re.search(r"\b(\d{5})\b", question)
    if zip_match:
        return zip_match.group(1)

    # Look for "for X" pattern first — most reliable
    match = re.search(
        r"\bfor\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        question
    )
    if match:
        loc = match.group(1)
        if loc.lower() not in NOT_LOCATIONS:
            return loc

    # Look for "of X" pattern
    match = re.search(
        r"\bof\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        question
    )
    if match:
        loc = match.group(1)
        if loc.lower() not in NOT_LOCATIONS:
            return loc

    # Look for known state/country names explicitly
    # Only match capitalized words not in exclusion list
    words = question.split()
    for w in words:
        clean = w.strip(",.\'\"")
        if (len(clean) > 2
                and clean[0].isupper()
                and clean.lower() not in NOT_LOCATIONS
                and not clean.isupper()):  # skip acronyms
            return clean

    return ""


def _find_latest_report(
    vault: Path,
    location: str,
    report_type_slug: str,
) -> Path | None:
    """Finds the most recent report note for a location and type."""
    reports_dir = vault / "Reports"
    if not reports_dir.exists():
        return None

    candidates = []
    search_term = _slugify(location).lower() if location else ""

    for p in reports_dir.glob(f"*{report_type_slug}*.md"):
        if not search_term or search_term in p.stem.lower():
            candidates.append(p)

    if not candidates and not search_term:
        # No location specified — return most recent report of this type
        for p in sorted(
            reports_dir.glob(f"*{report_type_slug}*.md"), reverse=True
        )[:1]:
            return p

    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _extract_metrics_from_report(report_path: Path) -> dict:
    """
    Extracts key metrics from a report note.
    Reads YAML frontmatter and content for key numbers.
    """
    metrics: dict[str, Any] = {}
    try:
        text = report_path.read_text(encoding="utf-8", errors="ignore")

        # Parse YAML frontmatter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                fm = text[4:end]
                for line in fm.splitlines():
                    if ":" in line:
                        key, _, val = line.partition(":")
                        metrics[key.strip()] = val.strip().strip('"')

        # Extract numbers from content
        # Irradiance
        m = re.search(
            r"(\d+\.?\d*)\s*kWh/m[²2]/day", text
        )
        if m:
            metrics["irradiance"] = float(m.group(1))

        # Rate
        m = re.search(
            r"(\d+\.?\d*)\s*(?:¢/kWh|cents/kWh|¢ per kWh)", text
        )
        if m:
            metrics["rate_cents_kwh"] = float(m.group(1))

        # Annual solar output
        m = re.search(
            r"(\d[\d,]+)\s*kWh(?:/year|/yr|\s+per\s+year|\s+annual)", 
            text, re.IGNORECASE
        )
        if m:
            metrics["annual_kwh"] = float(m.group(1).replace(",", ""))

        # Viability score
        m = re.search(
            r"(\d+\.?\d*)\s*/\s*100", text
        )
        if m:
            metrics["viability_score"] = float(m.group(1))

        # Population density
        m = re.search(
            r"(\d[\d,]+)\s*(?:per sq mi|/sq mi|per square mile)",
            text, re.IGNORECASE
        )
        if m:
            metrics["density"] = float(m.group(1).replace(",", ""))

    except Exception as exc:
        LOGGER.warning("Failed to extract metrics from %s: %s",
                       report_path, exc)

    return metrics


def _save_insight(vault: Path, slug: str, content: str) -> None:
    """Saves an inline analysis result to Insights/ folder."""
    try:
        from datetime import date
        insights_dir = vault / "Insights"
        insights_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{date.today().isoformat()}_{slug}.md"
        path = insights_dir / filename
        path.write_text(content, encoding="utf-8")
        LOGGER.info("Insight saved to: %s", path)
    except Exception as exc:
        LOGGER.warning("Could not save insight: %s", exc)


def _load_config(filename: str) -> str:
    """Loads a config file. Never raises."""
    path = PROJECT_ROOT / "config" / filename
    if not path.exists():
        return f"[Config missing: {filename}]"
    return path.read_text(encoding="utf-8")


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")