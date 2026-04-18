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
import plotly.graph_objects as go
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
[data-testid="stExpandSidebarButton"] {
    background: #4ECDC4 !important;
    border: 2px solid #C9A96E !important;
    border-radius: 0 6px 6px 0 !important;
    opacity: 1 !important;
    visibility: visible !important;
    width: 28px !important;
    min-height: 40px !important;
}
[data-testid="stExpandSidebarButton"] svg {
    fill: #0A1F15 !important;
    color: #0A1F15 !important;
}
[data-testid="stExpandSidebarButton"]:hover {
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

/* ── Hide Streamlit branding ── */
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "messages":        [],
        "mode":            "home",          # home | report_intake | chat
        "show_help":       False,
        "intake_step":     "",              # tracks sub-steps within intake
        "last_input":      "",              # prevents double-processing
        "report_location": "",
        "report_type":     "solar_viability",
        "current_report":  None,
        "market_intel_result": None,
        "post_report_action": None,
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
        count = st.session_state.get("_vault_count") or get_vault_stats()
        st.markdown(
            f"<div style='font-family:monospace;font-size:11px;"
            f"color:#4ECDC4;letter-spacing:.12em;margin-bottom:4px;'>"
            f"VIRIDIAN SOCIETY</div>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<div style='font-family:monospace;font-size:10px;"
            f"color:#C9A96E;opacity:.6;margin-bottom:16px;'>"
            f"{count} reports in vault</div>",
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
                        width='stretch'):
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
                        width='stretch'):
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
                     width='stretch'):
            with st.spinner("Ranking markets..."):
                from memory.search import _analysis_market_ranking
                result = _analysis_market_ranking()
            _add_message("assistant", result, badge="analysis")
            st.rerun()

        with st.popover("🔬  Market intelligence",
                        width='stretch'):
            st.markdown(
                "<div style='font-family:monospace;font-size:11px;"
                "color:#4ECDC4;margin-bottom:8px;'>"
                "MARKET INTELLIGENCE</div>",
                unsafe_allow_html=True
            )
            st.caption(
                "K-Means clustering · Linear regression · "
                "LCOE analysis · Rate trajectory"
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
                    # If location not in vault, seed it first
                    # then redirect through full report pipeline
                    if (isinstance(result, dict) and
                            not result.get("target")):
                        _add_message("assistant",
                            f"{mi_location} is not in the knowledge "
                            f"base yet. Running a solar viability "
                            f"report first so I can include it in "
                            f"the cluster analysis.",
                            badge="report"
                        )
                        st.session_state.report_location = mi_location
                        st.session_state.report_type = "solar_viability"
                        st.session_state.post_report_action = "market_intel"
                        st.session_state.mode = "report_running"
                        st.rerun()
                    else:
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
                width='stretch',
                help=r["headline"][:120] if r["headline"] else ""
            ):
                st.session_state.selected_report = r
                st.rerun()

        st.markdown("<hr style='border-color:#2D5A5A;margin:16px 0 8px;'>",
                    unsafe_allow_html=True)
        st.markdown(
            "<div style='font-family:monospace;font-size:10px;"
            "letter-spacing:.12em;color:#4ECDC4;opacity:.7;"
            "margin-bottom:8px;'>QUICK REFERENCE</div>",
            unsafe_allow_html=True
        )
        st.markdown(
            """<div style='font-family:monospace;font-size:11px;
            color:#C9A96E;line-height:1.8;'>
            ☀️ Solar Viability — any location<br>
            ⚡ Rate &amp; ROI — any location<br>
            📈 Demand Forecast — U.S. states only<br>
            📄 Executive Summary — any location<br>
            <br>
            💬 Type a ZIP for instant report<br>
            🔍 Ask anything — vault answers free<br>
            <br>
            Press <b>[</b> to open sidebar
            </div>""",
            unsafe_allow_html=True
        )


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
            st.session_state._last_error = findings["error"]
            status.update(
                label="Analysis failed",
                state="error",
                expanded=False
            )
            st.error(findings["error"])
            LOGGER.error("Report failed: %s", findings["error"])
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
        vault_count = st.session_state.get("_vault_count", 0)
        _add_message("assistant",
            f"Hello. I'm **Verdigris** — an energy intelligence platform "
            f"built on public data from NASA, EIA, Eurostat, and World Bank.\n\n"
            f"I have **{vault_count} reports** in my knowledge base. "
            f"What would you like to do?",
        )

    _render_messages()

    # Three action buttons
    if st.session_state.mode == "home":
        col1, col2, col3 = st.columns([2, 2, 1.5])
        with col1:
            if st.button("📋  Run a report", width='stretch'):
                _add_message("assistant",
                    "Which location would you like to analyze?\n\n"
                    "_Enter a U.S. state, city, ZIP code, or country name._",
                    badge="report"
                )
                st.session_state.mode = "report_location"
                st.rerun()
        with col2:
            if st.button("💬  Ask a question", width='stretch'):
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
            if st.button("🔬  Run analysis", width='stretch'):
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
            if st.button("☀️  Solar Viability", width='stretch'):
                st.session_state.report_type = "solar_viability"
                st.session_state.mode = "report_running"
                _add_message("user", "Solar Viability Assessment")
                st.rerun()
            if st.button("⚡  Rate & ROI", width='stretch'):
                st.session_state.report_type = "rate_roi"
                st.session_state.mode = "report_running"
                _add_message("user", "Rate & ROI Analysis")
                st.rerun()
            if st.button("📈  Demand Forecast", width='stretch'):
                st.session_state.report_type = "demand_forecast"
                st.session_state.mode = "report_running"
                _add_message("user", "Energy Demand Forecast")
                _add_message("assistant",
                    "Running demand forecast. Note: this report type "
                    "uses Prophet time series modeling on EIA historical "
                    "consumption data and is available for U.S. states only. "
                    "For cities or ZIP codes, Verdigris will automatically "
                    "use the parent state. International locations are not "
                    "supported for demand forecasting.",
                    badge="analysis"
                )
                st.rerun()
        with col2:
            if st.button("🌍  Market Comparison", width='stretch'):
                st.session_state.report_type = "market_comparison"
                st.session_state.mode = "report_running"
                _add_message("user", "Market Comparison")
                st.rerun()
            if st.button("📄  Executive Summary", width='stretch'):
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
            error_msg = st.session_state.get(
                "_last_error",
                "Report generation failed. Check your API keys and try again."
            )
            _add_message("assistant", error_msg, badge="report")
            st.session_state._last_error = ""

        post_action = st.session_state.get(
            "post_report_action"
        )
        st.session_state.post_report_action = None
        if post_action == "market_intel":
            st.session_state.mode = "analysis_market_intel"
        else:
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

                # Auto-seed: if location not in vault,
                # run solar viability first then retry
                if (isinstance(result, dict) and
                        not result.get("target")):
                    _add_message("assistant",
                        f"{location} is not in the knowledge "
                        f"base yet. Running a solar viability "
                        f"report first so I can include it in "
                        f"the cluster analysis.",
                        badge="report"
                    )
                    st.session_state.report_location = location
                    st.session_state.report_type = "solar_viability"
                    st.session_state.post_report_action = "market_intel"
                    st.session_state.mode = "report_running"
                    st.rerun()
                    return
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
                        st.plotly_chart(fig, width='stretch')

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
                                st.plotly_chart(fig2, width='stretch')

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
    lcoe   = data.get("lcoe")
    traj   = data.get("rate_trajectory")
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
    c3.metric("Payback (PVWatts)",
              f"{target.get('payback_years', 0):.1f} yrs"
              if target.get('payback_years') else "—",
              help="Location-specific estimate from NREL PVWatts simulation")
    c4.metric("Solar Resource",
              f"{target.get('irradiance', 0):.2f} kWh/m²/d")

    st.markdown("---")

    # LCOE comparison table
    if lcoe and lcoe.rows_res:
        import pandas as pd

        st.markdown(
            "<div style='font-family:monospace;font-size:11px;"
            "color:#4ECDC4;letter-spacing:.12em;margin-bottom:8px;'>"
            "LEVELIZED COST OF ENERGY — SYSTEM COMPARISON"
            "</div>",
            unsafe_allow_html=True
        )

        is_us = target.get("is_us", False)
        grid_rate = target.get("rate", 0)
        lcoe_val  = lcoe.lcoe_cents_kwh
        lcoe_noitc = lcoe.lcoe_cents_kwh_noitc
        spread    = grid_rate - lcoe_val

        # Residential side by side ITC comparison
        st.markdown("**Residential Systems**")
        col_itc, col_noitc = st.columns(2)

        def _build_res_df(rows, use_itc):
            data = []
            for row in rows:
                net  = row["net_cost"] if use_itc else row["net_cost_noitc"]
                lc   = row["lcoe"] if use_itc else row["lcoe_noitc"]
                pb   = row["payback_res"] if use_itc else row["payback_noitc"]
                npv  = row["npv_25yr_res"] if use_itc else row["npv_25yr_noitc"]
                data.append({
                    "System":      row["system"].split("(")[0].strip(),
                    "Net Cost":    f"${net:,}",
                    "LCOE":        f"{lc:.1f}¢",
                    "Annual kWh":  f"{row['annual_kwh']:,}",
                    "Annual Save": f"${row['annual_savings_res']:,}",
                    "Payback":     f"{pb}yr",
                    "25yr NPV":    f"${npv:,}",
                })
            return pd.DataFrame(data)

        with col_itc:
            st.caption("With 30% ITC" if is_us else "Standard")
            st.dataframe(
                _build_res_df(lcoe.rows_res, use_itc=True),
                width='stretch',
                hide_index=True,
            )
        with col_noitc:
            st.caption("Without ITC / Post-incentive")
            st.dataframe(
                _build_res_df(lcoe.rows_res, use_itc=False),
                width='stretch',
                hide_index=True,
            )

        # LCOE vs grid verdict
        if spread > 0:
            verdict = (
                f"Solar LCOE **{lcoe_val:.1f}¢** (with ITC) · "
                f"**{lcoe_noitc:.1f}¢** (without ITC) · "
                f"Grid **{grid_rate:.1f}¢** · "
                f"Solar is **{spread:.1f}¢ cheaper** than grid."
            )
        else:
            verdict = (
                f"Solar LCOE {lcoe_val:.1f}¢ (with ITC) · "
                f"{lcoe_noitc:.1f}¢ (without ITC) · "
                f"Grid {grid_rate:.1f}¢ · "
                f"Solar parity when grid exceeds "
                f"{lcoe.break_even_rate:.1f}¢."
            )
        st.markdown(verdict)

        st.caption(
            "📌 LCOE payback is a standardized estimate using "
            "irradiance × efficiency. The PVWatts payback on the "
            "metric card above is location-specific and accounts "
            "for actual roof orientation, shading, and system losses. "
            "Both are valid — LCOE enables cross-market comparison; "
            "PVWatts gives the more accurate single-site figure."
        )

        # Commercial systems
        if lcoe.rows_com:
            st.markdown("**Commercial Systems**")
            st.caption(
                "Commercial rates applied · "
                "Section 48 ITC may apply — consult tax advisor"
            )
            com_data = []
            for row in lcoe.rows_com:
                com_data.append({
                    "System":      row["system"].split("(")[0].strip(),
                    "Gross Cost":  f"${row['gross_cost']:,}",
                    "LCOE":        f"{row['lcoe']:.1f}¢",
                    "Annual kWh":  f"{row['annual_kwh']:,}",
                    "Annual Save": f"${row['annual_savings_primary']:,}",
                    "Payback":     f"{row['payback_primary']}yr",
                    "25yr NPV":    f"${row['npv_25yr_primary']:,}",
                })
            st.dataframe(
                pd.DataFrame(com_data),
                width='stretch',
                hide_index=True,
            )

        # Cumulative savings chart
        st.markdown("**25-Year Cumulative Savings**")
        st.caption(
            "Rising grid rates applied year-by-year · "
            "Residential solid · Commercial dashed"
        )

        capped_cagr = min((traj.cagr / 100) if traj else 0.03, 0.05)
        DEGRADATION = 0.005
        LIFETIME    = 25

        fig_cum = go.Figure()
        colors_res = ["#4ECDC4", "#2D9D9D", "#1A6B6B"]
        colors_com = ["#C9A96E", "#A07840", "#6B4F28"]

        for rows_list, colors, is_res in [
            (lcoe.rows_res, colors_res, True),
            (lcoe.rows_com, colors_com, False),
        ]:
            for idx, row in enumerate(rows_list):
                net        = row["net_cost"]
                annual_kwh = row["annual_kwh"]
                base_rate  = (
                    grid_rate / 100 if is_res
                    else (grid_rate * 0.55) / 100
                )
                cumulative = [-net]
                for yr in range(1, LIFETIME + 1):
                    yr_kwh     = annual_kwh * ((1 - DEGRADATION) ** yr)
                    yr_rate    = base_rate * ((1 + capped_cagr) ** yr)
                    cumulative.append(cumulative[-1] + yr_kwh * yr_rate)

                fig_cum.add_trace(go.Scatter(
                    x=list(range(0, LIFETIME + 1)),
                    y=[round(v) for v in cumulative],
                    mode="lines",
                    name=row["system"].split("(")[0].strip(),
                    line=dict(
                        color=colors[idx % len(colors)],
                        width=2,
                        dash="solid" if is_res else "dash",
                    ),
                ))

        fig_cum.add_hline(
            y=0,
            line_dash="dot",
            line_color="#E8A07A",
            annotation_text="Break-even",
            annotation_position="right",
        )
        fig_cum.update_layout(
            plot_bgcolor="#0F2A1E",
            paper_bgcolor="#0A1F15",
            font_color="#C9A96E",
            font_family="monospace",
            title="Cumulative Net Savings — All Systems (25 Years)",
            xaxis_title="Year",
            yaxis_title="Cumulative Savings ($)",
            legend=dict(
                bgcolor="#0A1F15",
                bordercolor="#2D5A5A",
                borderwidth=1,
            ),
            margin=dict(l=0, r=0, t=40, b=0),
            height=420,
        )
        st.plotly_chart(fig_cum, width='stretch')
        st.markdown("---")

    # Rate trajectory chart
    if traj and traj.historical:
        st.markdown(
            "<div style='font-family:monospace;font-size:11px;"
            "color:#4ECDC4;letter-spacing:.12em;margin-bottom:8px;'>"
            "RATE TRAJECTORY ANALYSIS"
            "</div>",
            unsafe_allow_html=True
        )
        hist_years  = sorted(traj.historical.keys())
        hist_rates  = [traj.historical[y] for y in hist_years]
        hist_com    = [
            traj.historical_com.get(y, traj.historical[y] * 0.65)
            for y in hist_years
        ]
        proj_years  = sorted(traj.projected.keys())
        proj_rates  = [traj.projected[y] for y in proj_years]

        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=hist_years, y=hist_rates,
            mode="lines+markers",
            name="Residential (actual)",
            line=dict(color="#4ECDC4", width=2),
        ))
        fig3.add_trace(go.Scatter(
            x=hist_years, y=hist_com,
            mode="lines+markers",
            name="Commercial (actual)",
            line=dict(color="#C9A96E", width=2),
        ))
        fig3.add_trace(go.Scatter(
            x=proj_years, y=proj_rates,
            mode="lines",
            name=f"Projected ({traj.cagr:.1f}% CAGR)",
            line=dict(color="#4ECDC4", width=2, dash="dash"),
        ))
        if traj.lcoe_reference > 0:
            all_years = hist_years + proj_years
            fig3.add_trace(go.Scatter(
                x=[min(all_years), max(all_years)],
                y=[traj.lcoe_reference, traj.lcoe_reference],
                mode="lines",
                name=f"Solar LCOE ({traj.lcoe_reference:.1f}¢)",
                line=dict(color="#7BC67A", width=1.5, dash="dot"),
            ))
        if traj.crisis_year:
            fig3.add_vline(
                x=traj.crisis_year,
                line_dash="dot",
                line_color="#E8A07A",
                annotation_text="Energy crisis",
                annotation_position="top right",
            )
        fig3.update_layout(
            plot_bgcolor="#0F2A1E",
            paper_bgcolor="#0A1F15",
            font_color="#C9A96E",
            font_family="monospace",
            title="Electricity Rate Trajectory (¢/kWh)",
            xaxis_title="Year",
            yaxis_title="Rate (¢/kWh)",
            legend=dict(
                bgcolor="#0A1F15",
                bordercolor="#2D5A5A",
                borderwidth=1,
            ),
            margin=dict(l=0, r=0, t=40, b=0),
            height=380,
        )
        st.plotly_chart(fig3, width='stretch')
        st.markdown(
            f"*Source: {traj.source} · "
            f"CAGR {traj.cagr:.1f}%/year*"
        )
        st.markdown("---")

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

# ── Main router ───────────────────────────────────────────────────────────────

def main():
    vault_count = get_vault_stats()
    st.session_state._vault_count = vault_count

    # Sidebar toggle — fixed position, always visible
    st.markdown(
        """<style>
        </style>""",
        unsafe_allow_html=True
    )

    # Header
    col_title, col_badge, col_toggle, col_help = st.columns([6, 1.2, 0.4, 0.4])
    with col_title:
        st.markdown(
            "<div style='padding:4px 0 8px 0;'>"
            "<h1 style='font-family:monospace;font-size:24px;"
            "color:#4ECDC4;letter-spacing:.1em;margin-bottom:2px;"
            "font-weight:bold;'>"
            "VERDIGRIS</h1>"
            "<p style='font-family:monospace;font-size:11px;"
            "color:#C9A96E;opacity:.6;margin-top:0;"
            "letter-spacing:.08em;'>"
            "ENERGY INTELLIGENCE PLATFORM · VIRIDIAN SOCIETY"
            "</p></div>",
            unsafe_allow_html=True
        )
    with col_badge:
        count = vault_count
        st.markdown(
            f"<div style='font-family:monospace;font-size:11px;"
            f"color:#4ECDC4;border:1px solid #2D5A5A;"
            f"padding:6px 12px;border-radius:20px;"
            f"text-align:center;margin-top:12px;"
            f"white-space:nowrap;'>"
            f"{count} vault reports</div>",
            unsafe_allow_html=True
        )
    with col_toggle:
        if st.button("☰", key="sidebar_toggle",
                     help="Press [ to toggle sidebar"):
            if "sidebar_open" not in st.session_state:
                st.session_state.sidebar_open = True
            st.session_state.sidebar_open = not st.session_state.sidebar_open
    with col_help:
        if st.button("?", help="User manual", key="help_toggle"):
            st.session_state.show_help = not st.session_state.get(
                "show_help", False
            )

    render_sidebar()

    # If a vault report is selected show viewer overlay
    if st.session_state.selected_report:
        render_report_viewer()
        return

    st.markdown("<hr style='border-color:#2D5A5A;margin:8px 0 16px;'>",
                unsafe_allow_html=True)

    if st.session_state.get("show_help", False):
        st.markdown(
            "<div style='font-family:monospace;font-size:11px;"
            "letter-spacing:.12em;color:#4ECDC4;margin-bottom:12px;'>"
            "USER MANUAL</div>",
            unsafe_allow_html=True
        )

        col_a, col_b = st.columns(2)


        with col_a:
            st.markdown("""
**Report Types**

☀️ **Solar Viability**
Scores a market 0-100 using irradiance, electricity
rate, and population density. Full written report
saved to the knowledge base permanently.
Works for: U.S. states, ZIP codes, and countries.

⚡ **Rate & ROI**
Analyzes electricity rate environment and estimates
payback period for a standard 4kW solar system.
Works for: U.S. states and countries.

📈 **Demand Forecast**
Prophet time series model forecasting electricity
consumption using EIA historical warehouse data.
U.S. states only. Cities, ZIP codes, and
international locations are not supported.

📄 **Executive Summary**
One-page stakeholder brief. Maximum 400 words.
Works for: U.S. states and countries.

🌍 **Market Comparison**
Side-by-side comparison of markets already in
the vault. Use exact names from vault reports.
""")

        with col_b:
            st.markdown("""
**Supported Locations**

| Type | Example | Notes |
|------|---------|-------|
| U.S. state | California, TX | All report types |
| ZIP code | 90210, 77002 | Solar Viability only |
| Country | Germany, Japan | Solar, Rate, Executive |
| City | Not recommended | Use state name instead |

**How the Chat Works**

🔍 **Vault recall** (free, instant)
Answers from existing reports. No API calls.
Try: "Which states have the strongest solar economics?"

⚡ **Inline analysis** (free, vault data only)
Keywords: payback, rank, scenario, cluster,
sensitivity, forecast, similar markets.
Try: "What is the payback period for Hawaii?"

📋 **Full report** (~$0.04 per report)
Keywords: run a report, solar viability,
demand forecast, rate roi, executive summary.
Try: "Run a solar viability report for Oregon"

🔄 **ZIP auto-detection**
Type any valid 5-digit U.S. ZIP code to run
an automatic solar viability report.
Try: "77002"

**Quick Analyses (sidebar)**

📈 Payback calculator — vault location required
🎯 Rate sensitivity — vault location required
🏆 Market ranking — no input needed
🔬 Market intelligence — vault location required

**Cost per action**

| Action | Cost |
|--------|------|
| Vault recall | Free |
| Inline analysis | Free |
| Market intelligence | Free |
| Full report | ~$0.04 |

**Data sources used**
NASA POWER · EIA · NREL PVWatts
U.S. Census · Eurostat · World Bank · Ember Climate
""")

        st.markdown(
            "<hr style='border-color:#2D5A5A;margin:8px 0 16px;'>",
            unsafe_allow_html=True
        )

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