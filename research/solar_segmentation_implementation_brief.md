# Implementation Brief: Solar Panel Segmentation & Coverage-Ratio Layer

**Audience**: a coding agent picking this up cold, no memory of prior conversation. Read
`/Users/marcserrano/WORK/SEMIANALYSIS/siting-model/research/solar_panel_segmentation_feasibility.md`
(the "research report") in full before writing any code — it contains the verified technical
findings (model choice, imagery source, hardware feasibility, geometry derivation, citations) this
brief builds on. This brief does not re-derive those findings; it turns them into an ordered,
checkable implementation plan. Where a number or claim is used below, it comes from that report —
go there for the "why," not here.

This is a spec document only. No code has been written yet for this feature.

---

## 1. Motivation

The project (`siting-model`) tracks Spain's solar farms for a datacenter-siting analysis. Today,
`data/solar_farms.json` holds ~3,215 records of `[lat, lon, capacity_MW, name]` — point data only,
rendered on the web map (`web/app.js`) as circles sized by `sqrt(capacity_MW)`. This is a good
overview but tells you nothing about the *shape* of a farm or how efficiently it uses its land
parcel. Two farms with identical claimed capacity could be a dense, well-packed array or a sparse
one with lots of unused land inside the fence line — the point data can't distinguish them.

The goal of this feature is to go from **points** to **true panel shapes**, and from there to a
measurable **land-use-efficiency / coverage-ratio statistic per site**: what fraction of a farm's
land parcel is actually covered by panels, versus access roads, inverter pads, buffer, and unused
corners. This is also a direct, measured replacement for an assumption already baked into
`pipeline/build_sites.py` — capacity for OSM elements without a tagged output is currently just
guessed as `km2 * 0.6 (bbox fill) * 50 MWp/km²`, a crude density prior. A real per-site coverage
ratio is strictly better information and was already flagged as a natural target for this project
in the research report's grounding section.

**This is additive, not a replacement.** The existing point/capacity layer stays exactly as-is;
segmented polygons become a *new* layer that a user can toggle on top of it, the same way
`web/app.js` already treats "existing solar farms" (`ov_pv` toggle → `state.showFarms` →
canvas-drawn circles) as one togglable layer among several (substations, footprint overlay, base
imagery, etc.). Nothing about `solar_farms.json` or its rendering path should change.

**The core insight that makes this tractable** (from the research report, section 1a): this is
*not* an object-detection problem. Marc already knows *where* every farm is — OSM gave him that.
What's missing is the *shape*. That reframes the task from "find solar panels anywhere in Spain"
(hard: needs a trained detector, huge imagery volume, false-positive risk) to "given a known point,
trace the boundary of the object under it" (easy: a zero-shot **promptable** segmenter). Segment
Anything (SAM/SAM2/MobileSAM), via the `segment-geospatial` (samgeo) Python package, does exactly
this: point-prompted or box-prompted segmentation, no training or fine-tuning, run once per known
site. This is why the research report concludes "no purpose-built solar-detection model needed" —
detection was already solved by OSM; only segmentation remains, and that's a solved zero-shot
problem for compact, well-bounded objects like solar panels (reported IoU ≈ 0.54–0.69 zero-shot
per arXiv:2306.16623, per the research report).

---

## 2. High-level pipeline

Five conceptual stages, following the existing `pipeline/` convention of one `fetch_*.py` script
per data source, feeding into `build_sites.py`, then `pack_web.py` for the web map. All existing
pipeline scripts are plain `requests` + resume-safe disk caches + `ThreadPoolExecutor` for I/O +
`PIL`/`numpy` for raster decode (see `fetch_pvgis.py`, `fetch_terrain.py`) — new scripts should
match this house style rather than introducing a different structure (no async frameworks, no new
CLI tooling, no config files beyond what's already the norm).

1. **Source coordinates** — already have these. `data/solar_farms.json` (points) and
   `data/osm_solar.json` (the Overpass response they were derived from). *No new code, reuse as-is
   — except see Step 1 in section 3, which upgrades `osm_solar.json`'s geometry.*

2. **Fetch a georeferenced image crop per site from PNOA** — *new code.* One PNOA WMS `GetMap`
   HTTP call per site (verified live, no API key, 25–50cm native resolution — see research report
   §2), bbox padded beyond the site's OSM footprint, sized so the crop resolves panel rows clearly.
   Follows the same shape as `fetch_terrain.py`'s tile-fetch-and-cache pattern, but simpler (WMS
   `GetMap` returns the whole crop in one call — no tile-pyramid math needed, unlike the
   XYZ-tile-stitching `fetch_terrain.py` has to do).

3. **Run point/box-prompted SAM via samgeo on the crop** — *new code, but the ML "hard part" is
   entirely pretrained.* `segment-geospatial` wraps SAM/SAM2/MobileSAM for georeferenced rasters:
   feed it the crop plus a prompt (box preferred over point per the remote-sensing SAM literature
   cited in the research report), get back a mask. MobileSAM (~40MB) is the primary candidate for
   the 8GB M2; SAM ViT-B (375MB) is the documented fallback for slightly better mask quality. No
   training or fine-tuning anywhere in this pipeline.

4. **Vectorize the mask to a polygon** — *new code, but mostly reuse of existing library
   capability.* Prefer samgeo's built-in raster→vector export first; fall back to
   `rasterio.features.shapes` + `shapely` (simplify/buffer) only if samgeo's output isn't clean
   enough. `rasterio` and `shapely` are already installed in this project's `.venv` (confirmed by
   inspection — nothing new to add there); `geopandas` is not yet installed and will arrive as a
   transitive dependency of `segment-geospatial`.

5. **Compute coverage-ratio statistics against the OSM parcel polygon** — *new code, pure math, no
   ML.* Per the research report's geometry section (§4): primary ratio = segmented panel area ÷
   OSM land-parcel polygon area (both are ground-plane quantities — deliberately **not**
   tilt-corrected, since correcting for tilt would answer a different question, physical panel
   surface area, not land-use efficiency). Secondary QA ratio = panel area ÷ convex hull of the
   panel rows, expected in the ~0.35–0.55 engineering ground-coverage-ratio (GCR) band — values far
   outside that band flag a bad segmentation automatically, without manual review.

6. **Integrate as a new layer into the existing web map pipeline** — *new code in existing files,
   following existing conventions exactly.* Extend `build_sites.py` (or add a small new stage
   script) to fold polygon + ratio data into a new `web/data/*.json` file, add it to the `PACK` list
   in `pack_web.py` (same one-line-per-file pattern already used for `cells.json`, `solar_farms.json`,
   etc.), and add a new toggle in `web/index.html`/`web/app.js` alongside the existing `ov_pv`
   toggle — as a genuinely separate, independently-togglable layer, not a modification of the
   existing farm-circle rendering.

**Summary of what's new vs. reused**: stages 2, 3, 4, 5 are new code (imagery fetch, segmentation,
vectorization, ratio math). Stage 1 is pure reuse, except its *upstream input* needs a one-time
upgrade (Step 1 below). Stage 6 is new code but slotted into an existing, well-understood extension
point (`build_sites.py` → `pack_web.py` → `web/app.js` toggle pattern) — it should not require
touching the existing farm-point rendering logic at all.

---

## 3. Concrete near-term steps

Ordered. Each has a self-checkable "done when." Do not proceed past Step 4 without a human
(Marc) visually reviewing the pilot output — that gate is intentional, not a formality.

### Step 0 — Environment setup + smoke test

Install `segment-geospatial` (pulls in `torch`, SAM/SAM2, and `geopandas` as dependencies — the
project's `.venv` currently has `rasterio`/`shapely`/`numpy`/`pandas`/`pillow` but no `torch`, no
`geopandas`, no `segment-geospatial`; there is no existing `requirements.txt` in this repo, so
check whether to create one or just install into the existing `.venv` ad hoc — flagged as an open
decision below). Download a SAM checkpoint — MobileSAM (`mobile_sam.pt`, ~40MB) as the primary
choice per the research report's hardware section.

**Smoke test**: segment ONE single well-known site end-to-end — fetch its PNOA crop, run
point-or-box-prompted segmentation, get back a mask, vectorize it — before writing any pipeline
code. Pick the largest farm in `data/solar_farms.json` (sort by `capacity_MW` descending, take
index 0) so the array is unambiguous in the imagery.

**Done when**: a single mask/polygon has been produced for that one site and visually looks like a
solar array (rows of panels, not noise) when plotted over the source crop. If this doesn't work,
stop and debug here — don't proceed to batch code against a broken foundation.

### Step 1 — Re-fetch OSM with full polygon geometry

`pipeline/fetch_osm.py` currently queries with `out center bb tags qt;`, which returns only a
bounding box per element (confirmed in the research report's grounding section — `data/osm_solar.json`
has bboxes, not polygons). This blocks the coverage-ratio denominator in Step 4, which needs a real
parcel polygon, not its bounding box (a bbox overestimates area for any non-rectangular parcel).
Change the Overpass query to `out geom;` (for ways) and a members-recursive `out geom;` for the 374
multipolygon relations, so each element carries a real node-by-node boundary.

**Done when**: re-running `fetch_osm.py` produces a refreshed `data/osm_solar.json` where solar
elements have a `geometry` array (way) or resolved member geometries (relation), not just `bounds`.
Spot-check a handful of elements to confirm the polygon traces a sensible parcel shape, not a
degenerate line or empty array.

### Step 2 — Build `fetch_pnoa_crop.py`

Following the existing `fetch_*.py` pattern (plain `requests`, resume-safe disk cache directory
mirroring `fetch_terrain.py`'s `terrain_tiles/` convention, `ThreadPoolExecutor` for the I/O-bound
fetch step): take a list of `(lat, lon, capacity_MW)` and download one PNOA WMS `GetMap` crop per
site. **Size the crop relative to farm capacity** — a fixed crop size either clips large farms
(losing parcel area) or wastes bandwidth/resolution on tiny ones. The research report recommends
padding the bbox ~20–30% beyond the OSM polygon's bounding box and requesting WIDTH/HEIGHT sized
for ≈0.25m/pixel; the exact crop-size formula (e.g. derive straight from OSM polygon bbox once
Step 1 lands, vs. a capacity-based heuristic as a fallback for sites lacking usable OSM geometry)
is an **open decision** — flagged below, don't silently pick one without checking both are
reasonable.

**Done when**: running the script against the pilot set (Step 3) produces one cached image file
per site, each visibly containing the full farm with some margin, at approximately the target GSD.

### Step 3 — Pilot run: segment the top 20–30 farms

Sort `data/solar_farms.json` by `capacity_MW` descending, take the top 20–30. For each: fetch its
PNOA crop (Step 2), run MobileSAM/SAM-ViT-B via samgeo prompted with a box derived from the OSM
polygon's bbox (shrunk slightly inward), falling back to a point prompt at the farm centroid if no
usable OSM geometry exists for that site. Export each result as a GeoJSON polygon.

**Done when**: all pilot polygons are exported as GeoJSON, and each has been visually inspected —
plotted over its source PNOA crop — to confirm it traces actual panel rows and not noise, cloud
shadow, bare soil, or a building roof. This is a manual/visual check, not automatable; do not treat
"the script ran without errors" as sufficient — the point of the pilot is catching segmentation
quality problems before scaling.

### Step 4 — Compute pilot coverage-ratio statistics

For the same pilot set, compute both ratios per site:
- **Primary**: segmented panel area ÷ OSM parcel polygon area (needs Step 1's real polygons, not
  bboxes — this step is blocked on Step 1 being done first).
- **Secondary QA**: panel area ÷ convex hull of the panel rows, expected in the ~0.35–0.55 GCR band
  per the research report's geometry derivation.

Use `shapely`/`geopandas` in an equal-area or local UTM projection for the area math (not raw
lat/lon degrees — degree-based area is not comparable across latitude and would corrupt the ratio).

**Done when**: a distribution of both ratios across the pilot set has been reported (min/max/mean,
and any outliers named individually), with outliers on the secondary QA ratio explicitly flagged as
suspected bad segmentations, not real findings. **This is the trust checkpoint** — do not proceed
to Step 5 until this distribution looks sane (most sites' secondary ratio falling near the expected
band) and Marc has reviewed it.

### Step 5 — Scale to all ~3,215 sites

Only after Step 4 passes review. Batch and rate-limit the PNOA fetch (same spirit as
`fetch_pvgis.py`'s `ThreadPoolExecutor(max_workers=8)` pattern) and make the run resumable/
checkpointed — write results incrementally (e.g. append-as-you-go to a CSV or JSON-lines file with
a `done` set read back on restart, exactly like `fetch_pvgis.py`'s `done = {r[0] for r in
csv.reader(...)}` pattern) so a crash partway through a multi-hour run (the research report
estimates ~1.8 hours for the full set at ~2s/crop average, likely dominated by network fetch time
rather than inference) doesn't require starting over.

**Done when**: all (or nearly all — some sites may legitimately fail, e.g. no OSM geometry and no
segmentable imagery) 3,215 sites have a polygon + ratio pair recorded, and a re-run of the script
after an interrupted partial run correctly skips already-done sites rather than reprocessing them.

### Step 6 — Integrate into the web map

Fold the polygon + ratio data into the existing pipeline: extend `build_sites.py` (or add a small
new stage script feeding it) to produce a new `web/data/*.json` file (e.g.
`solar_panel_polygons.json`), add it to the `PACK` list in `pipeline/pack_web.py` (same
one-tuple-per-file pattern already used for `solar_farms.json` → `window.__FARMS`), and add a new,
independently-togglable layer in `web/index.html` + `web/app.js` — a new checkbox alongside the
existing `ov_pv` ("Existing solar farms") toggle, not a modification of it. `web/app.js` currently
renders farm points via a custom canvas layer (`canvasLayer`, drawn per-frame in its `draw`
callback) rather than individual Leaflet markers/polygons, for performance across ~3,215 points —
the new polygon layer should follow the same canvas-drawing approach for consistency and
performance if it's meant to show all 3,215 sites at once (the pilot's 20–30 polygons could
reasonably use a simpler Leaflet GeoJSON layer instead, if that's easier to stand up first — this
distinction is an open decision, see below).

Also surface the coverage-ratio stat somewhere visible: a per-site popup/tooltip value (the map
already does something similar — see the existing "Solar field — allocated land (only ~25% actual
panels)" tooltip pattern around `footLayer` in `web/app.js`), and/or an aggregate distribution
stat (e.g. in the sidebar stats area near where farm/substation counts are already shown, `m_pv`/
`m_subs` elements).

**Done when**: loading the map with the new layer toggled on shows panel polygons rendered
correctly geographically aligned over the base imagery, toggleable independently of the existing
farm-point layer, with a coverage-ratio value visible per site on interaction.

---

## Open decisions for the implementation agent (do not silently pick one)

- **Exact crop-size formula** (Step 2): derive directly from the OSM polygon bbox (once Step 1
  lands) with a fixed percentage pad, vs. a capacity-based heuristic (e.g. `sqrt(capacity_MW)`-scaled)
  as a fallback for sites lacking usable OSM geometry. Both are reasonable; pick one and document
  why, don't leave it implicit.
- **Exact SAM checkpoint choice**: MobileSAM (~40MB, fastest) vs. SAM ViT-B (375MB, better mask
  quality) — the research report recommends starting with MobileSAM and falling back to ViT-B if
  mask quality on the pilot set looks poor. Confirm this via the Step 3 pilot review rather than
  assuming one is sufficient.
- **Exact polygon simplification tolerance**: vectorized masks from raster segmentation will have
  jagged, pixel-stepped edges; some `shapely.simplify(tolerance=...)` value will be needed before
  these are usable as clean map polygons or before area math is computed on them. No specific
  tolerance value has been chosen — pick one empirically from the pilot set (small enough to
  preserve row structure, large enough to remove pixel-stepping) and document it.
- **Whether to add a `requirements.txt`**: this repo currently has no dependency manifest (checked
  by inspection — `.venv` exists with packages installed ad hoc). Adding `segment-geospatial`
  (which pulls in `torch`, a large dependency) may be a good forcing function to add one, but that's
  a repo-hygiene decision beyond this feature's strict scope — flag it to Marc rather than deciding
  unilaterally.
- **Pilot layer rendering approach** (Step 6): simple Leaflet GeoJSON layer (fine for 20–30 pilot
  polygons, faster to build) vs. building the canvas-based renderer from the start (needed
  eventually for all 3,215 polygons, more work up front). Recommend building the simple version
  first for the pilot review in Step 3/4, then deciding whether to invest in the canvas approach
  once Step 5's full-scale data exists.

---

## Reference

Full technical justification, verified numbers, and citations:
`/Users/marcserrano/WORK/SEMIANALYSIS/siting-model/research/solar_panel_segmentation_feasibility.md`
