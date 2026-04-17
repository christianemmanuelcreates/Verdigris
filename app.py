"""
Verdigris — Energy Intelligence Platform
app.py — Streamlit UI entry point
"""

import re
import time
import logging
from datetime import date
from pathlib import Path

import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("verdigris")

load_dotenv(Path(__file__).resolve().parent / ".env")

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Verdigris · Energy Intelligence",
    page_icon="🌿",
    initial_sidebar_state="auto",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Sidebar toggle — always visible, high contrast ── */
[data-testid="collapsedControl"] {
    display: block !important;
    visibility: visible !important;
    position: fixed !important;
    top: 50% !important;
    left: 0 !important;
    z-index: 999 !important;
}
[data-testid="collapsedControl"] button {
    background: #4ECDC4 !important;
    border: 2px solid #C9A96E !important;
    color: #0A1F15 !important;
    border-radius: 0 8px 8px 0 !important;
    width: 24px !important;
    min-height: 48px !important;
    padding: 0 !important;
}
[data-testid="collapsedControl"] button:hover {
    background: #C9A96E !important;
    border-color: #4ECDC4 !important;
}
[data-testid="collapsedControl"] svg {
    color: #0A1F15 !important;
    fill: #0A1F15 !important;
}

/* ── Chat avatars — remove orange robot ── */
[data-testid="chatAvatarIcon-assistant"] {
    background: #1A3A3A !important;
    border: 1px solid #4ECDC4 !important;
}
[data-testid="chatAvatarIcon-assistant"] svg {
    color: #4ECDC4 !important;
}
[data-testid="chatAvatarIcon-user"] {
    background: #2D5A5A !important;
    border: 1px solid #C9A96E !important;
}
[data-testid="chatAvatarIcon-user"] svg {
    color: #C9A96E !important;
}

/* ── Badge styles ── */
.badge-vault    { background:#1A3A3A; color:#4ECDC4;
                  border:1px solid #2D5A5A; padding:2px 10px;
                  border-radius:4px; font-size:11px;
                  letter-spacing:.08em; font-family:monospace; }
.badge-report   { background:#1A2A1A; color:#7BC67A;
                  border:1px solid #2D4A2D; padding:2px 10px;
                  border-radius:4px; font-size:11px;
                  letter-spacing:.08em; font-family:monospace; }
.badge-analysis { background:#2A2010; color:#C9A96E;
                  border:1px solid #4A3A20; padding:2px 10px;
                  border-radius:4px; font-size:11px;
                  letter-spacing:.08em; font-family:monospace; }
.badge-escalate { background:#2A1A10; color:#E8A07A;
                  border:1px solid #5A3A20; padding:2px 10px;
                  border-radius:4px; font-size:11px;
                  letter-spacing:.08em; font-family:monospace; }

/* ── Report cards ── */
.report-card { background:#0A1F15; border:1px solid #2D5A5A;
               border-radius:8px; padding:12px 16px;
               margin-bottom:8px; cursor:pointer; }
.report-card:hover { border-color:#4ECDC4; }
.report-title { color:#C9A96E; font-size:13px;
                font-family:monospace; font-weight:bold; }
.report-meta  { color:#4ECDC4; font-size:11px;
                font-family:monospace; opacity:.7; margin-top:2px; }

/* ── Plotly chart backgrounds ── */
.js-plotly-plot .plotly .bg {
    fill: #0A1F15 !important;
}
.stPlotlyChart {
    border: 1px solid #2D5A5A !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    background: #0A1F15 !important;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: #0A1F15 !important;
    border: 1px solid #2D5A5A !important;
    border-radius: 8px !important;
    padding: 12px !important;
}
[data-testid="stMetricLabel"] {
    color: #4ECDC4 !important;
    font-family: monospace !important;
    font-size: 11px !important;
    letter-spacing: .08em !important;
}
[data-testid="stMetricValue"] {
    color: #C9A96E !important;
    font-family: monospace !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: #0A1F15 !important;
    border-right: 1px solid #2D5A5A !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1px solid #2D5A5A !important;
    border-radius: 8px !important;
    background: #0A1F15 !important;
}

[data-testid="stExpandSidebarButton"],
[data-testid="stBaseButton-header"] {
    background: #4ECDC4 !important;
    border: 2px solid #C9A96E !important;
    color: #0A1F15 !important;
    opacity: 1 !important;
    visibility: visible !important;
}
[data-testid="stExpandSidebarButton"] svg,
[data-testid="stBaseButton-header"] svg {
    fill: #0A1F15 !important;
    color: #0A1F15 !important;
}

/* ── Hide Streamlit branding ── */
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "messages":        [],
        "mode":            "home",          # home | report_intake | chat
        "intake_step":     "",              # tracks sub-steps within intake
        "last_input":      "",              # prevents double-processing
        "report_location": "",
        "report_type":     "solar_viability",
        "current_report":  None,
        "market_intel_result": None,
        "vault_filter":    "All",
        "selected_report": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ── Vault helpers ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def get_vault_stats():
    """Counts reports in Obsidian vault. Updates every 30 seconds."""
    try:
        from memory.vault import load_index
        index = load_index()
        count = index.count("[[Reports/")
        return max(count, 0)
    except Exception:
        return 0


@st.cache_data(ttl=30)
def get_vault_reports():
    """Returns list of report metadata from vault Reports/ folder."""
    try:
        import os
        vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
        if not vault_path:
            return []
        reports_dir = Path(vault_path) / "Reports"
        if not reports_dir.exists():
            return []

        reports = []
        for p in sorted(reports_dir.glob("*.md"), reverse=True):
            text = p.read_text(encoding="utf-8", errors="ignore")
            # Parse frontmatter
            location = re.search(r"^location:\s*(.+)$", text, re.MULTILINE)
            rtype    = re.search(r"^report_type:\s*(.+)$", text, re.MULTILINE)
            rdate    = re.search(r"^date:\s*(.+)$", text, re.MULTILINE)
            headline = re.search(r'^headline:\s*"?(.+?)"?$', text, re.MULTILINE)

            reports.append({
                "filename": p.name,
                "path":     str(p),
                "location": location.group(1).strip() if location else p.stem,
                "type":     rtype.group(1).strip() if rtype else "unknown",
                "date":     rdate.group(1).strip() if rdate else "",
                "headline": headline.group(1).strip() if headline else "",
                "content":  text,
            })
        return reports
    except Exception:
        return []


TYPE_LABELS = {
    "solar_viability":   "Solar Viability",
    "rate_roi":          "Rate & ROI",
    "demand_forecast":   "Demand Forecast",
    "executive_summary": "Executive Summary",
    "market_comparison": "Market Comparison",
    "unknown":           "Report",
}

TYPE_COLORS = {
    "solar_viability":   "#4ECDC4",
    "rate_roi":          "#C9A96E",
    "demand_forecast":   "#7BC67A",
    "executive_summary": "#E8A07A",
    "market_comparison": "#9B8EC4",
    "unknown":           "#888",
}

# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    vault_count = get_vault_stats()

    with st.sidebar:
        st.markdown(
            f"<div style='font-family:monospace;font-size:11px;"
            f"color:#4ECDC4;letter-spacing:.12em;margin-bottom:4px;'>"
            f"VIRIDIAN SOCIETY</div>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<div style='font-family:monospace;font-size:10px;"
            f"color:#C9A96E;opacity:.6;margin-bottom:16px;'>"
            f"{vault_count} reports in vault</div>",
            unsafe_allow_html=True
        )

        # Quick analyses
        st.markdown(
            "<div style='font-family:monospace;font-size:10px;"
            "letter-spacing:.15em;color:#4ECDC4;opacity:.7;"
            "margin-bottom:8px;'>QUICK ANALYSES</div>",
            unsafe_allow_html=True
        )

        with st.popover("📈  Payback calculator", 
                        use_container_width=True):
            st.markdown(
                "<div style='font-family:monospace;font-size:11px;"
                "color:#4ECDC4;margin-bottom:8px;'>"
                "PAYBACK CALCULATOR</div>",
                unsafe_allow_html=True
            )
            pb_location = st.text_input(
                "Location", 
                placeholder="California, Hawaii, 90210...",
                key="pb_location"
            )
            if st.button("Calculate", key="pb_run"):
                if pb_location:
                    with st.spinner("Calculating..."):
                        from memory.search import _analysis_payback
                        result = _analysis_payback(pb_location)
                    _add_message("user", 
                        f"Payback analysis for {pb_location}")
                    _add_message("assistant", result, 
                        badge="analysis")
                    st.rerun()

        with st.popover("🎯  Rate sensitivity",
                        use_container_width=True):
            st.markdown(
                "<div style='font-family:monospace;font-size:11px;"
                "color:#4ECDC4;margin-bottom:8px;'>"
                "RATE SENSITIVITY</div>",
                unsafe_allow_html=True
            )
            rs_location = st.text_input(
                "Location",
                placeholder="Texas, Germany, 85001...",
                key="rs_location"
            )
            if st.button("Analyze", key="rs_run"):
                if rs_location:
                    with st.spinner("Running scenarios..."):
                        from memory.search import _analysis_scenario
                        result = _analysis_scenario(
                            rs_location, rs_location.lower()
                        )
                    _add_message("user",
                        f"Rate sensitivity for {rs_location}")
                    _add_message("assistant", result,
                        badge="analysis")
                    st.rerun()

        if st.button("🏆  Market ranking", 
                     use_container_width=True):
            with st.spinner("Ranking markets..."):
                from memory.search import _analysis_market_ranking
                result = _analysis_market_ranking()
            _add_message("assistant", result, badge="analysis")
            st.rerun()

        with st.popover("🔬  Market intelligence",
                        use_container_width=True):
            st.markdown(
                "<div style='font-family:monospace;font-size:11px;"
                "color:#4ECDC4;margin-bottom:8px;'>"
                "MARKET INTELLIGENCE</div>",
                unsafe_allow_html=True
            )
            st.caption(
                "K-Means clustering · Linear regression · "
                "Decision tree · Opportunity scoring"
            )
            mi_location = st.text_input(
                "Location",
                placeholder="Hawaii, California, Texas...",
                key="mi_location"
            )
            if st.button("Run analysis", key="mi_run"):
                if mi_location:
                    with st.spinner("Running 4 models..."):
                        from models.clustering import (
                            run_full_market_analysis
                        )
                        reports = get_vault_reports()
                        result = run_full_market_analysis(
                            mi_location, reports
                        )
                    st.session_state.market_intel_result = result
                    _add_message("user",
                        f"Market intelligence for {mi_location}")
                    st.session_state.mode = "market_intel_view"
                    st.rerun()

        st.markdown("<hr style='border-color:#2D5A5A;margin:16px 0;'>",
                    unsafe_allow_html=True)

        # Vault search + filter
        st.markdown(
            "<div style='font-family:monospace;font-size:10px;"
            "letter-spacing:.15em;color:#4ECDC4;opacity:.7;"
            "margin-bottom:8px;'>VAULT SEARCH</div>",
            unsafe_allow_html=True
        )

        search_query = st.text_input(
            "Search", placeholder="Location or keyword...",
            label_visibility="collapsed"
        )

        all_reports = get_vault_reports()
        type_options = ["All"] + sorted(set(
            TYPE_LABELS.get(r["type"], "Report") for r in all_reports
        ))
        filter_type = st.selectbox(
            "Filter by type", type_options, label_visibility="collapsed"
        )

        # Filter reports
        filtered = all_reports
        if search_query:
            sq = search_query.lower()
            filtered = [r for r in filtered
                        if sq in r["location"].lower()
                        or sq in r["headline"].lower()]
        if filter_type != "All":
            filtered = [r for r in filtered
                        if TYPE_LABELS.get(r["type"], "Report") == filter_type]

        st.markdown(
            f"<div style='font-family:monospace;font-size:10px;"
            f"color:#4ECDC4;opacity:.5;margin:8px 0 6px;'>"
            f"{len(filtered)} report{'s' if len(filtered)!=1 else ''}</div>",
            unsafe_allow_html=True
        )

        for r in filtered[:20]:
            color = TYPE_COLORS.get(r["type"], "#888")
            label = TYPE_LABELS.get(r["type"], "Report")
            if st.button(
                f"**{r['location']}** · {label}",
                key=f"report_{r['filename']}",
                use_container_width=True,
                help=r["headline"][:120] if r["headline"] else ""
            ):
                st.session_state.selected_report = r
                st.rerun()


# ── Message helpers ───────────────────────────────────────────────────────────

def _add_message(role: str, content: str, badge: str = None):
    st.session_state.messages.append({
        "role":    role,
        "content": content,
        "badge":   badge,
    })


def _render_messages():
    for msg in st.session_state.messages:
        role    = msg["role"]
        content = msg["content"]
        badge   = msg.get("badge")

        with st.chat_message(role):
            if badge and role == "assistant":
                badge_labels = {
                    "vault":    "VAULT RECALL",
                    "report":   "FULL REPORT",
                    "analysis": "INLINE ANALYSIS",
                    "escalate": "NEW LOCATION · ESCALATING",
                }
                badge_text = badge_labels.get(badge, badge.upper())
                badge_class = f"badge-{badge}"
                st.markdown(
                    f'<span class="{badge_class}">{badge_text}</span>',
                    unsafe_allow_html=True
                )
            st.markdown(content)


# ── Report pipeline ───────────────────────────────────────────────────────────

def run_full_report(location: str, report_type: str):
    """Runs the full analyst → writer → vault pipeline with live status."""
    from data.location import resolve
    from data.nasa import get_irradiance
    from data.eia import get_rates
    from data.pvwatts import get_output as pvwatts_output
    from data.census import get_demographics
    from data.warehouse import get_country_profile
    from data.intl_rates import get_intl_rate
    from agent.analyst import run
    from agent.report import write

    report_md = None

    LOGGER.info("REPORT ── starting pipeline: %s / %s", location, report_type)
    with st.status(
        f"Analyzing {location}...", expanded=True
    ) as status:
        # Step 1 — Resolve location
        st.write(f"🌍 Resolving location: {location}")
        loc = resolve(location)
        if isinstance(loc, list):
            loc = loc[0]
        if "error" in loc:
            status.update(label="Location not found", state="error")
            return None
        st.write(
            f"   → {loc['name']} "
            f"({'U.S.' if loc.get('is_us') else 'International'})"
        )

        # Step 2 — Live data
        lat, lon = loc.get("lat", 0), loc.get("lon", 0)
        st.write(f"☀️ Fetching NASA solar irradiance ({lat:.2f}°, {lon:.2f}°)...")
        irr = get_irradiance(lat, lon)
        if irr.get("annual_avg_kwh_m2_day"):
            st.write(
                f"   → {irr['annual_avg_kwh_m2_day']} kWh/m²/day "
                f"({irr.get('cache_status','')})"
            )

        if loc.get("is_us"):
            state = loc.get("state_abbr", "")
            st.write(f"⚡ Fetching EIA electricity rates for {state}...")
            rates = get_rates(state)
            if rates.get("residential_cents_kwh"):
                st.write(
                    f"   → {rates['residential_cents_kwh']}¢/kWh residential "
                    f"({rates.get('cache_status','')})"
                )
            st.write(f"🏗️ Running PVWatts solar simulation...")
            pv = pvwatts_output(lat, lon)
            if pv.get("annual_kwh"):
                st.write(
                    f"   → {pv['annual_kwh']:,.0f} kWh/year "
                    f"(4kW system, {pv.get('cache_status','')})"
                )
            fips = loc.get("fips", "")
            if fips:
                st.write(f"👥 Fetching Census demographics (FIPS {fips})...")
                demo = get_demographics(fips)
                if demo.get("population"):
                    st.write(
                        f"   → {demo['population']:,} population, "
                        f"{demo.get('density_per_sq_mi',0):.0f}/sq mi"
                    )
        else:
            iso2 = loc.get("country", "")
            iso3 = loc.get("iso3", "")
            st.write(f"🌐 Loading warehouse profile for {loc['name']}...")
            profile = get_country_profile(iso2, iso3)
            if profile.get("renewables_pct"):
                st.write(
                    f"   → {profile['renewables_pct']}% renewables "
                    f"({profile.get('generation_year','')})"
                )
            st.write(f"💡 Fetching electricity rates...")
            rate = get_intl_rate(iso2)
            if rate.get("rate_cents_kwh"):
                st.write(
                    f"   → {rate['rate_cents_kwh']}¢/kWh "
                    f"({rate.get('method','')})"
                )

        # Step 3 — Models + analyst LLM
        st.write(f"🤖 Analyst reasoning ({report_type.replace('_',' ')})...")
        findings = run(location, report_type)
        if "error" in findings:
            status.update(
                label=f"Analysis failed: {findings['error'][:60]}",
                state="error"
            )
            return None
        st.write(f"   → {len(findings.get('findings',[]))} findings produced")

        # Step 4 — Writer LLM
        st.write(f"✍️ Writing report...")
        report_md = write(findings, report_type)
        word_count = len(report_md.split())
        st.write(f"   → {word_count} words")

        # Step 5 — Vault
        st.write(f"💾 Saving to Obsidian vault...")
        st.write(f"   → Reports/{date.today().isoformat()}_{location.lower().replace(' ','_')}_{report_type.replace('_','-')}.md")

        status.update(
            label=f"Report complete — {loc['name']}",
            state="complete",
            expanded=False
        )

    # Clear cache so vault count updates
    get_vault_stats.clear()
    get_vault_reports.clear()

    return report_md, findings.get("headline", "")


# ── Home screen ───────────────────────────────────────────────────────────────

def render_home():
    """Opening message with three action buttons."""
    if not st.session_state.messages:
        LOGGER.info("RENDER ── mode: %s", st.session_state.mode)
        vault_count = get_vault_stats()
        _add_message("assistant",
            f"Hello. I'm **Verdigris** — an energy intelligence platform "
            f"built on public data from NASA, EIA, Eurostat, and World Bank.\n\n"
            f"I have **{vault_count} reports** in my knowledge base. "
            f"What would you like to do?",
        )

    _render_messages()

    # Three action buttons
    if st.session_state.mode == "home":
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📋  Run a report", use_container_width=True):
                _add_message("assistant",
                    "Which location would you like to analyze?\n\n"
                    "_Enter a U.S. state, city, ZIP code, or country name._",
                    badge="report"
                )
                st.session_state.mode = "report_location"
                st.rerun()
        with col2:
            if st.button("💬  Ask a question", use_container_width=True):
                _add_message("assistant",
                    "Ask me anything about energy markets, solar economics, "
                    "or reports we've run.\n\n"
                    "_I'll search the knowledge base first — "
                    "API calls only if needed._",
                    badge="vault"
                )
                st.session_state.mode = "chat"
                st.rerun()
        with col3:
            if st.button("🔬  Run analysis", use_container_width=True):
                _add_message("assistant",
                    "Which analysis would you like to run?\n\n"
                    "Use the **Quick Analyses** buttons in the sidebar, or "
                    "describe what you're looking for in the chat.",
                    badge="analysis"
                )
                st.session_state.mode = "chat"
                st.rerun()


# ── Report intake flow ────────────────────────────────────────────────────────

def render_report_intake():
    """Collects location → report type → runs pipeline."""
    _render_messages()

    mode = st.session_state.mode

    if mode == "report_location":
        location = st.chat_input("Enter location (state, city, ZIP, or country)...")
        if location:
            _add_message("user", location)
            st.session_state.report_location = location
            _add_message("assistant",
                f"**{location}** — what type of report would you like?",
                badge="report"
            )
            st.session_state.mode = "report_type"
            st.rerun()

    elif mode == "report_type":
        col1, col2 = st.columns(2)
        with col1:
            if st.button("☀️  Solar Viability", use_container_width=True):
                st.session_state.report_type = "solar_viability"
                st.session_state.mode = "report_running"
                _add_message("user", "Solar Viability Assessment")
                st.rerun()
            if st.button("⚡  Rate & ROI", use_container_width=True):
                st.session_state.report_type = "rate_roi"
                st.session_state.mode = "report_running"
                _add_message("user", "Rate & ROI Analysis")
                st.rerun()
            if st.button("📈  Demand Forecast", use_container_width=True):
                st.session_state.report_type = "demand_forecast"
                st.session_state.mode = "report_running"
                _add_message("user", "Energy Demand Forecast")
                st.rerun()
        with col2:
            if st.button("🌍  Market Comparison", use_container_width=True):
                st.session_state.report_type = "market_comparison"
                st.session_state.mode = "report_running"
                _add_message("user", "Market Comparison")
                st.rerun()
            if st.button("📄  Executive Summary", use_container_width=True):
                st.session_state.report_type = "executive_summary"
                st.session_state.mode = "report_running"
                _add_message("user", "Executive Summary")
                st.rerun()

    elif mode == "report_running":
        location    = st.session_state.report_location
        report_type = st.session_state.report_type
        result      = run_full_report(location, report_type)

        if result:
            report_md, headline = result
            _add_message("assistant",
                f"**{headline}**\n\n---\n\n{report_md}",
                badge="report"
            )
            st.session_state.current_report = report_md
        else:
            _add_message("assistant",
                "Report generation failed. Check your API keys and try again.",
                badge="report"
            )

        st.session_state.mode = "chat"
        st.rerun()


def _render_analysis_intake(analysis_type: str):
    """Collects location input for sidebar analysis buttons,
    runs the analysis, then drops into chat mode."""
    LOGGER.info("ANALYSIS INTAKE ── type: %s", analysis_type)
    _render_messages()

    # Guard against double-firing on rerun
    if st.session_state.get("last_input", "") == \
       st.session_state.get("_intake_processing", ""):
        st.session_state.mode = "chat"
        st.session_state._intake_processing = ""
        st.rerun()
        return

    location = st.chat_input("Enter a location from the vault...")
    if location and location != st.session_state.get("last_input", ""):
        st.session_state.last_input = location
        st.session_state._intake_processing = location
        _add_message("user", location)

        with st.spinner("Running analysis..."):
            if analysis_type == "payback":
                from memory.search import _analysis_payback
                result = _analysis_payback(location)
            elif analysis_type == "scenario":
                from memory.search import _analysis_scenario
                result = _analysis_scenario(location, location.lower())
            elif analysis_type == "market_intel":
                LOGGER.info("MARKET INTEL ── location: %s", location)
                from models.clustering import run_full_market_analysis
                reports = get_vault_reports()
                LOGGER.info("MARKET INTEL ── vault reports loaded: %d", len(reports))
                result = run_full_market_analysis(location, reports)
                LOGGER.info("MARKET INTEL ── result type: %s", type(result))
                if isinstance(result, dict):
                    LOGGER.info("MARKET INTEL ── keys: %s", list(result.keys()))
                    LOGGER.info("MARKET INTEL ── target: %s", result.get("target"))
                    data = result.get("data", {})
                    LOGGER.info("MARKET INTEL ── kmeans: %s", data.get("kmeans") is not None)
                    LOGGER.info("MARKET INTEL ── opportunity scores: %d",
                                len(data.get("opportunity").scores)
                                if data.get("opportunity") else 0)
                else:
                    LOGGER.warning("MARKET INTEL ── result is not dict: %s", result)

                if isinstance(result, dict):
                    target  = result.get("target", {})
                    data    = result.get("data", {})
                    opp     = data.get("opportunity")
                    km      = data.get("kmeans")
                    reg     = data.get("regression")

                    # ── Sales view: metric cards ──────────────────
                    st.markdown(
                        "<div style='font-family:monospace;font-size:11px;"
                        "color:#4ECDC4;letter-spacing:.12em;margin-bottom:8px;'>"
                        f"MARKET INTELLIGENCE — "
                        f"{target.get('name','').upper()}</div>",
                        unsafe_allow_html=True
                    )
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Viability Score",
                              f"{target.get('viability', 0):.0f} / 100")
                    c2.metric("Electricity Rate",
                              f"{target.get('rate', 0):.1f} ¢/kWh")
                    c3.metric("Payback Period",
                              f"{target.get('payback_years', 0):.1f} yrs"
                              if target.get('payback_years') else "—")
                    c4.metric("Solar Resource",
                              f"{target.get('irradiance', 0):.2f} kWh/m²/d")

                    # ── Opportunity bar chart ──────────────────────
                    if opp and opp.scores:
                        top10 = sorted(
                            opp.scores, key=lambda x: -x["opp_score"]
                        )[:10]
                        fig = px.bar(
                            top10,
                            x="opp_score",
                            y="name",
                            orientation="h",
                            color="opp_score",
                            color_continuous_scale=[
                                "#0F2A1E", "#1A3A3A", "#2D5A5A",
                                "#4ECDC4"
                            ],
                            labels={"opp_score": "Opportunity Score",
                                    "name": "Market"},
                            title="Top 10 Markets by Deployment Opportunity",
                        )
                        fig.update_layout(
                            plot_bgcolor="#0F2A1E",
                            paper_bgcolor="#0A1F15",
                            font_color="#C9A96E",
                            font_family="monospace",
                            coloraxis_showscale=False,
                            yaxis={"categoryorder": "total ascending"},
                            margin=dict(l=0, r=0, t=40, b=0),
                            height=360,
                        )
                        fig.update_traces(marker_line_width=0)
                        st.plotly_chart(fig, use_container_width=True)

                    # ── Analyst deep dive expander ─────────────────
                    with st.expander(
                        "🔬  Deep dive: clustering & regression", 
                        expanded=False
                    ):
                        if km and opp:
                            scatter_data = []
                            for i, loc in enumerate(
                                result.get("_fm_locations", [])
                            ):
                                scatter_data.append({
                                    "name":      loc.name,
                                    "irradiance": loc.irradiance,
                                    "rate":      loc.rate_cents_kwh,
                                    "cluster":   f"Cluster {int(km.labels[i])+1}",
                                    "viability": loc.viability_score,
                                })
                            if scatter_data:
                                fig2 = px.scatter(
                                    scatter_data,
                                    x="irradiance",
                                    y="rate",
                                    color="cluster",
                                    size="viability",
                                    hover_name="name",
                                    labels={
                                        "irradiance": "Solar Resource (kWh/m²/day)",
                                        "rate":       "Electricity Rate (¢/kWh)",
                                        "cluster":    "Cluster",
                                    },
                                    title="K-Means: Rate vs Irradiance by Cluster",
                                    color_discrete_sequence=[
                                        "#4ECDC4","#C9A96E","#7BC67A",
                                        "#E8A07A","#9B8EC4"
                                    ],
                                )
                                fig2.update_layout(
                                    plot_bgcolor="#0F2A1E",
                                    paper_bgcolor="#0A1F15",
                                    font_color="#C9A96E",
                                    font_family="monospace",
                                    margin=dict(l=0, r=0, t=40, b=0),
                                    height=400,
                                )
                                st.plotly_chart(fig2, use_container_width=True)

                        if reg:
                            st.markdown(
                                "**R² = {:.2f}** — {}% of viability variance "
                                "explained by portfolio features".format(
                                    reg.r_squared,
                                    int(reg.r_squared * 100)
                                )
                            )

                        st.markdown(result["markdown_report"])

                else:
                    _add_message("assistant", str(result), badge="analysis")
                    st.session_state.mode = "chat"
                    st.session_state._intake_processing = ""
                    st.rerun()
                return   # dashboard already rendered above, stop here
            else:
                result = "Unknown analysis type."
                _add_message("assistant", result, badge="analysis")
                st.session_state.mode = "chat"
                st.session_state._intake_processing = ""
                st.rerun()
                return

        _add_message("assistant", result, badge="analysis")
        st.session_state.mode = "chat"
        st.session_state._intake_processing = ""
        st.rerun()


# ── Chat flow ─────────────────────────────────────────────────────────────────

def render_chat():
    """Conversational Q&A with vault context, inline analysis, and escalation."""
    _render_messages()

    # Show selected report if user clicked one in sidebar
    if st.session_state.selected_report:
        r = st.session_state.selected_report
        label = TYPE_LABELS.get(r["type"], "Report")
        _add_message("assistant",
            f"**{r['location']} — {label}** _{r['date']}_\n\n"
            f"{r['headline']}\n\n---\n\n{r['content']}",
            badge="vault"
        )
        st.session_state.selected_report = None
        st.rerun()

    # Download button for current report
    if st.session_state.current_report:
        st.download_button(
            label="📥 Download last report (.md)",
            data=st.session_state.current_report,
            file_name=f"verdigris_{date.today().isoformat()}.md",
            mime="text/markdown",
        )

    # Chat input
    user_input = st.chat_input("Ask anything, or enter a ZIP code...")
    if user_input and user_input != st.session_state.get("last_input", ""):
        st.session_state.last_input = user_input
        LOGGER.info("CHAT ── input: %s", user_input[:80])
        _add_message("user", user_input)

        # Build history for chat()
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[-12:]
        ]

        # Detect intent and route
        q_lower = user_input.lower()

        # ZIP auto-run
        zip_match = re.search(r'\b(\d{5})\b', user_input)
        from memory.vault import get_vault_path
        vault = get_vault_path()
        existing = []
        if zip_match and vault and (vault / "Reports").exists():
            existing = list(
                (vault / "Reports").glob(f"*{zip_match.group(1)}*")
            )

        if zip_match and not existing:
            _add_message("assistant",
                f"No existing report for ZIP {zip_match.group(1)}. "
                f"Running a fresh solar viability analysis...",
                badge="escalate"
            )
            st.session_state.report_location = zip_match.group(1)
            st.session_state.report_type = "solar_viability"
            st.session_state.mode = "report_running"
            st.rerun()

        else:
            with st.spinner(""):
                from memory.search import chat as vault_chat
                response = vault_chat(user_input, history)

            # Classify badge
            badge = "vault"
            if any(k in q_lower for k in
                   {"run a report", "generate", "solar viability",
                    "demand forecast", "rate roi", "executive summary"}):
                badge = "report"
            elif any(k in q_lower for k in
                     {"payback", "roi", "scenario", "rank", "ranking",
                      "sensitivity", "forecast", "predict",
                      "similar markets", "market analysis", "cluster",
                      "opportunity", "deploy", "decision tree",
                      "regression", "go no-go", "where else",
                      "comparable", "markets like", "what drives"}):
                badge = "analysis"

            _add_message("assistant", response, badge=badge)
            st.rerun()


# ── Vault report viewer ───────────────────────────────────────────────────────

def render_report_viewer():
    """Full-width report viewer when user clicks a vault report."""
    r = st.session_state.selected_report
    if not r:
        return

    label = TYPE_LABELS.get(r["type"], "Report")
    col1, col2 = st.columns([6, 1])
    with col1:
        st.markdown(
            f"<div style='font-family:monospace;font-size:12px;"
            f"color:#4ECDC4;margin-bottom:8px;'>"
            f"{r['location'].upper()} · {label.upper()} · {r['date']}</div>",
            unsafe_allow_html=True
        )
    with col2:
        if st.button("✕ Close"):
            st.session_state.selected_report = None
            st.rerun()

    st.download_button(
        "📥 Download (.md)",
        data=r["content"],
        file_name=r["filename"],
        mime="text/markdown",
    )
    st.markdown("---")
    st.markdown(r["content"])


def _render_market_intel_dashboard():
    """Renders the full market intelligence dashboard 
    from stored session state result."""
    result = st.session_state.get("market_intel_result")
    
    if not result or not isinstance(result, dict):
        st.session_state.mode = "chat"
        st.rerun()
        return

    target = result.get("target") or {}
    if not target or not target.get("name"):
        st.session_state.mode = "chat"
        st.rerun()
        return

    data   = result.get("data", {})
    opp    = data.get("opportunity")
    km     = data.get("kmeans")
    reg    = data.get("regression")

    # Back button
    if st.button("← Back to chat"):
        st.session_state.mode = "chat"
        st.rerun()

    st.markdown(
        "<div style='font-family:monospace;font-size:13px;"
        "color:#4ECDC4;letter-spacing:.12em;margin-bottom:16px;'>"
        f"MARKET INTELLIGENCE — "
        f"{target.get('name','').upper()}</div>",
        unsafe_allow_html=True
    )

    # Metric cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Viability Score",
              f"{target.get('viability', 0):.0f} / 100")
    c2.metric("Electricity Rate",
              f"{target.get('rate', 0):.1f} ¢/kWh")
    c3.metric("Payback Period",
              f"{target.get('payback_years', 0):.1f} yrs"
              if target.get('payback_years') else "—")
    c4.metric("Solar Resource",
              f"{target.get('irradiance', 0):.2f} kWh/m²/d")

    st.markdown("---")

    # Opportunity bar chart
    if opp and opp.scores:
        top10 = sorted(
            opp.scores, key=lambda x: -x["opp_score"]
        )[:10]
        fig = px.bar(
            top10,
            x="opp_score",
            y="name",
            orientation="h",
            color="opp_score",
            color_continuous_scale=[
                "#0F2A1E", "#1A3A3A", "#2D5A5A", "#4ECDC4"
            ],
            labels={"opp_score": "Opportunity Score",
                    "name": "Market"},
            title="Top 10 Markets by Deployment Opportunity",
        )
        fig.update_layout(
            plot_bgcolor="#0F2A1E",
            paper_bgcolor="#0A1F15",
            font_color="#C9A96E",
            font_family="monospace",
            coloraxis_showscale=False,
            yaxis={"categoryorder": "total ascending"},
            margin=dict(l=0, r=0, t=40, b=0),
            height=360,
        )
        fig.update_traces(marker_line_width=0)
        st.plotly_chart(fig, width='stretch')

    # Scatter plot
    with st.expander(
        "🔬  Deep dive: K-Means clusters", expanded=True
    ):
        if km and result.get("_fm_locations"):
            scatter_data = []
            for i, loc in enumerate(result["_fm_locations"]):
                scatter_data.append({
                    "name":       loc.name,
                    "irradiance": loc.irradiance,
                    "rate":       loc.rate_cents_kwh,
                    "cluster":    f"Cluster {int(km.labels[i])+1}",
                    "viability":  loc.viability_score,
                })
            fig2 = px.scatter(
                scatter_data,
                x="irradiance",
                y="rate",
                color="cluster",
                size="viability",
                hover_name="name",
                labels={
                    "irradiance": "Solar Resource (kWh/m²/day)",
                    "rate":       "Electricity Rate (¢/kWh)",
                    "cluster":    "Cluster",
                },
                title="K-Means: Rate vs Irradiance by Cluster",
                color_discrete_sequence=[
                    "#4ECDC4","#C9A96E","#7BC67A",
                    "#E8A07A","#9B8EC4"
                ],
            )
            fig2.update_layout(
                plot_bgcolor="#0F2A1E",
                paper_bgcolor="#0A1F15",
                font_color="#C9A96E",
                font_family="monospace",
                margin=dict(l=0, r=0, t=40, b=0),
                height=400,
            )
            st.plotly_chart(fig2, width='stretch')

        if reg:
            st.markdown(
                f"**R² = {reg.r_squared:.2f}** — "
                f"{int(reg.r_squared * 100)}% of viability "
                f"variance explained by portfolio features"
            )

        st.markdown(result["markdown_report"])

    # Download
    st.download_button(
        "📥 Download analysis (.md)",
        data=result["markdown_report"],
        file_name=f"verdigris_intel_{target.get('name','market').lower().replace(' ','_')}.md",
        mime="text/markdown",
    )


# ── Main router ───────────────────────────────────────────────────────────────

def main():
    # Sidebar toggle — fixed position, always visible
    st.markdown(
        """<style>
        div[data-testid="stHorizontalBlock"] 
            button[kind="secondary"]:has(p:contains("☰")) {
            position: fixed;
            left: 12px;
            top: 12px;
            z-index: 9999;
            background: #4ECDC4 !important;
            color: #0A1F15 !important;
            border: 2px solid #C9A96E !important;
            border-radius: 6px !important;
            font-size: 18px !important;
            width: 40px !important;
            height: 40px !important;
            padding: 0 !important;
        }
        </style>""",
        unsafe_allow_html=True
    )

    # Header
    col_title, col_badge, col_toggle = st.columns([5, 1, 0.5])
    with col_toggle:
        # Inject JS to click Streamlit's native sidebar toggle
        # data-testid confirmed as stExpandSidebarButton 
        # via DevTools on Streamlit 1.56
        st.markdown(
            """<script>
            window.toggleSidebar = function() {
                const btn = document.querySelector(
                    '[data-testid="stExpandSidebarButton"]'
                );
                if (btn) btn.click();
            }
            </script>""",
            unsafe_allow_html=True
        )
        if st.button("☰", help="Toggle sidebar",
                     key="sidebar_toggle"):
            st.markdown(
                "<script>window.toggleSidebar();</script>",
                unsafe_allow_html=True
            )
    with col_title:
        st.markdown(
            "<h1 style='font-family:monospace;font-size:22px;"
            "color:#4ECDC4;letter-spacing:.08em;margin-bottom:0;'>"
            "VERDIGRIS</h1>"
            "<p style='font-family:monospace;font-size:12px;"
            "color:#C9A96E;opacity:.7;margin-top:2px;letter-spacing:.05em;'>"
            "Energy Intelligence Platform · Viridian Society</p>",
            unsafe_allow_html=True
        )
    with col_badge:
        count = get_vault_stats()
        st.markdown(
            f"<div style='font-family:monospace;font-size:11px;"
            f"color:#4ECDC4;border:1px solid #2D5A5A;"
            f"padding:4px 12px;border-radius:20px;"
            f"text-align:center;margin-top:8px;'>"
            f"{count} vault reports</div>",
            unsafe_allow_html=True
        )

    render_sidebar()

    # If a vault report is selected show viewer overlay
    if st.session_state.selected_report:
        render_report_viewer()
        return

    st.markdown("<hr style='border-color:#2D5A5A;margin:8px 0 16px;'>",
                unsafe_allow_html=True)

    mode = st.session_state.mode

    # Safety: reset stuck intake modes after 30 seconds
    # (handles cases where user navigates away mid-flow)
    import time as _time
    if mode in ("analysis_payback", "analysis_scenario",
                "analysis_market_intel", "report_location",
                "report_type") and \
       not st.session_state.messages:
        st.session_state.mode = "home"
        mode = "home"

    if mode == "home":
        render_home()
    elif mode in ("report_location", "report_type", "report_running"):
        render_report_intake()
    elif mode == "analysis_payback":
        _render_analysis_intake("payback")
    elif mode == "analysis_scenario":
        _render_analysis_intake("scenario")
    elif mode == "analysis_market_intel":
        _render_analysis_intake("market_intel")
    elif mode == "market_intel_view":
        _render_market_intel_dashboard()
    else:
        render_chat()


if __name__ == "__main__":
    main()