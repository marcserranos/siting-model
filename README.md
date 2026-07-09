# Spain BYOP Datacenter Siting Model

An interactive model that identifies and ranks sites in Spain for **bring-your-own-power datacenters** — behind-the-meter solar + battery + compute, sited to never enter the grid interconnection queue.

![status](https://img.shields.io/badge/status-v1-informational) *Built July 2026.*

## The thesis

Spain has Europe's best solar resource and cheap land — and a grid that can no longer connect new demand to it:

- **88.3% of distribution-network nodes are saturated** (Feb 2026; up from 83.4% in Sept 2025, per the capacity maps distributors were forced to publish under CNMC Circular 1/2024). New large demand connections face multi-year queues.
- At the same time, Spain **curtailed a record >11% of renewable generation in July 2025** (>1,100 GWh in one month) and **5,414 GWh across 2025** — more than the annual electricity demand of Extremadura. Generation and demand potential co-exist without a wire between them.
- The April 2025 Iberian blackout put grid fragility — and grid dependence — on every datacenter developer's risk register.

If interconnection is the bottleneck, the sites worth finding are the ones where a datacenter can be powered **without joining the queue at all**. That is a *demand-siting* problem, not a generation-siting problem: compute doesn't chase the last 5% of irradiance — it needs firm on-site power, buildable land, a permitting path, and a regional government that wants it there. This model ranks every ~94 km² cell of peninsular Spain + the Balearics on exactly that.

It is also a **land-sourcing tool**: large Spanish parcels suited to solar+compute co-location are not yet a contested asset class. The top-sites list is an answer to "where should I be optioning land before anyone else looks."

## What it is

A static, fully client-side dashboard (`web/`) over a precomputed national grid of **5,289 cells at 0.1°** (~9×11 km):

- **Four project scales** — 1 GW solar / 1 GW hybrid (PV+wind) / 100 MW / 10 MW edge — each with its own weight presets, hard gates, and *mechanistic sizing math*: PV MWp, wind MW and battery MWh are sized from each cell's own solar yield and wind speed, converted to hectares, and checked against the cell's (or cell-cluster's) actually-developable land.
- **Live re-weighting** — every variable has a slider (city and DC-cluster proximity accept *negative* weights: remoteness can be the asset); the choropleth, ranking, and detail panels recompute instantly, no rebuild.
- **Hard gates** — max terrain relief, minimum developable share; gated-out cells drawn dark.
- **Parcel drill-down (the anti-abstraction layer)** — satellite basemap toggle, official Catastro parcel boundaries as a WMS overlay, and a live lookup on every click: the exact *referencia catastral*, class (rústica/urbana), declared use (agrario, industrial…), surface, and crop subparcels, straight from the Catastro API, with a deep link to the Sede Electrónica page for that parcel. The grid screens; the click cashes out into a real, legally identified piece of land.
- **Cost model** — screening-grade capex per MW-IT (PV + wind + BESS + backup + land), per cell per mode, viewable as its own map layer. The map answers "where is firm off-grid power cheapest to build," not just "where scores high."
- **Click any cell** — layer contributions, build math, MITECO sensitivity composition (classified stack + continuous PV/wind ISA values), the regional regulatory dossier with sources, nearest announced DC project.
- **Single-layer views** — inspect any input layer as its own choropleth.
- **Ground truth (v3)** — all 3,215 OSM-mapped solar plants (~43 GW) drawn on the map and aggregated per cell as an "existing PV build-out" layer (dual-sign: follow proven zones or hunt whitespace), plus a datacenter layer with status taxonomy (operating / construction / announced / land) from this project's primary-source research — `web/data/datacenters.json` is deliberately hand-editable because datacentermap.com and baxtel.com expose no free API (both rate-limit scrapers; their data is their product).
- **Reality check panel (v3)** — live scatter of model score vs. built PV per cell. Current result: the top-20% scored cells hold ~35% of existing capacity (~1.75× concentration) — the model tracks revealed developer preference without being fitted to it, and the residual "high score, zero PV" cells are the land-banking candidates.
- **Shareable state (v3)** — the full model state (mode, weights, gates, view) lives in the URL hash; copy the link to share an exact scenario.

## The six variables (and what got cut)

| # | Layer | Source | Why it's in |
|---|-------|--------|-------------|
| 1 | Solar specific yield | PVGIS v5.3 / SARAH3, optimal fixed tilt, per cell | Sets the size and cost of the power plant that *is* the datacenter's utility |
| 2 | Environmental permitting friction | MITECO Zonificación Ambiental FTV 2023 (25 m raster, sampled at 200 m) | The state's own map of where utility PV will/won't clear environmental review — the solar field is the permitting-critical footprint |
| 3 | Buildable terrain | AWS Terrain Tiles / Copernicus (~300 m), intra-cell relief p98−p2 | Hundreds of contiguous flat hectares gate both the array and the campus |
| 4 | Regulatory reception | Hand-built per-CCAA dossier from primary sources (confidence-flagged) | The genuinely underpriced variable: Aragón (PIGA) and Extremadura (PREMIA) have *legal instruments* that fast-track exactly this asset |
| 5 | City proximity (dual-sign) | Distance to nearest city ≥100k | Labor/fiber pull vs. social-pushback exposure — direction is a user choice, not an assumption |
| 6 | DC-cluster proximity (dual-sign) | Distance to 12 announced/operating DC sites (researched) | Follow validated corridors, or deliberately buy whitespace |
| 7 | Wind resource | NASA POWER 50 m climatology (0.5° — screening only) | Enables the hybrid mode; wind firms winter/night supply |
| 8 | Wind env. sensitivity | MITECO Zonificación EOL 2023, classified + continuous | Wind permitting is nationally *tighter* than PV (mean ISA 3.9 vs 5.7/10) — a hybrid site needs headroom on both maps |
| 9 | Rain (soiling relief) | NASA POWER annual precipitation | Second-order, default weight 0: rain cleans panels (~1–3% yield in dry areas); cloud losses are already inside PVGIS |

The classified and continuous MITECO products are used for different jobs on purpose: the **5-class map gates** (the classes encode MITECO's own thresholds — the buckets an EIA reviewer will actually use), the **continuous 0–10 ISA ranks** within and across those buckets. They are complements, not resolutions of each other.

**Cut, deliberately:** substation/interconnection distance (off-thesis — the whole point is not queuing), gas pipelines (same), water as a numeric layer (BYOP designs dry-cool; water politics are carried inside the regulatory dossiers — see Talavera), Corine land cover (MITECO's index already embeds land constraints), solar array tiling/GCR optimization (design-phase; doesn't reorder a screening ranking — it's inside the 2 ha/MWp constant), satellite/ML exotica (a simple correct model first).

## The regulatory layer (the differentiated part)

There is no dataset of "which Spanish regions want datacenters." It was built here from primary material and encoded as a score **plus** a dossier that travels with it (`web/data/regions.json`):

- **Aragón 95/100** (high confidence): PIGA declarations — Microsoft's 3-campus "Región MSFT" initially approved; AWS expansion PIGA at third partial final approval (May 2026), ~30 buildings planned.
- **Extremadura 90/100** (high): PREMIA status for Merlin Edged's Navalmoral campus (€1.6 B, up to 1 GW IT) + twin Valdecaballeros site; >€6 B captured in ~a year.
- **Castilla-La Mancha 70/100** (high): Meta Talavera advancing *and* the national water-controversy lightning rod (peak 120 L/s ≈ half the city's consumption) — pre-heated social terrain that a dry-cooled BYOP design partially sidesteps.
- Remaining regions scored from documented projects and posture, each explicitly flagged high/medium/low confidence — uncertainty is preserved, not laundered.

## Run it

```bash
cd web && python3 -m http.server 8000   # then open http://localhost:8000
```

No build step, no server logic, no keys. Rebuild the data from scratch (≈20 min, mostly PVGIS calls):

```bash
python3 -m venv .venv && .venv/bin/pip install numpy pandas requests shapely rasterio pillow
# download MITECO raster (link in PROGRESS.md) into data/zonificacion_ftv/
.venv/bin/python pipeline/build_grid.py
.venv/bin/python pipeline/fetch_pvgis.py      # resume-safe
.venv/bin/python pipeline/fetch_terrain.py
.venv/bin/python pipeline/sample_isa.py
.venv/bin/python pipeline/assemble.py
```

## Sizing & cost assumptions (shown in-app, deliberately simple)

PUE 1.15 · 90% energy from on-site renewables (55/35 PV/wind in hybrid mode; residual = backup/flex) · 2 ha/MWp PV, 5 ha/MW wind · 10 MWh battery per MW load (7 in hybrid). Screening capex: PV 0.55 M€/MWp, wind 1.15 M€/MW, BESS 0.20 M€/MWh, backup 0.45 M€/MW, land 12 k€/ha; the DC building is excluded as site-invariant. A 1 GW-IT campus at a 1,750 kWh/kWp cell ⇒ ~5.2 GWp PV, ~11.5 GWh BESS, ~10,400 ha, **~5.9 M€/MW-IT power capex** — which is why GW mode aggregates neighboring cells and why contiguous developable land is a first-class variable. Not an LCOE (no discounting, opex, or fuel) — it ranks sites, it doesn't price PPAs.

## The resolution question — why not just make the cells smaller?

Three separate ceilings, only one of which is engineering:
1. **Input resolution.** Only MITECO ISA (25 m) and terrain (~300 m) are fine-grained. PVGIS/SARAH3 is ~5 km; NASA POWER is 0.5°; the regulatory layer is regional. Cells much below 0.1° would be resampling noise dressed as precision.
2. **Payload/compute.** 0.02° ⇒ ~130k cells ⇒ ~14 MB JSON and sluggish live re-scoring. Feasible, but it buys false confidence, not information.
3. **Epistemics.** The model's honest claim is "this ~10 km neighborhood is worth sourcing land in." Which *hectares* inside it — that's what the sub-cell evidence is for: the ISA class composition, the largest-contiguous-patch metric, the satellite view, and the live parcel lookup. Screening → cell → parcel is a hierarchy of claims with different confidence, kept visibly separate instead of collapsed into one fake-precise number.

## Why would a land-buyer use this — and what would they still miss?

**Use it for:** turning "Spain is interesting" into a ranked, mechanically-argued shortlist of ~10 km zones with the permitting map, the land math, indicative capex, and the regional political instrument already attached — then clicking down to real *referencias catastrales* to hand to a local gestor. That compresses weeks of scattered GIS work into an afternoon.

**It will not tell you (knowingly):**
- **Who owns the land.** Catastro's public API returns parcel identity, class, use, area — ownership names are legally protected (requires justified interest via Registro de la Propiedad). Assembly risk — how many owners per 1,000 ha — is visible only indirectly through parcel sizes.
- **Municipal urbanism.** A parcel can be rústica and low-sensitivity yet sit in *suelo no urbanizable de especial protección* under the municipal PGOU. That layer lives in ~8,000 municipal plans; it's the top candidate for enrichment on shortlisted zones only.
- **Fiber reality.** Long-haul route data (Reintel, Telxius…) is proprietary; city distance is a proxy, not a route survey.
- **Water for construction and humidification** — small vs cooling but nonzero, and politically loaded (see Talavera dossier).
- **Off-grid engineering risk.** Islanded operation of a GW-class campus (blackstart, frequency stability, N-1 on-site) is assumed solvable at a price, not modeled.
- **Regulatory depth beyond the big three.** Aragón/Extremadura/C-LM dossiers are primary-sourced; the rest are flagged medium/low confidence and should be read as hypotheses.

## Known limitations (v2)

- The 90/10 (or 55/35/10) energy mix is one point on a cost curve; a real design co-optimizes PV/wind/BESS/backup per site. The in-app capex is linear in that choice and labeled screening-grade.
- Wind CF from 0.5° mean speed + a linearized power curve is indicative only; a real site needs Global Wind Atlas microdata or a met campaign. The honest screening result: **hybrid rarely beats solar-only on capex in Spain** — its value is winter/night firmness, which a capex/MW view under-credits.
- Strict off-grid is a modeling stance: most BYOP builds will eventually want a small grid tie (surplus export into a curtailment-priced market, backup import). The bet is that *starting* off-grid re-orders the map — and the data (record curtailment where queues are longest) supports it.
- Canary Islands excluded in v1 (separate raster and grid reality).

## Repo layout

```
pipeline/   5 stages: grid → PVGIS → terrain → MITECO sampling → assemble
data/       intermediate CSVs + MITECO raster (gitignored where heavy)
web/        index.html + app.js + data/{cells,regions}.json — the deliverable
PROGRESS.md research log: what was verified, where, and what's still open
```
