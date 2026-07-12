# Progress Log — Spain BYOP Siting Model

*Session started 2026-07-06. Running log per the brief's self-checkpointing protocol.*

## Research findings

### R1. MITECO zonificación — RESOLVED: downloadable ✅
- The PV environmental sensitivity map ("Zonificación ambiental para energías renovables", 2023 update) is bulk-downloadable as GeoTIFF, NOT just browsable.
- Direct file: `https://www.miteco.gob.es/content/dam/miteco/es/calidad-y-evaluacion-ambiental/temas/evaluacion-ambiental-de-planes-programas-y-proyectos/Zonificacion_FTV_clasificada_2023.zip` (downloading to `data/zonificacion_ftv/`).
- 5 classes: Máxima (not recommended), Muy Alta, Alta, Moderada, Baja. Aimed at utility-scale PV — exactly our use case. Also a continuous "Modelo ISA" raster available.
- Docs: exec summary + technical memoria PDFs on same page.

### R2. Solar resource — RESOLVED: PVGIS API ✅
- PVGIS v5.3 non-interactive API: `https://re.jrc.ec.europa.eu/api/v5_3/PVcalc?lat=..&lon=..&peakpower=1&loss=14&outputformat=json`
- SARAH3 database for Europe. Rate limit 30 calls/s per IP → national grid sampling feasible (~4–5k points in minutes).
- Plan: query E_y (kWh/kWp/yr specific yield) per grid cell. PVcalc already folds in temperature effects.

### R3. Regulatory reception, positive pole — RESOLVED: Aragon PIGA is real & specific ✅
- Aragon uses "Proyecto/Plan de Interés General de Aragón" (PIGA): declaración de interés autonómico → expedited permitting + tax benefits.
- Microsoft "Región MSFT" PIGA initially approved (3 campuses: La Muela, Villamayor de Gállego, Zaragoza; submitted 2025-09-29).
- AWS "Ampliación Región AWS" PIGA: third partial final approval May 2026; AWS planning ~30 DC buildings in Aragon (DCD).
- Local opposition exists even in Aragon (arainfo.org "prosperidad destructiva") — note as nuance.

### R4. Regional reception — RESOLVED enough to build the layer ✅
- **Extremadura = second fast-track pole.** PREMIA ("Proyecto de Interés Empresarial Autonómico") declared for Merlin Edged DC in Navalmoral de la Mata (€1.6B, 250 jobs); twin campus in Valdecaballeros (Badajoz); each up to 1 GW IT, PUE 1.15. Region claims €6B+ DC investment captured in ~1 year (Feb 2026). President Guardiola personally signing protocols.
- **Castilla-La Mancha:** Meta Talavera advancing (key step Dec 2025) but is the national lightning rod for water opposition — peak 120 L/s ≈ half the city's consumption; Meta moved it there after losing status in the Netherlands.
- **National opposition current:** Ecologistas en Acción "burbuja de centros de datos" campaign; MITECO minister Aagesen herself said "data center bubble" in 2025. Opposition exists even in Aragon (arainfo).
- Other CCAA: documented projects at Picassent (Valencia), Arasur/Álava (Basque), A Coruña (Galicia). Remaining regions get scores from posture + project evidence, flagged with confidence levels in the data file.

### R5. Thesis numbers — VERIFIED, stronger than brief ✅
- Node saturation: **83.4% (Sept 2025) → 88.3% (Feb 2026)** of distribution nodes saturated (aelec capacity maps, CNMC Circular 1/2024 forced publication).
- Curtailment: **July 2025 >11% of renewables curtailed, >1,100 GWh in one month**; 2025 total 5,414 GWh — more than annual demand of Extremadura/Navarra/Cantabria/La Rioja. Post-blackout reinforced operation raised system security costs ~97%.

### R6. Catastro — PARTIALLY RESOLVED ⚠️
- Sede Electrónica up; INSPIRE ATOM feeds (per-municipality GML parcels) exist but endpoints (catastro.minhap.es / hacienda) unreachable from this network (curl 000). Decision: catastro = manual top-N deep-dive only, documented approach, not a base layer. Matches brief's instinct.

### R7. Elevation — RESOLVED ✅ Open-Meteo elevation API (Copernicus GLO-90), batch 100 pts/call, works.
### R8. Boundaries — RESOLVED ✅ es-atlas TopoJSON (`cdn.jsdelivr.net/npm/es-atlas`) autonomous regions, 37KB.
### MITECO raster inspected: EPSG:25830, 25m, values 0=Máxima(excluded) 1=MuyAlta 2=Alta 3=Moderada 4=Baja, nodata 65535. Peninsula+Baleares file + separate Canarias file.

## LOCKED PLAN (decided, per brief's "make the calls")
- **Unit of analysis:** 0.1° lat/lon grid (~9×11 km, ~94 km²/cell), ~5,000 land cells over peninsular Spain + Balearics (Canarias deferred). Fine enough for solar/terrain/env variation, coarse enough for full-nation client-side live re-weighting. Cells carry *developable-hectares* so GW-mode aggregates contiguous cells; edge mode uses single cells.
- **Variable shortlist (6):** (1) solar yield PVGIS E_y optimal-tilt; (2) env permitting friction = MITECO ISA class composition per cell (developable fraction = Baja+Moderada share); (3) terrain relief (intra-cell elevation range, 4×4 subgrid); (4) CCAA regulatory reception score (hand-built, cited, confidence-flagged); (5) distance to nearest big city (dual-sign: labor/fiber vs pushback — user controls sign); (6) distance to announced DC clusters (dual-sign: validated corridor vs whitespace land-banking). CUT: gas pipelines (grid-adjacent, off-thesis), substation distance (explicitly out per brief), water as numeric layer (BYOP designs dry-cool; kept as qualitative note), wind resource (PV-only v1), Corine land cover (ISA already embeds land constraints).
- **Scoring:** min-max normalized 0–100 per layer with justified transforms; user weights incl. negative; composite recomputed client-side. Hard gates: developable fraction, relief, ISA Máxima exclusion.
- **Size modes:** 1 GW campus / 100 MW / 10 MW edge — each with land-requirement math (PV oversizing + BESS for target solar-coverage) computed from the cell's own yield; GW mode requires contiguous developable area via client-side clustering.
- **Stack:** static `web/` (Leaflet + canvas overlay + vanilla JS), precomputed `cells.json`. No server, no build step.

## Build state
- venv `.venv`: numpy/pandas/requests/shapely/rasterio/pillow OK.
- `data/zonificacion_ftv/` GeoTIFFs downloaded.
- **Stage 1 done:** `pipeline/build_grid.py` → `data/grid.csv`, 5,289 land cells (0.1°), CCAA-tagged via es-atlas TopoJSON (custom decoder, no geopandas needed).
- **Stage 2 running:** `pipeline/fetch_pvgis.py` → `data/pvgis.csv` (E_y kWh/kWp optimal tilt + elevation), resume-safe, ~57% at last check.
- **Stage 3 PIVOT:** Open-Meteo elevation API hit hourly quota after 1 batch (429 "hourly limit") — abandoned. Replaced with `pipeline/fetch_terrain.py`: AWS Terrain Tiles (s3 elevation-tiles-prod, Terrarium PNG, z9 ≈ 300 m, no key/limit). Relief = p98−p2 of intra-cell elevations. Running.
- **Stage 4 done:** `pipeline/sample_isa.py` → `data/isa.csv`. National means: 33% Máxima, 36% Baja — consistent with MITECO's published stats. 2,020 cells >50% Baja.
- **Stage 5 written:** `pipeline/assemble.py` (join + city/DC distances) → `web/data/cells.json`. Run after stages 2–3 finish.
- **Regulatory layer done:** `web/data/regions.json` — 16 CCAA dossiers, scores, confidence flags, source URLs.
- **Dashboard written:** `web/index.html` + `web/app.js` — Leaflet + custom canvas cell layer, 3 size modes (1 GW / 100 MW / 10 MW edge) with per-cell PV+BESS+land sizing math, live re-weighting (dual-sign sliders for city/DC proximity), hard gates, single-layer choropleth views, top-10 sites (45 km dedupe), click → full dossier panel. Untested until cells.json exists.

## FINAL STATE — v1 COMPLETE ✅ (2026-07-06, single session)
- All 5 pipeline stages ran to completion: 5,289 cells with solar (PVGIS SARAH3), terrain (AWS Terrain Tiles ~300 m, relief = p98−p2), MITECO ISA composition, CCAA, city/DC distances → `web/data/cells.json` (390 KB).
- Dashboard tested in browser (one bug found & fixed: first canvas redraw ran before scores existed → NaN into color ramp → boot died silently). All modes, sliders, gates, single-layer views, click-dossier verified working.
- **Results pass the smell test:** GW mode top-10 = Ebro valley/Zaragoza ×4 (where AWS+MSFT actually went — model wasn't told), Extremadura ×3 (Merlin's two 1 GW sites are there), La Mancha ×2, Lleida ×1. Most interesting non-obvious call: **Albacete/La Mancha plateau #2** (1,665 kWh/kWp, 99% developable, 5 m relief, 79k ha developable in cluster, no announced projects within ~146 km) — a genuine "huh, I hadn't thought about that spot" candidate, and the land-banking answer. Edge mode correctly reorders to 7–27 km from cities; 100 MW mode concentrates the Ebro corridor.
- README.md written (thesis w/ verified numbers, variable table + cuts, methodology, limitations).
- Run: `cd web && python3 -m http.server 8000` (or preview config in `.claude/launch.json`).

## v2 (2026-07-07, session 2 — Marc's feedback round)
Feedback: too abstract → satellite + parcels; use continuous ISA + wind maps; catastro is a big need; be metacritical; costs; wind/rain.
- **Data added:** continuous PV ISA (Modelo_ISA_FTV_2023, values ×1000, 10=least sensitive), wind classified+continuous ISA (EOL zips, same page), NASA POWER 0.5° climatology (WS50M + PRECTOTCORR, 4 regional calls — note: 1 param/request, ≥2° bbox), largest-contiguous-developable-patch per cell (scipy label on 200m mask; meseta is effectively one 2M-ha patch — patch shown as context, not gate). New pipeline: `fetch_power.py`, `sample_isa2.py`; cells.json now 22 fields, 548 KB.
- **Catastro RESOLVED (was ⚠️):** OVC REST works with `CoorX/CoorY` (my earlier probe used wrong param names) AND sends `Access-Control-Allow-Origin: *` → live browser lookup shipped: click → Consulta_RCCOOR (refcat) → Consulta_DNPRC (class RU/UR, luso, surface, cultivos, official mapa.aspx deep link). Catastro WMS (`layers=Catastro`) shipped as parcel-boundary overlay (zoom ≥13). Ownership NAMES are protected — that stays manual (Registro de la Propiedad).
- **SIGPAC:** both public WMS endpoints broken/moved (mapama 500s, fega 404s) — visor deep-link only.
- **Dashboard v2:** satellite basemap toggle (Esri) + Catastro overlay + grid on/off; cells auto-fade at zoom ≥12, hidden ≥15; 4th mode "1 GW hybrid" (55% PV/35% wind/10% backup, BESS 10→7 MWh/MW); capex model (PV .55, wind 1.15 M€/MW, BESS .2 M€/MWh, backup .45, land 12k€/ha) with €/MW-IT map view; 3 new score layers (wind res, wind ISA, rain/soiling — default weight 0 outside hybrid).
- **Verified in browser:** parcel lookup end-to-end (13005A03800072, Rústica/Agrario/14.3 ha), Esri+Catastro WMS tiles 200, hybrid top-3 = Ebro corridor (Cierzo — plausible), solar-only capex 5.9 vs hybrid 6.7 M€/MW-IT (honest: wind buys firmness, not capex, in Spain).
- README: added resolution rationale, buyer use-case/missing-info section, cost assumptions, complementarity of classified vs continuous ISA.

## v3 (2026-07-07, session 3 — ground truth & validation round)
Feedback: map existing solar farms (CV model proposed — declined, see below), map DCs incl. announced/land-bank (datacentermap/baxtel), external-critic pass, keep lean.
- **Solar farms: OSM Overpass instead of training a detector.** `power=plant + plant:source=solar` in ES → 3,215 plants, 706 capacity-tagged, rest estimated from bbox (60% fill, 50 MWp/km²) → ~43.2 GW (vs ~32 GW real utility fleet — bbox overestimate acceptable for screening). Rationale vs CV: OSM Spain solar coverage is substantially complete for utility scale; a tile-scan detector = ~1M Esri tiles download (ToS risk) + training data that... is itself derived from OSM. CV only wins for *recency* (plants < ~1 yr old) — noted as future delta-detection idea.
- **Validation result (the headline):** top-20% scored cells hold ~35% of mapped PV capacity in passing cells (~1.75× concentration). Model tracks revealed preference without being fitted to it; "high score, no PV" residuals = land-bank candidates. Live scatter panel in sidebar.
- **Crops-vs-desert question answered with data:** La Mancha cropland ISA 8.9/10, 99% dev; Tabernas 3.7 (18% dev), Monegros 2.5, Bardenas 0.56, Tierra de Campos 0.13 (2% dev!). Spain's "deserts"/steppes are protected habitat (steppe birds — MITECO model weights them heavily); intensive farmland is the LOW-sensitivity substrate. The model preferring cropland is correct behavior, matching where the 43 GW actually went.
- **Datacenters:** datacentermap.com hard-429s all fetches; baxtel loads via JS (no public API; stage taxonomy incl. "Land Bank" confirmed). Shipped: curated 14-site list w/ statuses (operating/construction/announced/land supported) in hand-editable `web/data/datacenters.json` + status-colored markers. OSM DC query (`telecom/building~data_cent`) timed out on 3 Overpass mirrors ×6 retries — `pipeline/fetch_osm.py` re-fetches both queries with mirror rotation; `build_sites.py` auto-merges `data/osm_dc.json` when present.
- **Also:** URL-hash shareable state; existing-PV row in detail panel; cache-busting `?v=3` (browser served stale cached app.js/cells.json after edits — remember to bump).
- New: `pipeline/fetch_osm.py`, `pipeline/build_sites.py`; cells.json field 22 = existing_pv_mw (23 fields).

## v3.1 (2026-07-09, session 4 — file:// fix + browser-session DC harvest)
- **Bug fix:** opening `web/index.html` directly (file://) broke the app — fetch() of local JSON is blocked. Data now ships as script files (`web/data/*.js`, generated by `pipeline/pack_web.py`, loaded via script tags with fetch fallback). The dashboard is now fully standalone: double-click index.html, no server. Cache version bumped to ?v=4 — REMEMBER: bump ?v= AND re-run pack_web.py after any data change.
- **datacentermap.com harvested via Claude-in-Chrome** (WebFetch was 429-blocked; real browser session worked fine). Site has 212 facilities/40 markets in Spain. Read Zaragoza (21), Santander (12), Toledo (4) market pages. Merged 15 new entries → datacenters.json now 28 sites (6 operating / 1 construction / 18 announced / 3 land).
- **Findings that strengthen the thesis:**
  - Ebro corridor beyond AWS/MSFT: Vantage €3.2B (Villanueva), Box2bit Proyecto Ebro €3.4B (Cariñena) + Calatayud 400k m² site (LAND), Green IT/SAMCA €2.6B 300MW (Pedrola), QTS/Blackstone 300MW (Calatorao), ACS €1.2B 150MW (La Puebla de Alfindén), Tillion/Azora (Villamayor), Iridium 18ha acquired (LAND), AWS ×2 new sites. €10B+ announced in one province.
  - **EdgeMode Mora (Toledo): 300MW NATURAL-GAS behind-the-meter campus w/ Bloom Energy fuel cells — BYOP is already happening in Spain, gas-first.** Our model maps the solar variant of the same move.
  - Proyecto Altamira (Stoneshield Capital PE, Villaescusa, Cantabria) — PE land-accumulation behavior already visible.
- To refresh from datacentermap later: browser session (not curl/WebFetch — hard 429), market pages at /spain/<market>/, remaining unread markets incl. Madrid 69, Barcelona 30, Valencia 11, Bilbao 10, Málaga 7.

## v3.2 (2026-07-09, session 4 cont. — full datacentermap harvest + status toggles)
- **Full DCM harvest via in-page JS** (not page text): every market page embeds a GeoJSON `mapdata.dcs` in `__NEXT_DATA__` with exact coords + name/operator/capacitytype. Extractor accumulated results in sessionStorage across navigations; exfiltrated via blob download to ~/Downloads (tool outputs truncate at ~1KB — slices also work).
- **DCM page-view limit hit after ~20 pages** ("Page View Limit Reached" → /research/limited/). Got 13 markets = 157 facilities (Madrid 74, Barcelona 30, Valencia 11, Zaragoza 17, Bilbao 8, Málaga 7, Murcia 3, Sevilla 3, + small). Missing ~25 small-market facilities (alicante, cadiz, palma, granada, guadalajara, lleida, pamplona, badajoz, caceres, ciudad-real, a-coruna, girona, albacete, soria, donostia, merida, oviedo, huesca, menorca, ibiza, mao) — quota presumably resets; rerun the same playbook later.
- Interesting: DCM's map omits markers for projects without exact sites (QTS Calatorao, Box2bit×2, EdgeMode, AWS San Mateo) — exactly the ones our curated list covers with town coords. Complementary by construction.
- `data/dcm_facilities.json` (157 rows) → build_sites.py merges: curated entries keep researched status + adopt DCM exact coords (MATCH dict); rest added as status "operating (unverified)". Madrid/Barcelona aggregate markers removed. **Total now 110 DC sites** (88 operating / 18 announced / 1 construction / 3 land).
- **UI: per-status toggle checkboxes** (operating/construction/announced/land) via L.layerGroup per status. Cache bump ?v=5.
- **Baxtel: BLOCKED on Chrome extension domain permission** ("Navigation to this domain is not allowed"). Marc needs to allow baxtel.com in the Claude Chrome extension's site access settings; then repeat the playbook — likely richer (their taxonomy: Operational/Construction/Planned/Prospective/Expansion/Land Bank/In Doubt/Withdrawn/Decommissioned).

## v3.4 (2026-07-10, session 5 — baxtel lifecycle stages landed)
- **Browser tools stayed domain-blocked for baxtel** (extension allowlist; not prompt injection — the deny predates any page load). Workaround: Marc pasted two snippets in DevTools himself (needed to type `allow pasting` first — Chrome self-XSS guard). Snippet 1: resource URL dump. Snippet 2: API discovery.
- **Discovery result:** baxtel's own `/api/sites/*` is 401 ("not publicly available yet") — left alone. But the map is fed by a **public Mapbox tileset `ericbell.baxtel_sites`** (token embedded in page for all visitors), vector PBF, fields incl. site_name, company_name, primary_stage, region_slug. `pipeline/fetch_baxtel.py` fetches z8 tiles over Spain (~88 tiles, cached in data/baxtel_tiles/), decodes with mapbox-vector-tile, calibrated against known Equinix coords.
- **249 features decoded** (incl. Lisbon/Marseille, filtered): stages operational 133 / planned 69 / construction 35 / landbank 11 / withdrawn 1.
- **Merge order & rules (learned the hard way):** curated (keeps researched status+notes, wide 6km token match) > baxtel (never merges baxtel-vs-baxtel — nearby features are distinct sub-projects, e.g. EdgeMode Vianos/GDC Alcaraz/Alcaraz Expansion within 4 km) > DCM (tight 400m match; gets status upgraded by baxtel). Meta Talavera curated coords were 10 km off (town center vs real campus) — fixed from baxtel.
- **Final: 200 DC sites — 115 operating / 59 announced / 19 construction / 7 land.** Land-bank highlights: **Fotowatio/FRV "Lusitanus" (Extremadura — a solar developer land-banking a DC site = the BYOP thesis as market behavior)**, EdgeMode Vianos (near the model's Albacete whitespace pick), Microsoft Alcalá, AWS Villanueva 2, Box2bit ×2, Iridium PTR. Also surfaced: EdgeMode has ~9 planned "GDC" sites across Castilla-La Mancha/Andalucía; Substrate AI planned at Talavera.
- Committed dd9910b. Refresh later: `fetch_baxtel.py` (tiles re-fetch after clearing cache dir) + `build_sites.py` + `pack_web.py` + bump ?v=.

## v4 (2026-07-12, session 6 — "if I were the expert" round)
Method: role-played each outreach persona (PE principal, developer, gas-BYOP operator, listed operator, government office, journalist) and implemented what they'd demand:
- **LCOE engine** (PE/developer ask): per-cell €/MWh delivered = annualized capex (CRF at editable WACC/years) + O&M + backup-share fuel. New "LCOE" map view (yellow=cheap). Header shows score + LCOE side by side.
- **Editable assumptions panel** (10 params: PV/BESS/wind/backup capex, WACC, years, O&M, gas fuel €/MWh_e, gas capex, land multiplier) — everything recomputes live incl. gates/ranking. Verified: gas 68→95 €/MWh moves benchmark 81→108; WACC 8→12% moves solar LCOE 78→99.
- **Gas-BYOP benchmark per cell** (EdgeMode ask answered quantitatively): at defaults, top Aragón cells show solar 78 vs gas 81 €/MWh — solar wins on the best land, narrowly. The map is now a solar-vs-gas breakeven surface.
- **Regional land prices** (developer ask): per-CCAA secano €/ha ballparks (MAPA Encuesta-style: Extremadura 5k … Madrid 40k), feeding capex/LCOE, scalable via Land×.
- **HV grid optionality** (recruiter instinct + Pepa persona, without betraying the thesis): 1,031 OSM 220/400 kV substations (336 400kV), per-cell distance (field 23), optional dual-sign layer default 0, map overlay toggle.
- **DC benchmark** (Merlin ask): model score shown live in every DC tooltip + Reality Check adds pipeline stat — **operating fleet avg score 61 vs announced/construction/land avg 65: the new build wave is measurably moving toward the model's map.**
- **Municipality names** (government ask): parsed live from Catastro RCCOOR ldt into the site header (e.g. "TORRES DE BARBUES (HUESCA)").
- **Copy site brief** (outreach ask): one-click clipboard prospectus (score, physics, math, LCOE vs gas, parcel context, assumptions) for pasting into cohort emails.
- Bug fixed during verify: stale `COST.` refs after rename to `A` broke showDetail silently (empty panel, no console error surfaced).
- OUTREACH.md written (18-target tiered cohort) — NOT committed yet per Marc's interrupt; sitting in working tree.

## Open items for the week (not blockers)
- Sweep the remaining low-confidence CCAA dossiers (esp. Castilla y León, Andalucía) with the same primary-source treatment as Aragón/Extremadura.
- Catastro parcel deep-dive on top-5 cells (Sede Electrónica manual; INSPIRE ATOM endpoints were unreachable from this network — retry from Spanish IP?).
- Optional: PV+BESS+backup cost curve instead of fixed 90% solar share; Canarias; wind hybrid.
- Show cluster outlines on map in GW mode (currently availability math only).

