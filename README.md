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

- **Three project scales** — 1 GW campus / 100 MW / 10 MW edge — each with its own weight presets, hard gates, and *mechanistic land math*: PV MWp and battery MWh are sized from each cell's own solar yield, converted to hectares, and checked against the cell's (or, for GW mode, the cell-cluster's) actually-developable land.
- **Live re-weighting** — every variable has a slider (city and DC-cluster proximity accept *negative* weights: remoteness can be the asset); the choropleth, ranking, and detail panels recompute instantly, no rebuild.
- **Hard gates** — max terrain relief, minimum developable share; gated-out cells drawn dark.
- **Click any cell** — full breakdown: layer contributions, PV/BESS/land sizing for the selected scale, MITECO sensitivity composition, the regional regulatory dossier with sources, nearest announced DC project.
- **Single-layer views** — inspect any input layer as its own choropleth.

## The six variables (and what got cut)

| # | Layer | Source | Why it's in |
|---|-------|--------|-------------|
| 1 | Solar specific yield | PVGIS v5.3 / SARAH3, optimal fixed tilt, per cell | Sets the size and cost of the power plant that *is* the datacenter's utility |
| 2 | Environmental permitting friction | MITECO Zonificación Ambiental FTV 2023 (25 m raster, sampled at 200 m) | The state's own map of where utility PV will/won't clear environmental review — the solar field is the permitting-critical footprint |
| 3 | Buildable terrain | AWS Terrain Tiles / Copernicus (~300 m), intra-cell relief p98−p2 | Hundreds of contiguous flat hectares gate both the array and the campus |
| 4 | Regulatory reception | Hand-built per-CCAA dossier from primary sources (confidence-flagged) | The genuinely underpriced variable: Aragón (PIGA) and Extremadura (PREMIA) have *legal instruments* that fast-track exactly this asset |
| 5 | City proximity (dual-sign) | Distance to nearest city ≥100k | Labor/fiber pull vs. social-pushback exposure — direction is a user choice, not an assumption |
| 6 | DC-cluster proximity (dual-sign) | Distance to 12 announced/operating DC sites (researched) | Follow validated corridors, or deliberately buy whitespace |

**Cut, deliberately:** substation/interconnection distance (off-thesis — the whole point is not queuing), gas pipelines (same), wind resource (PV-only v1), water as a numeric layer (BYOP designs dry-cool; water politics are carried inside the regulatory dossiers — see Talavera), Corine land cover (MITECO's index already embeds land constraints), satellite/ML exotica (a simple correct model first).

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

## Sizing assumptions (shown in-app, deliberately simple)

PUE 1.15 · 90% of energy from on-site PV+BESS (residual = backup/flex) · 2 ha per MWp · 10 MWh battery per MW of campus load. A 1 GW-IT campus at a 1,750 kWh/kWp cell ⇒ ~5.2 GWp PV, ~11.5 GWh BESS, **~10,400 ha** — which is why GW mode aggregates neighboring cells and why "contiguous developable land" is a first-class variable, not an afterthought.

## Known limitations (v1)

- 0.1° cells are a screening resolution: the output is "option land *here*," not "build on *this parcel*." Parcel-level diligence is the designed next step — Catastro's Sede Electrónica for ownership/legal state of the top-N cells only (its INSPIRE bulk endpoints were unreachable during the build; noted in PROGRESS.md).
- The 90%-solar/10%-backup configuration is one point on a cost curve; a real design would optimize PV/BESS/backup jointly per site. The model's land math is linear in that choice.
- Regulatory scores for regions without primary-source evidence are posture estimates and say so on their face.
- Strict off-grid is a modeling stance: in practice most BYOP builds will want a small grid tie eventually (export of surplus, backup import). The bet is that *starting* off-grid re-orders the map — and the data (curtailment where queues are longest) supports it.
- Canary Islands excluded in v1 (separate raster and grid reality).

## Repo layout

```
pipeline/   5 stages: grid → PVGIS → terrain → MITECO sampling → assemble
data/       intermediate CSVs + MITECO raster (gitignored where heavy)
web/        index.html + app.js + data/{cells,regions}.json — the deliverable
PROGRESS.md research log: what was verified, where, and what's still open
```
