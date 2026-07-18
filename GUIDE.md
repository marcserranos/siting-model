# The Complete Guide to the Spain BYOP Siting Model

*A plain-language, end-to-end walkthrough of everything this project is, where every number comes from, what every acronym means, and why each piece exists. Written so you can read it top to bottom once and then explain the whole thing to anyone.*

Live site: **https://marcserranos.github.io/spain-dc-map/**

---

## How to read this guide

- **Part 0** is the 60-second mental model. If you read nothing else, read that.
- **Parts 1–7** are the siting model (the map, the scores, the money math) — the thing a visitor actually sees.
- **Parts 8–10** are the machinery behind it: the datacenter data, the live news pipeline ("Hermes"), and how it's all hosted.
- **Part 11** is a glossary — every acronym in one place. If a term ever trips you up, jump there.
- **Part 12** is the honest limitations list — the stuff to say *before* someone points it out. This is the most important part for the interview.

Every claim here was read straight out of the code, so when you say it, it's true.

---

## Part 0 — The 60-second mental model

There are really **two systems** bolted together:

**System A — the siting model (static).** A one-time data pipeline (Python, on your Mac) fetched ~12 public datasets, chopped Spain into a grid of ~5,300 squares, and tagged each square with numbers (sunshine, terrain, environmental protection, wind, etc.). All those numbers were baked into one file (`cells.json`). The website loads that file and does *all the scoring live in your browser* — every time you move a slider, your laptop re-scores all 5,300 cells in a few milliseconds. **There is no server doing calculations.** The map is just a very smart spreadsheet with a nice face.

**System B — the live intelligence pipeline (dynamic).** A cheap rented Linux computer in Germany (the "Hermes VM") wakes up once a day, reads Spanish news, uses a cheap AI model (DeepSeek) to pull out facts about new datacenter projects, stores them in a small database, and publishes an updated `dc_live.json` file to GitHub. The website loads *that* file too, and overlays the fresh news onto the map. This is the part that makes the project feel *alive* rather than a one-off screenshot.

```
        SYSTEM A (built once, static)                    SYSTEM B (runs daily, live)
   ┌─────────────────────────────────────┐        ┌────────────────────────────────────┐
   │ ~12 public data sources              │        │  Spanish news RSS feeds            │
   │ (PVGIS, MITECO, NASA, OSM, Catastro, │        │           │                        │
   │  datacentermap, baxtel …)            │        │           ▼                        │
   │           │                          │        │  Hermes VM (Germany)               │
   │           ▼                          │        │   → DeepSeek AI extracts facts     │
   │  Python pipeline on your Mac         │        │   → SQLite knowledge base          │
   │   → grid of 5,289 cells              │        │           │                        │
   │   → cells.json / datacenters.json    │        │           ▼                        │
   └───────────────┬─────────────────────┘        │   dc_live.json ──► GitHub          │
                   │                               └───────────────┬────────────────────┘
                   ▼                                                │
           ┌───────────────────────────────────────────────────────▼──────┐
           │  GitHub Pages (free static hosting)                           │
           │  index.html + app.js load BOTH files and render the map.      │
           │  ALL scoring happens live in the visitor's browser.           │
           └───────────────────────────────────────────────────────────────┘
```

That's the whole thing. Everything below is detail.

---

## Part 1 — The thesis (what the project is actually arguing)

**BYOP = "Bring Your Own Power"** (also called *behind-the-meter*). It means a datacenter that generates its own electricity on-site — here, mostly solar panels + batteries — instead of plugging into the public electricity grid.

**Why this matters in Spain, in three facts:**

1. Spain's electricity grid is **jammed**. As of Feb 2026, **88.3%** of distribution-network connection nodes are saturated — there's a huge queue to plug anything big in, and the wait can be years.
2. At the same time Spain **throws away** enormous amounts of clean power it can't use: **5,414 GWh curtailed in 2025** (curtailment = generation deliberately switched off because the grid can't absorb it). That's more electricity than the entire region of Extremadura uses in a year.
3. So you have cheap sun and wasted generation on one side, and datacenters desperate for power on the other — **with no wire connecting them**. The bet: the smart place to build an AI datacenter in Spain is somewhere you **never touch the grid queue at all** — you build your own solar farm next door.

**The deliberate pivot.** The recruiter's informal suggestion was a *grid-centric* model — score sites by grid-connection quality, distance to gas pipelines, distance to other datacenters, sun. This project deliberately did the opposite: it **excludes** grid-connection quality from the core score (it's available as an optional, off-by-default layer) and scores sites on how good they'd be as *self-powered* sites. The throughline — "the grid is the bottleneck, so find the sites that ignore it" — is what makes the model a sharp argument instead of a pile of variables. That's the story to lead with.

---

## Part 2 — What you actually see on screen

The page has **three columns**:

- **Left panel (controls):** project scale, score weights, hard gates, map-view selector, overlay toggles, an editable assumptions panel, a "reality check" chart, and a ranked list of the top sites.
- **Center (the map):** Spain covered in a grid of colored squares (the model), plus dots for real datacenters, solar farms, and substations.
- **Right panel (detail):** appears when you click a cell or a datacenter. Shows the full dossier for that spot.

Let's go through the left panel top to bottom, because that's the model's "control room."

### 2.1 Project scale (the four modes)

You're not scoring "a datacenter" in the abstract — you're scoring for a **specific size of project**, because a 10 MW edge site and a 1 GW hyperscale campus want completely different land. The four modes:

| Mode | IT load | Power mix | What it represents |
|------|---------|-----------|--------------------|
| **1 GW solar** | 1,000 MW | 90% PV, 10% backup | Hyperscale campus, solar + battery only |
| **1 GW hybrid** | 1,000 MW | 55% PV, 35% wind, 10% backup | Same size, but adds on-site wind |
| **100 MW** | 100 MW | 90% PV, 10% backup | Large single-site campus |
| **10 MW edge** | 10 MW | 90% PV, 10% backup | Small regional/edge site |

- **"IT load"** = the power the computers themselves draw. The *total* campus draw is bigger because of cooling — see PUE in Part 5.
- **"Power mix"** = how the energy is sourced. "10% backup" means 10% of the energy is expected to come from a backup generator (gas engines or fuel cells) for the windless, sunless stretches — solar+battery alone can't hit 99.99% uptime, so there's always a backup slice.
- Switching mode **changes three things at once**: the default weights, the default gates, and all the build/cost math. Each mode also picks different weights on purpose — e.g. for the 10 MW edge mode, "city proximity" flips to a strong *positive* (you *want* to be near labor and fiber), whereas for the 1 GW mode it's negative (you want to be remote, away from pushback).

### 2.2 Score weights (the sliders)

This is the heart of the model. Each row is a **factor** that makes a site better or worse, with a slider from 0–100 (or −100 to +100 for "dual" factors). Higher weight = that factor matters more in the final score. A checkbox turns each factor on/off.

The factors (these map one-to-one to the data layers in Part 3):

1. **Solar yield** — how much electricity a solar panel produces there.
2. **Env. sensitivity (PV)** — how environmentally protected/restricted the land is for solar.
3. **Buildable terrain** — how flat it is (flat = cheap to build).
4. **Regulatory reception** — how welcoming that region's government is.
5. **Wind resource** — how windy (only matters in hybrid mode).
6. **Env. sensitivity (wind)** — environmental restriction for wind specifically.
7. **Rain (soiling relief)** — rain washes dust off panels; a small bonus in dusty regions.
8. **City proximity** *(dual)* — near a city = labor + fiber (good) but also more NIMBY pushback (bad). You choose the sign.
9. **DC cluster proximity** *(dual)* — near existing datacenters = proven corridor (good) or crowded/contested (bad).
10. **Existing PV build-out** *(dual)* — solar already built in that cell = proven zone (good) or you want untouched whitespace (bad).
11. **HV grid optionality** *(dual, off by default)* — distance to a high-voltage substation. The thesis is off-grid, so this is **off** by default; it's there for people who want a "plan B" grid tie or to sell surplus power.

**"Dual" factors** are the clever bit: they can be a *positive* or a *negative* depending on which way you drag the slider. Drag right, "close is good"; drag left (negative), "far is good." This lets one model serve two opposite strategies (follow the herd vs. hunt whitespace) without rebuilding anything.

Each slider has a one-line hint under it explaining exactly what it measures — those hints are pulled straight from the model definitions, so they're accurate.

### 2.3 Hard gates

Weights *rank* cells. **Gates** *disqualify* them outright — a cell that fails a gate gets no score at all (shows up gray on the map). Two gates:

- **Max terrain relief** — reject cells steeper than X meters of elevation range. Default 300 m for the big modes.
- **Min developable share** — reject cells where less than X% of the land is environmentally buildable. Default 35% for the big modes, 5% for edge.

There's also a **hidden gate** in every mode: the cell (or cluster of neighboring cells, for the GW modes) must contain **enough developable land to physically fit the project**. A 1 GW solar campus needs thousands of hectares; a cell that's beautiful on every metric but too small to hold the build gets rejected. This is why the top-sites list changes so much between modes.

### 2.4 Map view selector

Switches what the colored squares *show*:

- **Composite score** — the blended 0–100 score (default). Yellow = best.
- **LCOE €/MWh delivered** — the cost of electricity (see Part 5). Yellow = cheapest.
- **Power capex €/MW IT** — the upfront build cost per megawatt. Yellow = cheapest.
- **…or any single raw layer** (solar yield alone, wind alone, etc.) — to see one variable in isolation.

The color ramp is **viridis** (dark purple → teal → green → yellow), the standard scientific "colorblind-safe" palette. For cost views the scale is flipped so yellow always means "good."

### 2.5 Overlay toggles

Checkboxes that add/remove things on the map:

- **Satellite basemap** — swaps the dark map for real satellite imagery (Esri/Maxar).
- **Catastro parcels** — overlays the actual land-registry parcel boundaries (only when zoomed in ≥13). This is the Spanish cadastre — real legal plot lines.
- **Model grid** — the colored score squares themselves.
- **Existing solar farms** — 3,215 real solar farms from OpenStreetMap (cyan dots, sized by capacity).
- **220/400 kV substations** — 1,031 high-voltage substations (white/gray squares).
- **📐 BYOP footprint to scale** — see 2.5.1 below.
- **Datacenter toggles** — four checkboxes to show/hide operating / construction / announced / land-banked datacenters.
- **📰 News feed** — appears once the live pipeline has published; opens the intelligence feed (Part 9).

### 2.5.1 BYOP footprint to scale (the "how big is this really?" overlay)

Turning this on drops a **draggable, true-to-scale drawing** of the selected project's power plant directly onto the map, over real geography. Drag the amber ✥ handle anywhere — put it over Madrid, over a real solar farm, over your own town — to compare the footprint against things you recognise. It draws three things, all at real geographic size:

- a **blue dashed square** = the total allocated solar land,
- a small **red square in its corner** = the datacenter buildings themselves (usually a speck — that's the point),
- (hybrid mode only) a **green square** = the wind area, drawn separately because it's genuinely dual-use (farming continues under the turbines, so that land isn't "lost").

The tooltip on the handle shows the totals and the land-to-building ratio. It **resizes automatically when you change project scale** (10 MW edge → 1 GW), and it reuses the model's exact sizing formulas, so the drawn area always matches the build-math panel. The headline it makes visceral: a 1 GW solar campus needs ~104 km² (about the size of Barcelona) to power buildings covering ~0.3 km² — a **346:1** ratio — and only ~25% of that land is actual panels; the rest is inter-row spacing, roads and setbacks. (Implemented as an isolated overlay in `app.js` — `footGeom` / `drawFoot` / `toggleFoot` — it does not touch the scoring engine.)

### 2.6 Assumptions panel (editable, live)

A collapsible grid of **number boxes** — every financial assumption in the model, editable on the spot. Change "PV M€/MWp" from 0.55 to 0.60 and *every cost number on the entire page recalculates instantly.* This exists so that when an expert says "your solar capex is too low," you can change it in front of them and show the effect live, instead of arguing. Full list of these in Part 5.

### 2.7 Reality check (the validation chart)

A little scatter plot: each dot is a passing cell, x-axis = its model score, y-axis = how much real solar capacity (from OSM) is already built there. The headline stat below it:

> **Top-20% scored cells hold ~35% of all mapped solar capacity** (a 1.75× concentration).

Translation: the places the model *independently* calls good are the same places developers *already* chose to build solar — **without the model being fitted to that data**. That's the difference between "a model" and "a model that's been validated against reality." It also computes whether the *newer* wave of datacenter projects (announced/construction/land) sits in higher-scoring cells than the old operating fleet — a check on whether the market is moving toward the model's map.

### 2.8 Top sites list

The ten highest-scoring cells, de-duplicated so they're spread out (no two within 45 km). Click one to fly there and open its dossier.

---

## Part 3 — Every data layer: where each number comes from

This is the "where does everything come from" part. The grid is **5,289 cells**, each **0.1° × 0.1°** (about **94 km²**, roughly a 9.7 km square). Each cell is stored as a compact array of 24 numbers. Here's every one, its source, and why it's there.

| # | Field | What it is | Source | Why it's in the model |
|---|-------|-----------|--------|----------------------|
| 0–1 | lat, lon | Cell center coordinates | Computed grid | Positioning |
| 2 | ccaa | Which of Spain's 17 autonomous communities | es-atlas boundaries (TopoJSON) | Links to the regulatory layer + land prices |
| 3 | **pv_yield** | Solar electricity yield, kWh per kWp per year | **PVGIS v5.3** (EU Joint Research Centre), SARAH3 satellite database, 1 kWp panel, optimal fixed tilt, 14% losses | The #1 driver — how much power a panel makes here |
| 4 | elev | Average elevation (m) | PVGIS returns it per point | Context |
| 5 | **relief** | Elevation *range* within the cell (m) | **Copernicus DEM** via AWS Terrain Tiles | Flatness = buildability. This is the terrain gate |
| 6–11 | ISA class fractions | % of the cell in each of 5 environmental-sensitivity classes | **MITECO** Zonificación Ambiental FTV 2023 raster (25 m) | Environmental permitting friction for solar |
| 12–13 | d_city, city_idx | km to nearest city ≥100k, and which one | Built-in city list (44 cities) | Labor/fiber vs. pushback |
| 14–15 | d_dc, dc_idx | km to nearest datacenter project, and which | Built-in DC list | Cluster proximity |
| 16 | **isa_val (PV)** | Continuous environmental sensitivity, 0–10 | **MITECO** *Modelo* ISA FTV raster (continuous version) | Ranks cells *within* a class — finer than the 5 buckets |
| 17 | isa_val (wind) | Same, but for wind | MITECO Modelo ISA EOL raster | Wind permitting is tighter than solar |
| 18 | eol_dev | % of cell developable for wind | MITECO wind classification | Hybrid mode |
| 19 | patch_ha | Largest single contiguous developable patch touching the cell (ha) | Computed from the national MITECO mask | "Can a big campus actually fit in one piece?" |
| 20 | **ws50** | Mean wind speed at 50 m height (m/s) | **NASA POWER** climatology (0.5° grid) | Wind resource for hybrid mode |
| 21 | precip | Annual rainfall (mm/yr) | NASA POWER | Panel-cleaning (soiling) bonus |
| 22 | **existing_pv_mw** | Solar capacity already built in the cell (MW) | **OpenStreetMap** / Overpass (3,215 farms) | Validation + "follow vs. avoid" layer |
| 23 | d_sub_km | km to nearest 220/400 kV substation | **OpenStreetMap** (1,031 substations) | Optional grid-tie optionality |

**The acronyms in that table, unpacked:**

- **PVGIS** — *Photovoltaic Geographical Information System*, the EU's official free solar-yield calculator. **SARAH3** is the satellite-derived solar-radiation database it uses. **kWh/kWp/yr** = kilowatt-hours produced per year, per kilowatt-peak of panel installed — the standard "how good is the sun here" number. Spain ranges roughly 1,250 (rainy north) to 1,800+ (sunny south).
- **DEM** — *Digital Elevation Model*, a map of ground height. **Copernicus** is the EU's Earth-observation program. The tiles use "Terrarium" encoding — height is packed into the red/green/blue of an image and decoded with a formula. "Relief" here isn't the average height, it's the *spread* (98th minus 2nd percentile) inside the cell — a proxy for "is this flat farmland or lumpy hills?"
- **MITECO** — *Ministerio para la Transición Ecológica* (Spain's environment ministry). **ISA** = *Índice de Sensibilidad Ambiental* (environmental sensitivity index). **FTV** = *fotovoltaica* (solar); **EOL** = *eólica* (wind). MITECO publishes both a **classified** version (5 buckets: Máxima / Muy Alta / Alta / Moderada / Baja sensitivity) and a **continuous** version (0–10 score). The model uses **both**: the classes act as gates ("Máxima" = essentially can't build), and the continuous value ranks the ok-to-build cells finely against each other. **"Developable"** here is defined precisely as the fraction of land in the two lowest-sensitivity classes (Baja + Moderada).
- **NASA POWER** — *Prediction Of Worldwide Energy Resources*, NASA's free climate dataset. **WS50M** = wind speed at 50 m. It's a coarse 0.5° grid, so the model is explicit that wind is **screening-grade only** — good enough to say "this region is windy," not good enough to site a turbine.
- **OSM** — *OpenStreetMap*, the free crowd-sourced world map. **Overpass** is its query API. Used for ground-truth solar farms and substations. Where a farm has no capacity tag, capacity is estimated from its area (~50 MWp/km², 60% fill).

**How the grid itself is built** (`build_grid.py`): it decodes Spain's regional boundaries, walks a 0.1° lattice across the bounding box, and keeps only the points that fall on land inside one of the 17 regions (Canary Islands, Ceuta, Melilla, Gibraltar excluded). Each kept point becomes a cell, tagged with its region.

---

## Part 4 — The scoring engine: how a cell gets its number

This all happens **live in your browser**, in the function `computeScores()`. Here's the exact logic, in plain steps, for one cell:

**Step 1 — Gates (pass/fail).** The cell must clear *all* of:
- Valid data covering ≥30% of the cell,
- Terrain relief ≤ your "max relief" gate,
- Developable share (Baja+Moderada fraction) ≥ your "min developable" gate,
- (Hybrid mode only) enough wind to matter.

Fail any → score = −1 → drawn gray. Done.

**Step 2 — Land-fit gate.** Compute how much land the project needs (Part 5). For the 1 GW modes, add up the developable hectares in this cell *and its 8 neighbors* (a project can spill across a ~30 km cluster). For smaller modes, just this cell. If there isn't enough → reject.

**Step 3 — Weighted blend.** For each turned-on factor:
- Get its **normalized value** `n` — a 0-to-1 version of the raw number. (E.g. solar yield: `(yield − 1250) / (1800 − 1250)`, clamped to 0–1. So 1,250 kWh→0, 1,800 kWh→1.)
- If the slider weight is **positive**, use `n` (high raw = good). If **negative**, use `1 − n` (high raw = bad). This is how "dual" factors flip.
- Multiply by the absolute weight and add up.

**Step 4 — Rescale to 0–100.** Divide the weighted sum by the total of all weights, times 100. So the score is always a clean 0–100 no matter how many factors you enabled or how big the sliders are — it's a *weighted average*, not a raw sum. That's why turning one slider up doesn't inflate everything.

**In one line of pseudo-code:**
```
score = 100 × Σ( |weight| × (weight≥0 ? n : 1−n) ) / Σ|weight|
```

**The map color** for the score view maps 35→purple and 85→yellow (`(score−35)/50`), because in practice almost all passing cells land in that band — it spreads the color where the actual variation is.

Because this whole thing runs client-side on baked data, moving any slider re-runs all four steps for all 5,289 cells and repaints — instantly, with no network call. That's the core engineering trick of the whole front end.

---

## Part 5 — The build & money math (every acronym in the cost model)

When you click a cell, the right panel shows "BYOP build math" and "Power capex." Here's how every number is produced, in the `sizing()` function. Let's use **1 GW solar** as the example.

### 5.1 Sizing the physical build

- **PUE** = *Power Usage Effectiveness* = 1.15. Datacenters spend extra power on cooling; PUE is the multiplier. 1 GW of computers ("IT load") → **1.15 GW** total campus draw. (1.15 is a good-but-realistic number for a modern efficient facility.)
- **Annual energy** = campus load × 8,760 hours/year = the MWh it needs per year.
- **PV size (MWp)** = (annual energy × solar share) ÷ this cell's solar yield. **MWp** = megawatt-peak = the nameplate DC size of the solar array. Sunnier cell → fewer panels needed for the same energy → cheaper. *This is why the same project costs different amounts in different cells.*
- **Wind size (MW)** (hybrid only) = (annual energy × wind share) ÷ (8,760 × capacity factor). **CF** = *capacity factor* = the fraction of its nameplate a turbine actually delivers on average (a windy site ≈ 30–40%). The model estimates CF crudely from the 50 m wind speed — flagged as screening-only.
- **BESS** = *Battery Energy Storage System*. Sized as hours-of-load: 10 h for solar-only, 7 h for hybrid (wind fills some night gaps so you need less battery). Stored in MWh.
- **Land (ha)** = PV area (2 ha/MWp) + wind area (5 ha/MW) + a small building allowance. Compared against the developable land available to decide "fits / doesn't fit."

### 5.2 The cost (capex) — with editable assumptions

**Capex** = capital expenditure = the upfront build cost. Each piece = quantity × a per-unit cost from the Assumptions panel:

| Assumption | Default | Meaning |
|-----------|---------|---------|
| PV | 0.55 M€/MWp | Cost per MW of solar installed (incl. balance-of-system) |
| BESS | 0.20 M€/MWh | Battery cost per MWh |
| Wind | 1.15 M€/MW | Onshore wind cost per MW |
| Backup | 0.45 M€/MW | Backup generator/fuel-cell cost per MW of load |
| Land | per-CCAA table × multiplier | Rural land price (€/ha), varies by region |

Add them up → total power-system capex, and **per MW of IT** (a normalized "how expensive is power here" number). Note: the datacenter *building* itself is deliberately **excluded** — it costs the same everywhere, so it's noise for a *siting* comparison. The model only prices the parts that change with location.

### 5.3 LCOE — the single most important cost number

**LCOE** = *Levelized Cost of Energy* = the all-in cost of one MWh of electricity over the project's life, in €/MWh. It's *the* number the energy industry uses to compare power sources, so it's the number an expert will look for first.

It's built from:
- **CRF** = *Capital Recovery Factor*. This turns a big upfront cost into an equivalent annual payment — exactly like a mortgage turns a house price into a monthly payment. It depends on:
  - **WACC** = *Weighted Average Cost of Capital* = the blended interest/return rate the money costs (default 8%).
  - **Years** = how long you spread it over (default 20).
  - Formula: `CRF = w(1+w)ⁿ / ((1+w)ⁿ − 1)`, where w = WACC, n = years.
- **O&M** = *Operations & Maintenance* = yearly running cost, as a % of capex (default 1.8%).
- **Backup fuel** = the cost of the gas burned for the backup-power slice.

`LCOE = (annualized capex + O&M + backup fuel) ÷ MWh delivered per year.`

### 5.4 The gas benchmark (the "why not just use gas?" answer)

For every cell the model *also* computes the LCOE of a **pure natural-gas BYOP plant** at the same load — because that's the real competing option, and Spain already has one being built (EdgeMode's Mora campus, 300 MW gas + Bloom Energy fuel cells). The panel shows both side by side and tells you which wins at that spot. On the best solar land the model puts solar-BYOP at **~78 €/MWh** vs. gas at **~81 €/MWh** — a quantified, defensible answer to the obvious challenge, instead of hand-waving. **gas_e** (68 €/MWh_e) and **gas_capex** (0.95 M€/MW) are the two editable gas assumptions.

---

## Part 6 — The detail panel, section by section

Click any cell → the right panel. Top to bottom:

1. **Header + composite score + LCOE** — the headline numbers, plus a "📋 Copy site brief" button that copies a clean text summary to your clipboard (built for pasting into outreach emails).
2. **Parcel at clicked point (Catastro, live)** — this queries Spain's official land registry **in real time** for the exact point you clicked: the *referencia catastral* (legal parcel ID), whether it's rural or urban, the land use, the surface area, and the crops on it. It's calling `ovc.catastro.meh.es` live from your browser. This is the feature that turns "a nice heatmap" into "I can identify the actual legal plot" — genuinely useful to a land buyer. Links out to the official Catastro map, satellite view, and SIGPAC (the agricultural-parcel viewer).
3. **Layer contributions** — a breakdown of *how* this cell got its score: each factor, its raw value, its weight, and the points it contributed. This is the "show your work" section.
4. **BYOP build math** — the physical sizing from Part 5.1, plus a green/red badge for whether the land fits.
5. **Power capex** — the cost table from Part 5.2–5.4, including the gas benchmark line.
6. **Environmental sensitivity** — a stacked bar of the 5 MITECO classes for that cell, plus the continuous PV/wind scores.
7. **Regulatory reception** — the region's score, the specific legal instrument (if any), a paragraph of hand-written analysis, and citation links. See Part 7.
8. **Context** — nearest DC project, nearest city, wind/rain, existing solar, nearest substation.

Everything is labeled "screening-grade" where appropriate — the model is honest that it's a first-pass filter, not an engineering study.

---

## Part 7 — The regulatory layer (the human-judgment part)

This is the one layer that **isn't** from an API — it was hand-built from primary sources (regional government press releases, project filings). Each of the 17 regions gets a **0–100 reception score**, a **confidence level** (high/medium/low, based on how hard the evidence is), the **specific legal instrument** that region offers, a **dossier** paragraph, and **source links**.

The two that matter most, and are worth knowing by name:

- **Aragón — 95/100.** Has **PIGA** (*Proyecto/Plan de Interés General de Aragón*), a real legal fast-track that lets big strategic projects skip normal planning friction. This is why AWS, Microsoft, and a dozen others are piling into Zaragoza. High confidence.
- **Extremadura — 90/100.** Has **PREMIA** (*Proyecto de Interés Empresarial Autonómico*), its equivalent fast-track. Where the Merlin/Edged 1 GW campuses are going. High confidence.

The rest range down to Balears at 30 (restrictive land politics). The README of this data file says it plainly: *"this layer is interpretive by design — the dossier text and citations ARE the data, the score is just its projection onto one axis."* That's the honest framing to use — it's expert judgment, transparently sourced, not a measurement.

---

## Part 8 — The datacenter & ground-truth layers

The dots on the map (real datacenters) come from **four merged sources**, combined in `build_sites.py`:

1. **Curated list (26 projects)** — hand-researched from primary sources, each with a status (operating/construction/announced/land) and a note. This is the highest-quality core.
2. **datacentermap.com (DCM)** — 157 facilities with exact coordinates. DCM has no free API; the data was read out of the JSON embedded in their Next.js web pages via a browser session. Curated entries "borrow" DCM's precise coordinates when they match.
3. **baxtel.com** — 249 facilities *with real lifecycle stages* (operational/construction/planned/landbank). Baxtel's REST API is locked (returns 401), **but** their map draws from a public Mapbox vector-tile layer whose access token is embedded in the page for every visitor. So the data was pulled by fetching and decoding those map tiles directly in Python — using only what's already served to any visitor, never touching the locked API. This is the source of the crucial "land-banked" category (companies that have bought land but not announced a build).
4. **OpenStreetMap** — any additional DC-tagged facilities.

The merge logic is careful about **not double-counting**: it matches by coordinates + name tokens, and deliberately keeps ambiguous cases as separate flagged entries rather than silently guessing they're the same (guessing wrong corrupts the data). This is why you'll occasionally see what looks like a near-duplicate — that's the safe design choice, not a bug.

**Solar farms** (3,215) and **substations** (1,031) come from OSM via Overpass, used both as map overlays and, for solar, as the validation ground-truth (Part 2.7).

---

## Part 9 — The Hermes live pipeline (System B, in full)

This is the part that makes the project *ongoing intelligence* rather than a snapshot — and it's the strongest "I can build at the frontier fast" signal, because **it's a miniature of SemiAnalysis's own business** (continuously-updated infrastructure intelligence).

### 9.1 Where it lives

A cheap rented Linux server (**Hetzner CX23**, ~€7/month, in Germany) — the "Hermes VM." It runs one Python script, `dc_watch.py`, on a schedule (**cron**, daily at **12:15 UTC** — deliberately timed to *dodge DeepSeek's peak-pricing windows* of 01–04 and 06–10 UTC, because you're cost-constrained to ~$5/month).

### 9.2 What it does, step by step

1. **Collect.** Reads 4 RSS feeds (3 Google News searches in Spanish for "centro de datos" / "data center España" / "hiperescala", + Datacenter Dynamics España). Keyword-filters, drops anything already seen. Caps at 40 articles/day — a hard budget cap.
2. **Fetch text.** For each article, pulls the full text with `trafilatura`. Google News wraps links in a redirect, so there's a decoder for that. If an article is paywalled/undecodable, it falls back to just the headline + RSS snippet.
3. **Extract (the AI step).** Sends the articles to **DeepSeek V4 Flash** (a very cheap Chinese LLM) in batches of 8, asking for **structured JSON**: for each article — is it about a *real, concrete Spanish datacenter project*? If so, extract project name, company, municipality, province, event type (land purchase / announcement / permit / construction start / operational / expansion / deal / cancelled), MW, €M investment, a ≤25-word summary, and a confidence score.
4. **Reconcile (the smart step).** For each extracted fact, it fuzzy-matches against the existing database of projects (by name + company + municipality). Then:
   - **New project?** Geocode the municipality (via OpenStreetMap Nominatim) to get coordinates, insert it, flag it "unreviewed."
   - **Existing project?** Update it — but with rules: status only ever moves *forward* (announced→construction→operating, never backward); MW/investment numbers only update if confidence ≥0.7 *and* the change is >15% (avoids noise). **Every change is logged with its source article** — so each card has a traceable history of what changed, when, and why. This is the "cards self-update and are traceable" feature you asked for.
5. **Publish.** Exports the whole knowledge base to `dc_live.json` and pushes it to the GitHub repo via the **GitHub Contents API** (no `git` needed, no open ports on the VM — keeps the firewall SSH-only).
6. **Notify.** Sends you a **Telegram** digest: how many articles, how many relevant, new projects, changes, total count.

### 9.3 Cost-safety details (worth knowing, because they show care)

- **Batching** (8 articles/call) cuts the number of API calls.
- **Truncation recovery:** if DeepSeek's JSON gets cut off mid-response, a salvage function recovers the complete part instead of losing the batch.
- **No infinite retries:** if a batch hard-fails, its articles are still marked "seen" so they're never re-fetched and re-billed. Without this, a bad article would cost tokens *every single day forever* — this was a real bug that got caught and fixed.

### 9.4 The live-trigger demo

Normally the pipeline runs once a day. But the site has a **"⚡ Trigger ingestion now"** button (in the news feed panel). Clicking it:
1. Writes a tiny `trigger.json` to GitHub (using a token stored only in your browser).
2. The VM polls that file every 2 minutes (a second cron, `trigger_poll.sh`), sees the new timestamp, and runs the pipeline immediately.
3. The browser polls for fresh data and auto-reloads when it appears (~2–4 min).

This lets you **demo the whole live pipeline running, on demand, in front of someone** — click, wait a couple minutes, watch a new datacenter appear on the map from a news article. That's a genuinely impressive live demo.

### 9.5 How live data merges onto the map

When the page loads, `app.js` fetches `dc_live.json` and merges each live project onto the baked datacenter markers — matching by proximity + name tokens. Matched projects get their news trail and change log attached (visible when you click the dot); unmatched new ones appear as fresh markers flagged "unreviewed — auto-created from news." The "📰 News feed" line in the left panel shows the count and last-updated date.

---

## Part 10 — How it's all hosted and deployed

- **The website is 100% static** — just HTML, JS, and JSON files. No backend server, no database behind the site. This is why it's free to host and can't "go down" in the usual sense.
- **GitHub Pages** serves it for free from the `spain-dc-map` repo. `index.html` + `app.js` + the data files, that's it.
- **`pack_web.py`** exists so the site *also* works when you just double-click `index.html` on your own computer (no server) — it wraps the JSON into `.js` files the browser can load directly. (Browsers block `fetch()` of local files; a `<script>` tag isn't blocked. That's the whole trick.)
- **`deploy_pages.sh`** is the publish script: it copies the `web/` folder into the GitHub repo, commits, and pushes. The daily `dc_live.json` is excluded from this (the VM owns that file and pushes it separately).
- **Two files get pushed by two different machines:** you push everything *except* `dc_live.json` from your Mac; the VM pushes *only* `dc_live.json`. They never collide because they touch different files.

**Repo layout:**
```
siting-model/                 ← your private working repo (Mac)
├── data/                     ← raw downloaded source data (big; not deployed)
├── pipeline/                 ← the Python build scripts (System A)
├── hermes/                   ← the live-pipeline scripts (System B, run on the VM)
├── web/                      ← the actual website (this is what gets deployed)
│   ├── index.html
│   ├── app.js                ← the entire scoring engine + UI
│   └── data/*.json + *.js    ← baked model data
├── README.md                 ← public methodology writeup
├── PROGRESS.md               ← full build log
├── OUTREACH.md               ← the 18-target contact plan
└── GUIDE.md                  ← this file
```

---

## Part 11 — Glossary (every acronym, one place)

- **BYOP** — Bring Your Own Power; a datacenter that generates its own electricity on-site instead of using the grid. Same idea as "behind-the-meter."
- **PV** — Photovoltaic; solar panels.
- **PVGIS** — Photovoltaic Geographical Information System; the EU's free solar-yield calculator. **SARAH3** is its solar-radiation database.
- **kWh/kWp/yr** — kilowatt-hours per kilowatt-peak per year; the standard "how much energy will a panel make here" metric.
- **MWp** — megawatt-peak; the nameplate (max) size of a solar array.
- **BESS** — Battery Energy Storage System; the on-site batteries.
- **PUE** — Power Usage Effectiveness; total datacenter power ÷ IT power (cooling overhead). ~1.15 here.
- **IT load** — the power the computers themselves draw (vs. total campus draw).
- **MITECO** — Spain's environment ministry. **ISA** = environmental sensitivity index. **FTV** = solar, **EOL** = wind. Publishes both classified (5 buckets) and continuous (0–10) versions.
- **CCAA** — Comunidades Autónomas; Spain's 17 regions.
- **DEM** — Digital Elevation Model; a height map. **Copernicus** = EU Earth-observation program.
- **NASA POWER** — NASA's free climate dataset. **WS50M** = wind speed at 50 m.
- **CF** — Capacity Factor; the fraction of nameplate a generator actually delivers on average.
- **OSM** — OpenStreetMap; the free crowdsourced map. **Overpass** = its query API.
- **HV** — High Voltage (here, 220/400 kV substations).
- **LCOE** — Levelized Cost of Energy (€/MWh); all-in lifetime cost of electricity. The key comparison number.
- **CRF** — Capital Recovery Factor; converts an upfront cost into an equal annual payment (like a mortgage).
- **WACC** — Weighted Average Cost of Capital; the blended cost of the money (interest/return). Default 8%.
- **O&M** — Operations & Maintenance; annual running cost.
- **Capex** — capital expenditure; upfront build cost.
- **Curtailment** — clean power deliberately switched off because the grid can't absorb it.
- **Catastro** — Spain's official land registry. **Referencia catastral** = a parcel's legal ID. **SIGPAC** = the agricultural-parcel viewer.
- **PIGA** — Aragón's legal fast-track for strategic projects. **PREMIA** — Extremadura's equivalent.
- **DCM** — datacentermap.com. **Baxtel** — baxtel.com. Two commercial datacenter databases.
- **RSS** — Really Simple Syndication; the standard news-feed format.
- **LLM** — Large Language Model (here, DeepSeek V4 Flash does the news extraction).
- **Cron** — the Linux job scheduler that runs the daily pipeline.
- **PAT** — Personal Access Token; the GitHub credential used to publish.
- **Hermes / the VM** — the rented Linux server in Germany running the live pipeline.

---

## Part 12 — Honest limitations (say these *before* they ask)

SemiAnalysis-grade rigor is knowing exactly what your model *can't* do. These are real and you should volunteer them:

1. **Wind is screening-grade only.** The 0.5° NASA grid is too coarse to site turbines — it says "this region is windy," not "put a turbine here." A real hybrid project needs a met-mast campaign or Global Wind Atlas microdata.
2. **Land assembly / ownership risk is invisible.** Catastro shows you the parcel, but not whether the owner will sell, or whether you'd need to assemble 40 plots from 40 owners. That's often the *real* bottleneck and the model can't see it.
3. **Municipal zoning (PGOU) isn't modeled.** Regional welcome (the reg layer) ≠ the specific town's land-use plan. A green region can still have a red parcel.
4. **The regulatory layer is judgment, not measurement.** It's transparently sourced, but it's interpretation projected onto a 0–100 axis. The dossiers are the real content.
5. **All economics are screening-grade and assumption-driven** — which is *why* every assumption is live-editable. The point is the framework and the relative ranking, not a bankable cost to two decimals.
6. **The live pipeline can misclassify or duplicate.** It's a cheap LLM reading news; new auto-created projects are flagged "unreviewed" precisely because they need a human check. That's a deliberate design choice (flag, don't silently guess).

Framed right, every one of these is a *strength* — it shows you understand where a screening model ends and real diligence begins.

---

## Part 13 — How to rebuild it from scratch (the pipeline order)

If you ever need to regenerate the data (System A), the stages run in this order (all in `pipeline/`):

1. `build_grid.py` → the 0.1° grid (`grid.csv`)
2. `fetch_pvgis.py` → solar yield + elevation (`pvgis.csv`)
3. `fetch_terrain.py` → terrain relief (`elev.csv`)
4. `fetch_power.py` → wind + rain (`power.csv`)
5. `sample_isa.py` + `sample_isa2.py` → environmental sensitivity (`isa.csv`, `isa2.csv`) — needs the MITECO rasters downloaded into `data/`
6. `fetch_osm.py` → solar farms + substations
7. `fetch_baxtel.py` → baxtel sites
8. `build_sites.py` → merges all datacenter + solar-farm sources → `datacenters.json`, `solar_farms.json`
9. `assemble.py` → joins everything into `web/data/cells.json`
10. `pack_web.py` → wraps JSON into `.js` for `file://` use
11. `deploy_pages.sh` → publish to GitHub Pages

System B (Hermes) is separate and lives on the VM — `seed_db.py` once to initialize, then `dc_watch.py` daily via cron.

---

*This guide describes the code exactly as it stands. If you change a feature, update the relevant part so it stays your single source of truth.*
