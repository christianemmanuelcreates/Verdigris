# Verdigris — Project Roadmap

*Last updated: 2026-04-14. Reflects true build state after session.*

---

## Phase 0 — Cleanup ✓ COMPLETE

- [x] `app.py` wiped — single comment line only
- [x] `data/warehouse.py` created
- [x] `data/seed_warehouse.py` created
- [x] `data/db.py` cleaned

---

## Phase 1 — Data Foundation ✓ COMPLETE

### Step 1 — `data/location.py` ✓ COMPLETE
- [x] File written
- [x] Texas resolves correctly with lat/lon, FIPS, region, ISO RTO
- [x] ZIP 90210 resolves correctly (Beverly Hills, CA)
- [x] Germany resolves correctly with real coordinates (51.16, 10.45)
- [x] CA, TX, FL multi-region resolves correctly
- [x] California → warehouse query returns real consumption data
- [x] Germany → warehouse query returns real Ember solar data
- [x] COUNTRY_CENTROIDS added — all 42 countries have real coordinates

### Step 2 — `data/warehouse.py` ✓ COMPLETE
- [x] Five tables created and seeded
- [x] `query()` SELECT-only validation working
- [x] `get_schema_description()` returns readable text
- [x] `is_seeded()` returns True
- [x] `get_country_profile()` added — replaces ember.py + worldbank.py

### Step 3 — `data/seed_warehouse.py` ✓ COMPLETE

**Final row counts (seeded 2026-04-12):**
```
eia_consumption   2,040 rows
eia_rates        18,360 rows
eia_generation   25,633 rows
wb_country_data   1,260 rows
ember_generation  3,585 rows
Total:           50,878 rows
```

- [x] All five tables seeded with real data
- [x] EIA rates fixed — `losses` not `system_losses`, no `timeframe`
- [x] Ember seeded via CSV download (API endpoint invalid for regions)
- [x] World Bank seeded with retry logic

### Step 4 — `data/nasa.py` ✓ COMPLETE
- [x] File written — no API key required
- [x] California: 5.442 kWh/m²/day ✓
- [x] Berlin: 2.832 kWh/m²/day ✓
- [x] Cache hit confirmed (0.001s)

### Step 5 — `data/pvwatts.py` ✓ COMPLETE
- [x] File written — NREL API key required
- [x] California: 6,592 kWh/year ✓
- [x] Texas (Houston): 5,686 kWh/year ✓
- [x] Cache hit confirmed (0.001s)
- [x] Fixed: `losses` not `system_losses`, `timeframe` removed

### Step 6 — `data/census.py` ✓ COMPLETE
- [x] File written — Census API key required
- [x] California (FIPS 06): 39.2M population, 251.91/sq mi ✓
- [x] ZIP 90210: 19,652 population, $190K median income ✓
- [x] SSL fix applied (certifi)

### Step 7 — `data/eia.py` ✓ COMPLETE
- [x] File written — EIA API key required
- [x] California: 30.29 ¢/kWh, +73.58% vs national ✓
- [x] Texas: 15.69 ¢/kWh, -10.09% vs national ✓
- [x] Cache hit confirmed (0.000s)

### Step 8 — `data/intl_rates.py` ✓ COMPLETE (new — not in original spec)
- [x] File written — no API key required
- [x] Eurostat nrg_pc_204 for EU/EEA countries (live, bi-annual)
- [x] Static reference table for 30 non-EU countries (verified 2024)
- [x] Germany: 41.79 ¢/kWh from Eurostat 2025-S2 ✓
- [x] France: 27.66 ¢/kWh from Eurostat 2025-S2 ✓
- [x] Ethiopia: 0.3 ¢/kWh (world's cheapest, hydro-based) ✓
- [x] EUROSTAT_BASE_URL added to .env for transparency
- [x] Wired into analyst.py international path

### Step 9 — `warehouse.get_country_profile()` ✓ COMPLETE
- [x] Function added to data/warehouse.py
- [x] Germany: renewables 58.64%, solar 14.95%, pop 83.5M ✓
- [x] India: renewables 19.81%, solar 7.03%, pop 1.45B ✓

### Phase 1 Integration Tests ✓ COMPLETE
- [x] U.S. full pipeline: location → NASA → EIA → PVWatts → Census
- [x] International full pipeline: location → NASA → warehouse → intl_rates

---

## Phase 2 — Models ✓ COMPLETE

### Step 10 — `models/metrics.py` ✓ COMPLETE
- [x] R² clamped to 0 minimum (negative R² on small holdouts misleading)
- [x] 60.5% improvement over baseline confirmed ✓
- [x] Negative path (below-baseline model) handled correctly ✓

### Step 11 — `models/solar_score.py` ✓ COMPLETE
- [x] California: 66.7 Strong market (rate-driven) ✓
- [x] Texas: 43.0 Marginal market ✓
- [x] Weak market: 13.2 Weak ✓

### Step 12 — `models/demand.py` ✓ COMPLETE
- [x] `prophet>=1.1.5` added to requirements.txt
- [x] California: decreasing -0.65%/year (correct — efficiency + rooftop solar) ✓
- [x] Texas: increasing (correct — population growth) ✓
- [x] Cross-sectional fallback for < 5 years data ✓

### Phase 2 Integration Test ✓ COMPLETE
- [x] solar_score + demand + metrics all run together cleanly

---

## Phase 3 — Agents ✓ COMPLETE

### Step 13 — `agent/analyst.py` ✓ COMPLETE
- [x] File written
- [x] Texas solar viability: 5 findings, benchmark_status live ✓
- [x] Germany solar viability: score 45.5/100 with real Eurostat rate ✓
- [x] U.S. data path: nasa + pvwatts + census + eia ✓
- [x] International data path: nasa + warehouse + intl_rates ✓
- [x] OpenRouter call working (gemini-2.5-pro)
- [x] JSON parser fixed (code fence stripping)
- [x] max_tokens removed — model decides output length

### Step 14 — `agent/report.py` ✓ COMPLETE
- [x] File written
- [x] Florida solar viability: 1,001-word report ✓
- [x] Germany solar viability: 962-word report with Eurostat citation ✓
- [x] Obsidian vault write triggered automatically on every report ✓
- [x] Temperature 0.3 for precise execution ✓

### Phase 3 Pipeline Test ✓ COMPLETE
- [x] Florida full pipeline (analyst → report → vault) ✓
- [x] Germany full pipeline with real Eurostat rate ✓
- [x] Obsidian Reports/ folder populated ✓
- [x] Wikilinks, frontmatter, Index.md all working ✓

---

## Phase 4 — Memory ✓ COMPLETE

### Step 15 — `memory/vault.py` ✓ COMPLETE
- [x] File written
- [x] Voice profile read passes (default string when no vault file)
- [x] Report note written to Obsidian Reports/ ✓
- [x] Locations/{location}.md created/updated ✓
- [x] Index.md updated with new row ✓
- [x] YAML frontmatter + wikilinks in every note ✓

### Step 16 — `memory/search.py` — NEXT
- [x] File written
- [x] Note retrieval returns 4 notes for Florida query
- [x] Chat lists Florida and Germany reports correctly
- [x] Payback analysis: 8.6 years, 16.3% ROI ✓
- [x] Market ranking: Germany 45.5, Florida 41.4 ✓
- [x] Token budget (4,000) enforced ✓
- [x] Scenario keywords updated ✓
- [x] Insights/ folder written automatically ✓
- [x] Vault recall returns ranked analysis from 31 reports
- [x] Prophet demand forecast triggers and runs inline
- [x] Escalation auto-generates new reports for unknown locations
- [x] All four chat modes verified end to end
---

## Phase 5 — UI

### Step 17 — `app.py`
- [ ] Opens at localhost:8501
- [ ] Report type dropdown shows all 5 options
- [ ] Location input accepts free text
- [ ] Run button triggers full pipeline
- [ ] Report renders with Markdown + data table
- [ ] Download button exports valid Markdown
- [ ] Chat tab opens with vault opening message
- [ ] Chat responds to question about a prior report
- [ ] Dark green monospace theme applied correctly

---

## Phase 6 — Notebooks

### Step 18 — `notebooks/01_solar_viability_eda.ipynb`
- [ ] Runs top to bottom without errors
- [ ] Irradiance distribution chart renders
- [ ] Rate vs score correlation chart renders

### Step 19 — `notebooks/02_demand_forecast_eda.ipynb`
- [ ] Runs top to bottom without errors
- [ ] Prophet forecast chart renders
- [ ] Residual analysis chart renders

---

## Key Technical Decisions Log

| Decision | Rationale |
|---|---|
| Warehouse-first architecture | 50,878 rows pre-seeded — most questions answered free |
| Ember via CSV not API | Ember REST endpoint has no valid EU aggregate code |
| `losses` not `system_losses` | PVWatts v8 API parameter name correction |
| R² clamped to 0 | Negative R² on 2-point holdout is misleading |
| No max_tokens on LLM calls | JSON output length is probabilistic — let model decide |
| Eurostat for EU rates | Live bi-annual data, no key needed, 26 countries |
| Static table for non-EU | IEA/national regulator verified rates, 30 countries |
| intl_rates wired to analyst | Germany score: 28→45.5 with real 41.79¢/kWh rate |
| COUNTRY_CENTROIDS in location.py | Germany was resolving to (0,0) — all 42 countries fixed |

---

## Current Status

```
Phase 0  ████████████████████  COMPLETE
Phase 1  ████████████████████  COMPLETE (9 steps + intl_rates bonus)
Phase 2  ████████████████████  COMPLETE (3 steps)
Phase 3  ████████████████████  COMPLETE (2 steps)
Phase 4  ████████████████████  COMPLETE ✓
Phase 5  ░░░░░░░░░░░░░░░░░░░░  0/1 steps
Phase 6  ░░░░░░░░░░░░░░░░░░░░  0/2 steps
```

**Next action:** Write `memory/search.py` — Phase 4, Step 16.