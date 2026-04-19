# Verdigris — Energy Intelligence Platform

> *A self-hosted energy intelligence platform that builds a compounding knowledge base from public data. Every market analysis enriches the next one — through an Obsidian knowledge graph, a cached warehouse, and ML clustering across the full portfolio.*

[![MIT License](https://img.shields.io/badge/license-MIT-4ECDC4.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-C9A96E.svg)](https://python.org)
[![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-1A3A3A.svg)](https://streamlit.io)
[![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter-2D5A5A.svg)](https://openrouter.ai)

**Built by [Christian Appia](https://www.linkedin.com/in/christian-appia-824521187/) · Viridian Society**

---

## What it does

Verdigris turns public energy data into deployable market intelligence. Ask it whether a ZIP code, state, or country is worth pursuing for solar — it answers with live data from NASA, EIA, Eurostat, and World Bank, then remembers that answer forever.

The 100th market analysis is dramatically more valuable than the first — because every report enriches the knowledge graph that powers the next one.

**Three things it does that most tools don't:**

- **Finds similar markets automatically** — run K-Means clustering across your entire analyzed portfolio to find markets that look like your best performers, with no additional API calls
- **Answers repeated questions for free** — the Obsidian vault and SQLite warehouse mean most queries cost zero tokens after the first run
- **Explains its reasoning** — every analysis includes plain-English explanations of what the models found and what it means for deployment decisions

---

## Demo

### Main interface
![Verdigris home screen — sidebar with quick analyses, 
vault search, and 39 reports in knowledge base](docs/ui-home.png)

### Live thinking states — ZIP code analysis
![Live pipeline showing ZIP resolution, NASA irradiance fetch, 
EIA rates, PVWatts simulation, and Census 
demographics](docs/thinking_state_Analysis_and_reports.png)

### Market intelligence dashboard — Top 10 opportunity ranking
![Texas market intelligence: viability score, rate, payback, 
solar resource metrics — Top 10 markets by deployment 
opportunity](docs/Top_ten_markets_from_stored_database.png)

### K-Means clustering — Rate vs Irradiance by cluster
![K-Means scatter plot: 26 markets across 5 clusters, 
R²=0.78, showing rate vs irradiance 
distribution](docs/kmeans_scatter_plot.png)

### Plain-English model explanations for non-technical users
![K-Means clustering output for Texas with similar markets 
table and deployment insight in plain 
English](docs/LLM_explanation_for_non_technical_reps.png)

> 🎥 *Loom walkthrough coming soon*

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/christianemmanuelcreates/Verdigris.git
cd verdigris

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
cp .env.example .env
# Edit .env and add your API keys (see API Keys section below)

# 5. Seed the warehouse (one-time, ~2 minutes)
python3 data/seed_warehouse.py

# 6. Seed the demo knowledge base (optional, ~30 minutes, ~$1.50)
python3 DEMO_SEED.py --dry-run   # preview first
python3 DEMO_SEED.py             # run all 32 reports

# 7. Launch
streamlit run app.py
```

Open `http://localhost:8501` — Verdigris starts with a pre-seeded knowledge base of 32 reports across 3 demo narratives.

---

## API Keys

Five data sources power Verdigris. All are free.

| Key | Source | Used for | Required |
|-----|--------|----------|----------|
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) | LLM calls (analyst + writer) | Yes |
| `EIA_API_KEY` | [eia.gov/opendata](https://www.eia.gov/opendata/register.php) | U.S. electricity rates | U.S. markets |
| `NREL_API_KEY` | [developer.nrel.gov](https://developer.nrel.gov/signup) | PVWatts solar simulation | U.S. markets |
| `CENSUS_API_KEY` | [api.census.gov](https://api.census.gov/data/key_signup.html) | Population and density | U.S. markets |
| Eurostat | Public — no key needed | EU electricity rates | Auto |

NASA POWER (solar irradiance) requires no key and works globally.

---

## Demo Narratives

The demo vault ships with 32 pre-generated reports across three workflows:

### Narrative 1 — The Energy Analyst
*Building a market intelligence library from scratch*

```
"Which states have the strongest solar economics right now?"
→ Vault recall: Hawaii 39.79¢/kWh (127% above avg),
  Massachusetts 31.16¢/kWh, Connecticut, California

"What is the payback period for California?"
→ Inline analysis: 4.7yr payback, 16.3% 10-year ROI
  Source: vault data — zero new API calls

"Run a full market analysis for Hawaii"
→ K-Means: Cluster 3 (high-rate premium)
  Similar markets: Australia, Beverly Hills, California
  Regression: Rate explains 77% of viability variance
  LCOE: 6.2¢/kWh vs 30.3¢ grid — solar 79% cheaper
  25yr NPV: $54,128 (8kW system after ITC)
```

### Narrative 2 — The Market Development Manager
*Ranking markets for crew deployment*

```
"Rank all markets we have analyzed"
→ Ranked table: 23 markets, Germany #1 by rate economics,
  Hawaii #1 by opportunity score

"Where is demand growing fastest?"
→ Prophet forecast: Texas +1.2%/yr, Arizona +0.9%/yr,
  California -0.65%/yr (efficiency gains)

"What happens to Arizona viability if rates rise 20%?"
→ Scenario: 52/100 → 61/100, crosses into Strong market tier
```

### Narrative 3 — International Expansion
*Comparing markets across 42 countries*

```
"How does Germany compare to California?"
→ Germany: 41.79¢/kWh (Eurostat live), 2.93 kWh/m²/day
  California: 30.29¢/kWh, 5.44 kWh/m²/day
  Germany wins on rate; California wins on resource

"Which countries have the strongest rate economics?"
→ Germany 41.79¢ · UK 30¢ · Australia 32¢ · Japan 26¢

"Run a solar viability report for the UK"
→ Full pipeline: NASA → Eurostat → analyst → writer → vault
  Saved to Obsidian for future free recall
```

---

## Architecture

Verdigris is built in seven layers. Each layer has a deliberate design rationale.

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit UI — app.py                                       │
│  Chat interface · Plotly dashboards · Popover forms          │
├─────────────────────────────────────────────────────────────┤
│  Memory — memory/search.py · memory/vault.py                 │
│  4-mode intent routing · 3-tier vault retrieval              │
│  Wikilink traversal · 4,000 token budget enforcement         │
├─────────────────────────────────────────────────────────────┤
│  Agent Layer — agent/analyst.py · agent/report.py            │
│  Pydantic-validated findings · Separated analyst/writer      │
│  Tenacity retry · OpenRouter model abstraction               │
├─────────────────────────────────────────────────────────────┤
│  ML Models — models/                                         │
│  K-Means clustering · OLS regression · LCOE analysis         │
│  Prophet demand forecast · Rate trajectory                   │
├─────────────────────────────────────────────────────────────┤
│  Data Connectors — data/                                     │
│  NASA · EIA · NREL · Census · Eurostat · World Bank          │
│  Cache-first · Tenacity retry · 15s timeout                  │
├─────────────────────────────────────────────────────────────┤
│  Warehouse — data/warehouse.py + verdigris_warehouse.db      │
│  50,878 rows pre-seeded · SQLite · SELECT-only validation    │
├─────────────────────────────────────────────────────────────┤
│  Knowledge Graph — Obsidian Vault                            │
│  Markdown reports · YAML frontmatter · Wikilinks             │
│  Human-browsable + machine-queryable                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Architecture Decisions

These are the non-obvious choices in the system design and the reasoning behind each.

### 1. Warehouse-first data access

The warehouse is pre-seeded with 50,878 rows from EIA, World Bank, and Ember Climate before the app runs. This is a **materialized data warehouse** pattern — expensive queries are pre-computed and stored locally so downstream operations run against SQLite instead of remote APIs.

The business reason: multi-user API cost compounds exponentially without a local data layer. A team of five analysts running ten queries each per day would generate 50 API calls daily. With the warehouse, most of those calls hit local SQLite at zero cost.

The analytical reason: a local warehouse enables batch ML operations — K-Means clustering, linear regression, Prophet forecasting — that would be impossible or prohibitively expensive to run against live APIs on every request.

### 2. Cache-first connectors with TTL aligned to data volatility

Every connector checks a local SQLite cache before hitting an external API. Cache lifetime (TTL — Time To Live) is set per-connector based on how often the underlying data actually changes:

- **Eurostat electricity rates** — 6 months (published bi-annually)
- **NASA irradiance** — indefinite (30-year climatological average)
- **EIA current rates** — 24 hours (monthly publication)
- **Census demographics** — 30 days (annual publication)

This isn't just a performance optimization — it's **matching cache lifetime to data volatility.** Fetching Eurostat rates daily would return the same number for 6 months while burning API quota. The cache TTL for each source reflects when that source's data actually changes.

### 3. Obsidian as the memory layer

Reports are stored as Markdown files in an Obsidian vault rather than in a database table. This was a deliberate choice over PostgreSQL, SQLite, or a vector database.

The key property Obsidian provides that a database doesn't: **the knowledge base is simultaneously machine-readable for the AI and human-readable for the analyst.** An energy analyst can open the vault and browse reports like a library — reading, annotating, and connecting notes manually. The AI queries the same files programmatically.

The wikilink graph (`[[California]] · [[Solar Viability]] · [[2026-04]]`) creates edges between reports that enable 2-hop traversal during retrieval. A question about California solar automatically surfaces linked notes about West Coast markets, rate trends, and ITC policy — connections that emerge from structure without explicit programming.

This approach also minimizes token spend. A vector database requires embedding every document and running similarity search on every query. The 3-tier retrieval system (index scan → keyword match → wikilink traversal) answers most questions with zero embedding costs.

### 4. Separated analyst and writer agents

Each report makes two LLM calls: one analyst call that produces a structured findings package, and one writer call that produces prose.

The principle is **cognitive task separation** — analysis and communication are different tasks that benefit from different prompts, temperatures, and context. Combining them into a single long prompt produces worse output on both dimensions.

The engineering benefit is a **testable contract boundary** enforced by Pydantic. The analyst always returns a validated `AnalystFindings` object. If report quality drops, you can isolate whether the fault is in the analyst JSON or the writer prose. This also enables **incremental prompt improvement** — the analyst and writer prompts can be tuned independently.

### 5. Pydantic validation on analyst output

LLMs are probabilistic — they sometimes return malformed JSON, add unexpected fields, or drop required ones. Without validation, a malformed analyst response propagates silently into the writer, producing a corrupted report.

Pydantic enforces the schema at the boundary, introducing **determinism at the contract boundary** of a probabilistic pipeline. If validation fails, the system catches it before the writer call, logs the specific field error, and retries. The schema also acts as living documentation — `AnalystFindings` describes exactly what the analyst is expected to produce.

### 6. Shared normalized feature matrix for ML models

All four ML models operate on the same normalized feature matrix. Normalization maps every feature to a 0–1 scale before any model sees it.

This solves a **scale invariance problem** specific to solar market data. Population density ranges from 12/sq mi (rural Nevada) to 8,000+/sq mi (Manhattan). Electricity rate ranges from 8¢ to 42¢/kWh. Without normalization, K-Means would cluster markets by density almost exclusively — not because density is the most important feature, but because it has the largest absolute values.

A normalized matrix gives every feature proportional influence based on its relative range. The shared matrix also means adding a fifth model costs almost nothing — it receives the same input the other four already compute.

### 7. Prophet for demand forecasting

Prophet was chosen over a simpler linear trend model because electricity demand is not linear.

Energy demand has **weekly seasonality** (industrial loads drop on weekends), **annual seasonality** (air conditioning in summer, heating in winter), and **structural breaks** (a major employer closes, COVID lockdowns, a grid transition). Linear regression finds the best straight line through historical data and extends it — which systematically misestimates demand at seasonal peaks and after structural changes.

Prophet decomposes the time series into trend, seasonality, and holiday components, then models each independently. For Texas, where summer heat dome demand spikes significantly above the annual average, a linear trend would produce misleading forecasts.

### 8. OpenRouter for model abstraction

Verdigris routes all LLM calls through OpenRouter rather than calling Anthropic, Google, or OpenAI directly. Think of it like choosing where to buy fuel — you can switch between providers based on price and quality without changing your engine.

If Anthropic raises prices, one line in `.env` switches the analyst to DeepSeek or Gemini. If a new model outperforms Claude on structured JSON extraction, the switch takes seconds. The system is **decoupled from any specific model provider** — the model is a configuration variable, not a hard dependency. This is the same principle as programming to an interface rather than an implementation.

---

## Project Structure

```
verdigris/
├── app.py                      ← Streamlit UI entry point
├── cli.py                      ← Terminal interface and system diagnostic
├── DEMO_SEED.py                ← Seeds 32-report demo vault
├── ROADMAP.md                  ← Build history and current status
├── test_suite.py               ← Pre-push test suite (run before committing)
│
├── config/
│   ├── niche.md                ← Market benchmarks and averages
│   ├── regions.md              ← U.S. regions and RTO mapping
│   └── prompts/
│       ├── analyst.md          ← Analyst agent system prompt
│       ├── report.md           ← Writer agent system prompt
│       └── chat.md             ← Chat agent system prompt
│
├── data/
│   ├── db.py                   ← SQLite cache layer
│   ├── warehouse.py            ← Pre-seeded data warehouse
│   ├── seed_warehouse.py       ← One-time warehouse seeder
│   ├── location.py             ← Location resolver (ZIP/state/country)
│   ├── nasa.py                 ← NASA POWER solar irradiance
│   ├── pvwatts.py              ← NREL PVWatts solar simulation
│   ├── eia.py                  ← EIA U.S. electricity rates
│   ├── census.py               ← U.S. Census demographics
│   └── intl_rates.py           ← Eurostat + static international rates
│
├── models/
│   ├── solar_score.py          ← 0–100 viability composite score
│   ├── demand.py               ← Prophet demand forecasting
│   ├── metrics.py              ← Model accuracy explanation
│   └── clustering.py           ← K-Means · regression ·
│                                  LCOE analysis · rate trajectory
│
├── agent/
│   ├── analyst.py              ← Data → Pydantic findings package
│   └── report.py               ← Findings → Markdown report + vault
│
├── memory/
│   ├── vault.py                ← Obsidian vault read/write
│   └── search.py               ← 4-mode chat · 3-tier retrieval
│
└── .streamlit/
    └── config.toml             ← Dark green monospace theme
```

---

## How the Chat Works

The chat interface routes every input through a 4-mode intent classifier:

```
User input
    │
    ├── ZIP code detected?
    │   └── No vault report exists → run full pipeline automatically
    │
    ├── Analysis keywords? (payback, cluster, rank, scenario...)
    │   ├── Payback calculator → vault data + standard assumptions
    │   ├── Rate sensitivity → solar_score with modified inputs
    │   ├── Market ranking → read all vault frontmatter, sort
    │   └── Market intelligence → all 4 ML models on feature matrix
    │
    ├── Escalation keywords? (run a report, solar viability...)
    │   └── analyst.run() → report.write() → vault.write_report()
    │
    └── Default → 3-tier vault retrieval + LLM synthesis
        ├── Tier 1: Index.md scan (always, free)
        ├── Tier 2: Frontmatter keyword match
        └── Tier 3: Wikilink traversal (1 hop)
```

Token budget: 4,000 tokens hard limit on vault context per query.

---

## Roadmap

```
Phase 0  ████████████████████  Complete — project setup
Phase 1  ████████████████████  Complete — data foundation (9 connectors)
Phase 2  ████████████████████  Complete — ML models
Phase 3  ████████████████████  Complete — analyst + writer agents
Phase 4  ████████████████████  Complete — memory system
Phase 5  ████████████████████  Complete — Streamlit UI
Phase 6  ░░░░░░░░░░░░░░░░░░░░  Planned — EDA notebooks
```

**Planned:**
- Rate anomaly detection — flag markets where rates spiked unusually
- Streamlit Cloud deployment with demo mode
- Additional international sources (IEA, IRENA)
- PDF export

---

## Contributing

The most valuable contributions:

- **New data connectors** — add a file to `data/`, follow the cache-first pattern in `nasa.py`
- **New report types** — add a prompt variant to `config/prompts/`
- **New ML models** — add to `models/clustering.py`, they receive the shared feature matrix automatically
- **International rate coverage** — extend `STATIC_RATES` in `data/intl_rates.py`

Please open an issue before submitting a large PR.

---

## Data Sources

| Source | Data | Coverage | Key required |
|--------|------|----------|-------------|
| [NASA POWER](https://power.larc.nasa.gov/) | Solar irradiance | Global | No |
| [EIA](https://www.eia.gov/opendata/) | U.S. electricity rates | 51 states | Yes (free) |
| [NREL PVWatts](https://developer.nrel.gov/docs/solar/pvwatts/) | Solar output simulation | U.S. | Yes (free) |
| [U.S. Census ACS](https://www.census.gov/data/developers.html) | Population, density | U.S. ZIP + state | Yes (free) |
| [Eurostat nrg_pc_204](https://ec.europa.eu/eurostat) | EU electricity rates | 26 EU/EEA countries | No |
| [World Bank](https://data.worldbank.org/) | GDP, population, energy access | 42 countries | No |
| [Ember Climate](https://ember-climate.org/) | Generation mix | 42 countries | No |

---

## License

MIT — see [LICENSE](LICENSE)

---

## Author

**Christian Appia** · Viridian Society

[LinkedIn](https://www.linkedin.com/in/christian-appia-824521187/)

Built with NASA POWER · EIA · Eurostat · World Bank · NREL · Anthropic Claude · Streamlit

---

*Verdigris is named for the blue-green patina that forms on copper over time —
a compound that builds slowly, layer by layer, into something more valuable than what it started as.*