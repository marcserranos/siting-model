# Feasibility: Solar-Panel Segmentation & Coverage-Ratio Statistic per Site

Research memo, not implementation. Scope: can Marc go from his existing 3,215 known solar-farm
coordinates to a per-site "panel pixels ÷ land-parcel area" packing-density statistic, using
free/cheap imagery and an 8GB M2 MacBook, without building or training anything from scratch.

## Grounding: what already exists in the repo

Before researching, I read the actual files this would build on:

- `data/solar_farms.json` — 3,215 records `[lat, lon, capacity_MW, name]`. Confirmed point-only,
  no geometry.
- `data/osm_solar.json` — 2,881 Overpass `way` + 374 `relation` elements tagged
  `power=plant`/`plant:source=solar`. **Important finding: this file only has bounding boxes, not
  polygons.** `pipeline/fetch_osm.py` queries with `out center bb tags qt;`, which returns a
  `bounds` bbox per element and nothing else — there is no node-by-node `geometry` array in this
  file today. Getting an actual land-parcel *polygon* (not just its bbox) requires re-fetching with
  `out geom;` (for ways) or a members-recursive `out geom;` for the 374 multipolygon relations.
  This matters a lot for the coverage-ratio math below: a bounding box overestimates the area of
  any non-rectangular parcel, sometimes by a large margin.
- `pipeline/build_sites.py` — reveals that today's `capacity_MW` for OSM elements *without* a
  tagged output is not measured at all, it's **assumed**: `km2 * 0.6 (bbox fill) * 50 MWp/km²`
  (line ~26-27). This is exactly the kind of density prior the segmentation project would let Marc
  replace with a measured value — worth noting as motivation, independent of the research below.
- `pipeline/fetch_pvgis.py`, `fetch_terrain.py`, `fetch_baxtel.py` — all follow the same pattern:
  plain `requests`, resume-safe caches (CSV `done` sets, or a tile directory), `ThreadPoolExecutor`
  for parallel I/O-bound fetches, and in `fetch_terrain.py`, PIL/numpy decoding of PNG raster tiles
  into elevation arrays. No ML anywhere in the pipeline yet. This is a good precedent: he already
  knows how to fetch and decode raster tiles into numpy — imagery fetching for segmentation is the
  same skill applied to a different raster source.
- `data/pvgis.csv` — column 4 is PVGIS's per-cell **optimal fixed tilt angle**, already fetched for
  5,289 grid cells. Empirically: min 12°, max 41°, mean 35.4° across Spain. This is directly useful
  for §4 below — Marc's own data already tells us the representative tilt angle, no need to guess.

---

## Bottom line

- **Plug-and-play is the right approach — no training needed.** A pretrained, general-purpose
  promptable segmenter (Segment Anything / SAM2 / MobileSAM), given a box or point prompt derived
  from a coordinate Marc already has, is a better fit than any purpose-built "solar panel detector,"
  precisely because detection (finding *where* the panels are) is not the hard part of his problem —
  he's already solved that with OSM. He only needs the segmentation half, at 3,215 known locations.
- **No purpose-built solar-segmentation model comes with weights that are both current and a clean
  drop-in fit.** DeepSolar-family repos exist with released weights, but are US-rooftop-oriented and
  trained on Google Static Maps imagery, not Spanish ground-mount farms at PNOA resolution. The
  academic PV01/PV03/PV08 dataset is an excellent *resolution and content match* (0.3m aerial,
  ground-mount arrays) but is a labeled dataset, not a released checkpoint — models trained on it
  (SolarFormer, Mask2Former baselines) have papers/repos but I could not verify a maintained,
  downloadable trained checkpoint for any of them (flagged explicitly below, don't take my word for
  it — check the repos yourself before ruling it out).
- **Imagery: PNOA (IGN) is clearly the right source.** Free, no API key, Spain-specific, 25–50cm
  native resolution, live WMS/WMTS endpoints (verified below, both return HTTP 200 right now).
  Sentinel-2 is numerically far too coarse (confirmed below). Esri/Google/Bing tiles are legally
  murkier for a public repo and not obviously better in rural Spain.
- **Hardware verdict: comfortably feasible, inference-only, on the 8GB M2.** Use MobileSAM (~40MB)
  or SAM ViT-B (375MB) — not ViT-H (2.56GB, too tight against 8GB unified memory shared with macOS).
  No fine-tuning needed or recommended. Full 3,215-crop run is plausibly on the order of an hour or
  two of unattended compute; the top 50–100 biggest farms (Marc's own stated starting point) would
  take minutes.
- **Geometry: don't tilt-correct the segmentation output.** A nadir photo measures ground-projected
  footprint, which is the *correct* apples-to-apples quantity to compare against OSM's
  also-ground-plane parcel polygon. Recommended ratio: **segmented panel pixel area ÷ OSM
  land-parcel polygon area**, with a secondary ratio (panel area ÷ convex hull of the panel rows) as
  an automatic QA check against the known ~0.35–0.55 engineering GCR band.

---

## 1. Does a usable pretrained model already exist?

### 1a. Zero-shot promptable segmentation (SAM family) — the actual answer here

**Segment Anything (SAM)**, Meta, Apache 2.0 license, [github.com/facebookresearch/segment-anything](https://github.com/facebookresearch/segment-anything). Three checkpoint sizes (`vit_b`/`vit_l`/`vit_h`), trained on 11M images / 1.1B masks, promptable with points, boxes, or masks; native image encoder input is 1024×1024 (arbitrary-size crops get resized/padded to this internally, so image tiles don't need to be a particular size going in). This is *general-purpose* — it has no idea what a solar panel is, but that's fine, because Marc supplies the prompt (a point or box), and SAM only has to draw a tight boundary around whatever's under that prompt.

Relevant to solar arrays specifically: **["The Segment Anything Model (SAM) for Remote Sensing Applications: From Zero to One Shot"](https://arxiv.org/abs/2306.16623)** (arXiv 2306.16623) tested SAM across remote-sensing datasets with point, box, and text prompts. Reported (per the paper's abstract/summary, I did not verify every number against the full PDF): SAM achieves competitive mask IoU for compact, well-bounded objects like **solar panels and buildings (IoU ≈ 0.54–0.69)** when prompted with boxes, versus much worse performance on diffuse objects like roads. Box prompts outperformed point prompts across their datasets. Newer summaries (from search snippets, not independently verified against the primary source — treat with some caution) suggest SAM2/2.1 improve further, including on small PV cells in lower-resolution imagery. I'd recommend Marc treat the 0.54–0.69 IoU figure as a realistic *zero-shot* expectation band, not the ~0.85 IoU numbers quoted for models *trained specifically* on solar datasets (see 1b) — those are a different, supervised, comparison.

**Practical tool: [segment-geospatial (samgeo)](https://github.com/opengeos/segment-geospatial)**, docs at [samgeo.gishub.org](https://samgeo.gishub.org/), by opengeos (Qiusheng Wu). This is the actual plug-and-play match for Marc's stack: it wraps SAM/SAM2 for georeferenced rasters directly — takes a GeoTIFF in, gives you a GeoTIFF mask or vectorized polygons out, supports point/box prompts and even text-prompted segmentation (via an integrated Grounding DINO/LangSAM path) if he ever wants to go fully automatic later. Published in JOSS (8(89), 5663). Notes 8GB of *GPU* memory as a rough recommendation for large-scale batch use — see §3 for why that's not the right comparison for Marc's inference-only, one-crop-at-a-time, MPS/CPU workload.

**MobileSAM**, [github.com/ChaoningZhang/MobileSAM](https://github.com/ChaoningZhang/MobileSAM) — distills SAM's image encoder down to a TinyViT (~5–9.7M params vs. 632M for ViT-H's encoder), checkpoint `mobile_sam.pt` is **~39–41MB**, reportedly ~50x faster than ViT-H. Compatible with the same point/box prompting API as SAM. Good candidate for the 8GB machine specifically because of its small footprint (§3).

**Grounded-SAM** (Grounding DINO + SAM, see [viso.ai explainer](https://viso.ai/deep-learning/grounded-sam/) and [zero-shot text-prompted remote-sensing segmentation paper](https://www.sciencedirect.com/science/article/pii/S2666544125000012)) — lets you segment by a text prompt like "solar panel" with no coordinate at all. **Not needed here** — Marc already has a coordinate per site, so plain point/box-prompted SAM is simpler and avoids Grounding DINO's proposal noise. Worth keeping in mind only if he later wants to *discover* uncatalogued farms rather than measure known ones.

### 1b. Purpose-built solar-segmentation models and datasets

| Name | Weights released? | License / notes | Fit for Marc |
|---|---|---|---|
| [DeepSolar](https://github.com/wangzhecheng/DeepSolar) (Stanford, Yu et al.) | Yes, pretrained weights linked in repo | Inception-v3 classifier + CAM-based weak localization, not a tight-polygon segmenter | Trained on Google Static Maps imagery over the continental US (mostly rooftop-heavy); domain and imagery source mismatch for Spanish ground-mount farms |
| [DeepSolar-3M](https://github.com/rajanieprabha/DeepSolar-3M) | Weights via external Google Drive links | Newer, larger-scale (3M systems) | Same US/rooftop bias; external hosting means I can't vouch for the links staying live |
| [gabrieltseng/solar-panel-segmentation](https://github.com/gabrieltseng/solar-panel-segmentation) | U-Net w/ ImageNet-pretrained ResNet34 encoder, weights in repo | Small, simple, real segmentation (not just classification) | Best of the "small purpose-built" options if Marc wants a solar-specific baseline to compare against SAM's output, but check the training-imagery resolution/GSD before trusting it on PNOA crops directly |
| [NREL Panel-Segmentation](https://github.com/NREL/Panel-Segmentation) | VGG16-ConvTranspose based | Aimed at rooftop residential arrays | Wrong array type for ground-mount Spanish solar farms |
| [PV01/PV03/PV08 dataset](https://zenodo.org/records/5171712) (paper: [ESSD 13, 5389 (2021)](https://essd.copernicus.org/articles/13/5389/2021/)) | **Dataset only, not a checkpoint** | 3,716 samples, polygon annotations, three resolutions: PV01 = 0.1m UAV rooftop, **PV03 = 0.3m aerial ground-mount** (5 background types: shrub, grassland, cropland, saline-alkali, water), PV08 = 0.8m satellite | **PV03 is an excellent resolution/content match** for PNOA-crop ground-mount Spanish farms — worth downloading purely as a *validation set* to sanity-check whatever pipeline Marc builds, even without training on it |
| [SolarFormer](https://arxiv.org/pdf/2310.20057) / [SolarFormer++](https://github.com/UARK-AICV/SolarFormerPlusPlus) / [S3Former](https://arxiv.org/html/2405.04489v1) | **Unclear — repo exists but I could not verify a released, downloadable trained checkpoint from the search results alone.** Check the repo directly. | Mask2Former-based, multi-scale transformer | Reports ~85%+ IoU on PV03-class data *when trained on it* — a useful target/sanity-check number, not a plug-and-play weight |

**Bottom line for Q1**: there is no purpose-built solar segmentation model that is simultaneously (a) released with usable weights, (b) trained on imagery matching PNOA's resolution/content, and (c) documented well enough to trust blind. The zero-shot SAM/SAM2/MobileSAM route is the pragmatic answer, especially combined with PV03 as a free, resolution-matched *validation* set to spot-check accuracy before trusting the pipeline across all 3,215 sites.

---

## 2. Imagery source and resolution

### Why sub-meter GSD is required

A standard 60-cell module is **~1.65m × 0.99m**; 72-cell commercial modules run **~1.96m × 0.99m** ([panel size sources](https://www.solarreviews.com/blog/complete-guide-to-solar-panel-size), [unboundsolar.com](https://www.unboundsolar.com/blog/solar-panel-size-guide)). To resolve array/row structure (not necessarily individual modules) a segmentation model needs at least a few pixels across a module — practically, GSD ≤ 0.5m, and 0.25m is comfortably enough to see row boundaries and the gaps between rows.

**Sentinel-2 is confirmed too coarse, numerically**: its visible/NIR bands are 10m GSD ([Earth Engine catalog](https://developers.google.com/earth-engine/datasets/catalog/sentinel-2)). A 1.65m-wide module is under 17% of one pixel's linear dimension — a whole multi-hectare solar farm might occupy tens of Sentinel-2 pixels total, enough to *detect* a bright/dark anomaly (which some published work does, for province-scale mapping) but nowhere near enough to segment individual rows or panels. Reject Sentinel-2 for this task.

### PNOA (IGN España) — recommended, and verified live

I fetched the endpoints directly rather than trusting a summary:

- **WMS**: `https://www.ign.es/wms-inspire/pnoa-ma?Request=GetCapabilities&Service=WMS` → returns HTTP 200, valid WMS 1.3.0 XML, INSPIRE-profile capabilities, title "Ortoimágenes de España (satélite Sentinel2 y ortofotos del PNOA máxima actualidad...)".
- **WMTS**: `https://www.ign.es/wmts/pnoa-ma?Request=GetCapabilities&Service=WMTS` → HTTP 200, valid WMTS capabilities. Tiles pre-generated in JPEG/PNG, **up to zoom level 19** (≈1:1,000 scale) in EPSG:3857 Web Mercator. At z19, Web Mercator resolution = 156543.034·cos(lat)/2^19 m/px; for Spain's latitude range (36–43°N) that works out to **≈0.22–0.24 m/pixel** — consistent with PNOA's stated native mosaic resolution of **25cm or 50cm depending on region/acquisition date**.
- **No API key required** for either endpoint (both responded without any auth header).
- **Attribution required, not payment**: IGN's stated terms are free use conditional on crediting "PNOA cedido por © Instituto Geográfico Nacional de España" — trivially compatible with a public GitHub Pages project that already leans on Spanish government sources (Catastro, MITECO).
- **Coverage recency**: PNOA-MA ("máxima actualidad") mosaic is explicitly the always-current layer, updated several times a year; underlying tiles are a patchwork of different acquisition dates/resolutions (25 vs 50cm) region to region.
- **Access pattern recommendation**: for per-site crops, a single **WMS `GetMap`** request (arbitrary bbox, one HTTP call, no tile math) is simpler than WMTS tile-pyramid stitching — simpler even than Marc's existing `fetch_terrain.py`, which has to do XYZ tile math and stitch multiple tiles per grid cell. One `GetMap` call per solar-farm bbox gets the whole crop in one shot.
- Official documentation index: [pnoa.ign.es/pnoa-imagen/visualizadores-y-servicios-web](https://pnoa.ign.es/pnoa-imagen/visualizadores-y-servicios-web).

### Fallbacks considered and why they're worse fits

- **Esri World Imagery** (XYZ tiles) — resolution is inconsistent outside US/EU urban cores and not obviously better than PNOA in rural Spain; Esri's terms restrict bulk export (basemap tile services commonly capped around 100,000 tiles) and are oriented around use *within* ArcGIS products or under the Esri Master Agreement ([esri.com/en-us/legal/terms/web-site-service](https://www.esri.com/en-us/legal/terms/web-site-service)) — legally murkier than PNOA for scraping into a public repo.
- **Google/Bing static tiles** — ToS explicitly restrict programmatic scraping and republishing without a paid API key; given `spain-dc-map` is a *public* site, redistributing Google/Bing tiles would be a clear ToS problem. Not recommended.
- **Planet/Maxar** — genuinely overkill: paid commercial constellations (sub-30–50cm) for a need that PNOA already satisfies for free, Spain-specific, with better legal footing.

**Recommendation: PNOA WMS `GetMap`, no fallback needed.**

---

## 3. Hardware feasibility on the 8GB M2 Mac

### Is training necessary at all? No.

Given the workload — inference over ~3,215 (or a prioritized subset of) small image crops, each already anchored to a known coordinate — **zero-shot promptable segmentation needs no training or fine-tuning step.** This is the single biggest simplification available here: the "hard" ML problem (learning what a solar panel looks like, from scratch, across arbitrary backgrounds) is exactly what SAM's 11M-image pretraining already solved in a domain-general way, and the task-specific part (which pixels, at which location) is supplied by Marc's own coordinate + OSM bbox, not learned.

### If fine-tuning were wanted anyway (not recommended, but sized for completeness)

- **Checkpoint sizes**: SAM ViT-B **375MB**, ViT-L **~1.2GB**, ViT-H **2.56GB** (confirmed via hosted file listings: `sam_vit_b_01ec64.pth` = 375MB, `sam_vit_h_4b8939.pth` = 2,564,550,879 bytes ≈ 2.56GB). MobileSAM `mobile_sam.pt` ≈ **39–41MB**. SAM2 (Hiera backbone, released 2024-07-29, refined as SAM2.1 2024-09-30) ships four sizes by parameter count: tiny 38.9M, small 46M, base_plus 80.8M, large 224.4M params — roughly proportional file sizes, tiny smallest.
- **PyTorch MPS backend (Apple Silicon)**: functional, but **training support is explicitly still experimental**, per PyTorch/HuggingFace docs. Known rough edges: not all ops are implemented (needs `PYTORCH_ENABLE_MPS_FALLBACK=1` to silently fall back to CPU for gaps), a documented **memory-contiguity bug** where in-place ops like `addcmul_`/`addcdiv_` can silently zero out or NaN a tensor if it isn't contiguous (this hits some optimizer internals), and bf16 execution on MPS is unoptimized (up to 10x slower than fp16). None of this is disqualifying, but it means MPS *training* is a finicky, debug-as-you-go path — not something to reach for on a one-off measurement task.
- **RAM headroom**: 8GB unified memory is shared with macOS itself (realistically ~2–3GB of OS/GUI overhead), leaving roughly 5–6GB free. Loading ViT-H's 2.56GB checkpoint plus its live activation memory would eat most of that margin and risk swapping. **ViT-B (375MB) or MobileSAM (~40MB) leave generous headroom**, especially since inference here is one small crop at a time (not a large batch), and SAM's image encoder resizes any input to a fixed 1024×1024 internally regardless of the crop's original pixel dimensions.

**Recommendation: MobileSAM (or SAM ViT-B as a fallback for slightly better mask quality) run inference-only, on CPU or MPS, one crop at a time — no training step anywhere in the pipeline.**

### Wall-clock estimate

I have not benchmarked this exact model on this exact machine — these are estimates from published relative-speed figures (MobileSAM ~50x faster than ViT-H; ViT-H itself runs sub-second per image on datacenter GPUs), scaled down to CPU/MPS on an M2. Treat this as a planning estimate, and validate it directly by timing the first 5–10 crops before committing to a full run:

- **MobileSAM, per-crop inference (encode + prompt decode) on M2 CPU/MPS**: plausibly ~0.5–2 seconds/crop.
- **SAM ViT-B, same**: plausibly ~2–5 seconds/crop (larger encoder, more compute per image).
- **Top 50–100 biggest farms** (Marc's own stated starting point): on the order of **1–5 minutes total** — fast enough to iterate on prompt/box parameters interactively before running everything.
- **Full 3,215-crop run**, at a conservative ~2s/crop average: **≈3,215 × 2s ≈ 1.8 hours**, easily left running unattended (matches the pattern of his existing `fetch_pvgis.py`/`fetch_terrain.py` stages, which already run for a while over thousands of network calls).
- In practice, **fetching the PNOA imagery crops over the network will likely dominate wall-clock time more than the segmentation inference itself** — same shape of bottleneck as his existing pipeline stages, and the same fix applies: cache to disk, resume-safe, `ThreadPoolExecutor` for the I/O-bound fetch step, run inference as a separate pass over the cached crops.

---

## 4. The tilt/projection geometry, rigorously

### Setup and derivation

Consider a single flat panel (or a full row of coplanar panels) tilted at angle **θ** from horizontal, with **θ** measured about a horizontal axis perpendicular to the tilt direction (i.e. the row runs east-west, tilts up toward the equator — the standard fixed-mount configuration).

- The panel's true physical dimensions are length **L** (measured along the slope, i.e. up the tilt) and width **W** (measured along the row, horizontal, unaffected by tilt).
- **True module surface area**: `A_true = L × W`.
- A nadir (straight-down, orthographic) camera does **not** see this tilted rectangle at its true size. It sees the parallel projection of the tilted plane onto the horizontal ground plane. Only the dimension *along the tilt axis* foreshortens; the width `W`, lying in a horizontal line, projects unchanged.
- **Apparent (ground-projected) length**: `L' = L·cos θ`.
- **Apparent nadir footprint area**: `A_nadir = L' × W = (L·cos θ) × W = A_true · cos θ`.

So the relationship is:

```
A_nadir = A_true · cos θ         (foreshortening)
A_true  = A_nadir / cos θ        (if you wanted to recover true module surface area from a nadir photo)
```

### Typical tilt angle for Spain

Spain spans roughly 36–43°N. Marc's own `data/pvgis.csv` (PVGIS optimal fixed-tilt angle, per grid cell, already fetched by his pipeline) gives an **empirical answer directly from his own data**: min 12°, max 41°, mean **35.4°** across 5,289 Spanish grid cells (the low outliers are likely elevation/microclimate edge cases; the bulk clusters in the low-to-mid 30s, consistent with general "optimum tilt ≈ latitude, roughly" guidance — [pvgis.com tilt guide](https://pvgis.com/en/blog/solar-panel-tilt-angle-calculation), [ratedpower.com](https://ratedpower.com/blog/pv-panel-tilt/)). At θ = 35°: `cos(35°) ≈ 0.819`, so a nadir photo would show only ~82% of the true tilted panel surface area — true area is ~1.22× the nadir footprint. Non-trivial if the wrong quantity is used unknowingly, which is exactly why this needs to be stated explicitly rather than hand-waved.

### Ground coverage ratio (GCR) — the second, separate effect

Independent of tilt-foreshortening of a *single* panel, real ground-mount arrays space rows apart by a **pitch R > L'** specifically to avoid inter-row self-shading at low sun angles (worst case: winter solstice). **Ground Coverage Ratio, GCR = L'/R** — the fraction of the *array field* (not the whole leased parcel) that is actually panel, versus bare/gravel/grass gap between rows. Typical fixed-tilt engineering values: **GCR ≈ 0.35–0.55**, with 0.38–0.42 commonly cited as a standard target for mid-latitude fixed-tilt designs, and values up to ~0.55 usable at lower latitudes with acceptable shading loss ([GCR overview, ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0038092X23002682), [detrasolar.com](https://detrasolar.com/understanding-ground-covering-ratio-gcr-in-solar-pv-systems/), [ratedpower.com](https://ratedpower.com/blog/pv-panel-tilt/)).

Note this is a different number from `build_sites.py`'s hard-coded "0.6 bbox fill" assumption used today to estimate untagged farms' capacity — that 0.6 is a *bounding-box* fill fraction (a looser, cruder proxy), not a GCR measured against the true parcel or array-field boundary. This is precisely the kind of assumption the segmentation project would let Marc replace with a measured, per-site number.

### Four distinct quantities — don't conflate them

| # | Quantity | What it is | How to get it |
|---|---|---|---|
| (a) | **True panel module surface area** | The actual tilted glass/cell surface — a physical, non-projected quantity | `A_nadir / cos θ`, or from known module specs directly |
| (b) | **Nadir-image apparent panel footprint** | Literally the pixels a segmentation model paints as "panel material," summed | Direct output of the segmentation model — no correction |
| (c) | **Row-pitch-inclusive field footprint** | The polygon enclosing the whole planted block of rows (panels *and* the gaps between them), excluding access roads/substations outside the array itself | Convex hull / bounding polygon of the union of all row masks in a site |
| (d) | **OSM land-parcel polygon area** | The full fenced/leased site boundary — includes (c) *plus* internal roads, inverter/transformer pads, security buffer, unused corners | OSM `power=plant` way/relation polygon (needs a re-fetch with `out geom;`, see grounding section above — bbox alone overstates this) |

### Which pair should Marc use, and should he tilt-correct?

**Use (b) as the numerator, uncorrected — no `cos θ` correction.** Tilt-correcting the segmentation output to recover (a) would answer a different question (how much glass/cell surface exists, an electrical-engineering quantity) than the one Marc actually cares about (how efficiently is this parcel of *land* being used, a siting/land-use quantity). Both the segmentation mask and the OSM parcel polygon are ground-plane (planimetric) quantities — comparing a slant-corrected area against a flat-ground area would mix two different area definitions and *inflate* the ratio in a way that has nothing to do with actual land occupation.

**Use (d), the OSM land-parcel polygon, as the primary denominator** — `coverage_ratio = (b) / (d)`. This is the statistic that actually matches his stated goal ("packing-density / land-use-efficiency statistic per site" against the parcel he's evaluating in the broader siting model), and it is the number a viewer of the public map would intuitively expect "coverage ratio" to mean: how much of this parcel is actually solar, versus support infrastructure/buffer/unused land.

**Also compute (b)/(c) as a secondary, diagnostic ratio** — an empirical GCR. Since real fixed-tilt GCR sits in a known, narrow band (~0.35–0.55), any site whose (b)/(c) falls far outside that band is a strong automatic signal of a segmentation problem (over/under-segmentation, cloud shadow false positives, mistaking a rooftop or bare soil for panel, or — separately — a case where the OSM bbox/polygon itself is a bad proxy for the actual parcel). This turns a known engineering constant into a free QA check across all 3,215 sites, without any manual review.

---

## 5. Recommended minimal pipeline

Python-first, consistent with the existing `pipeline/` conventions (plain `requests`, resume-safe disk caches, `ThreadPoolExecutor` for I/O, `PIL`/`numpy` for raster decode):

1. **Sort** `data/solar_farms.json` by `capacity_MW` descending — trivial, one line, start with top 50–100.
2. **Recover per-site geometry.** Today's `solar_farms.json` only carries the farm centroid, not its source OSM id/bounds — join back to `osm_solar.json` by nearest-centroid match, or (better) have `build_sites.py` retain the OSM id/bounds per farm going forward. **Re-fetch OSM with `out geom;`** (not the current `out center bb tags qt;`) for these 3,255 elements so a true polygon — not just a bbox — is available for denominator (d). This is a small, targeted addition to `fetch_osm.py`, not a new pipeline.
3. **Fetch imagery**: one **PNOA WMS `GetMap`** HTTP call per site, bbox padded ~20–30% beyond the OSM polygon's bounding box, requesting WIDTH/HEIGHT sized for ≈0.25m/pixel. Cache to disk (mirror the `terrain_tiles/`-style cache-directory pattern already used in `fetch_terrain.py`), resume-safe.
4. **Segment**: run **MobileSAM or SAM ViT-B via [segment-geospatial (samgeo)](https://github.com/opengeos/segment-geospatial)**, prompted with a box (the OSM polygon's bbox, shrunk slightly inward) — box prompts reportedly outperform point prompts per the remote-sensing SAM literature (§1a) — falling back to a point prompt at the farm centroid if no usable OSM geometry exists for that site. `samgeo` operates directly on georeferenced rasters and can output either a georeferenced mask raster or already-vectorized polygons.
5. **Vectorize**: prefer `samgeo`'s built-in raster→vector utilities first; fall back to `rasterio.features.shapes` + `shapely` (simplify/buffer) or OpenCV `findContours` + `shapely` only if its output isn't clean enough.
6. **Compute the two ratios** per site: `(b)/(d)` (primary coverage ratio) and `(b)/(c)` (GCR-band QA check), using `shapely`/`geopandas` for area math in an equal-area or local UTM projection (not raw lat/lon degrees).
7. **Persist**: extend `solar_farms.json` (or a new sidecar `solar_coverage.json`) with the new fields, feeding into the existing `pipeline/pack_web.py` step the same way other layers already reach the public map.
8. **"Paint everything in one run"**: once step 4–6 has run for all 3,215 sites, `geopandas`/`shapely.ops.unary_union` merges every site's panel polygon into one layer, exported as GeoJSON in the same packing convention `pack_web.py` already uses for other layers — this is a pure vector-merge step requiring no additional segmentation work, since by then every site already has its own polygon.

**Libraries to add**: `segment-geospatial` (pulls in `torch`, SAM/SAM2, `rasterio`, `geopandas` as dependencies), plus `shapely` if not already present. Everything else (`requests`, `numpy`, `PIL`) is already in the stack.

---

## 6. Citations

**Segmentation models / tools**
- Segment Anything (SAM), Meta — [github.com/facebookresearch/segment-anything](https://github.com/facebookresearch/segment-anything)
- SAM2 — [github.com/facebookresearch/sam2](https://github.com/facebookresearch/sam2)
- MobileSAM — [github.com/ChaoningZhang/MobileSAM](https://github.com/ChaoningZhang/MobileSAM)
- segment-geospatial (samgeo) — [github.com/opengeos/segment-geospatial](https://github.com/opengeos/segment-geospatial), docs [samgeo.gishub.org](https://samgeo.gishub.org/)
- SAM for remote sensing (zero/one-shot) — [arxiv.org/abs/2306.16623](https://arxiv.org/abs/2306.16623), [ScienceDirect version](https://www.sciencedirect.com/science/article/pii/S1569843223003643)
- Grounded-SAM explainer — [viso.ai/deep-learning/grounded-sam](https://viso.ai/deep-learning/grounded-sam/)
- Zero-shot text-prompted remote sensing segmentation (SAM + Grounding DINO) — [sciencedirect.com/science/article/pii/S2666544125000012](https://www.sciencedirect.com/science/article/pii/S2666544125000012)

**Solar-specific models/datasets**
- DeepSolar — [github.com/wangzhecheng/DeepSolar](https://github.com/wangzhecheng/DeepSolar)
- DeepSolar-3M — [github.com/rajanieprabha/DeepSolar-3M](https://github.com/rajanieprabha/DeepSolar-3M)
- U-Net solar segmentation — [github.com/gabrieltseng/solar-panel-segmentation](https://github.com/gabrieltseng/solar-panel-segmentation)
- NREL Panel-Segmentation — [github.com/NREL/Panel-Segmentation](https://github.com/NREL/Panel-Segmentation)
- PV01/PV03/PV08 multi-resolution dataset — Zenodo [10.5281/zenodo.5171712](https://zenodo.org/records/5171712), paper [ESSD 13, 5389 (2021)](https://essd.copernicus.org/articles/13/5389/2021/)
- Multi-resolution segmentation comparison (U-Net/DeepLabv3/Mask2Former) — [mdpi.com/2072-4292/15/24/5687](https://www.mdpi.com/2072-4292/15/24/5687)
- SolarFormer — [arxiv.org/pdf/2310.20057](https://arxiv.org/pdf/2310.20057); SolarFormer++ — [github.com/UARK-AICV/SolarFormerPlusPlus](https://github.com/UARK-AICV/SolarFormerPlusPlus); S3Former — [arxiv.org/html/2405.04489v1](https://arxiv.org/html/2405.04489v1)
- Crowdsourced solar array dataset — [arxiv.org/pdf/2209.03726](https://arxiv.org/pdf/2209.03726)

**Imagery**
- PNOA services index (IGN) — [pnoa.ign.es/pnoa-imagen/visualizadores-y-servicios-web](https://pnoa.ign.es/pnoa-imagen/visualizadores-y-servicios-web)
- PNOA WMS GetCapabilities (verified live) — `https://www.ign.es/wms-inspire/pnoa-ma?Request=GetCapabilities&Service=WMS`
- PNOA WMTS GetCapabilities (verified live) — `https://www.ign.es/wmts/pnoa-ma?Request=GetCapabilities&Service=WMTS`
- Sentinel-2 band resolutions — [developers.google.com/earth-engine/datasets/catalog/sentinel-2](https://developers.google.com/earth-engine/datasets/catalog/sentinel-2)
- Esri terms of use — [esri.com/en-us/legal/terms/web-site-service](https://www.esri.com/en-us/legal/terms/web-site-service)

**Hardware**
- PyTorch MPS backend notes — [huggingface.co/docs/transformers/en/perf_train_special](https://huggingface.co/docs/transformers/en/perf_train_special), [lightning.ai/docs/pytorch/stable/accelerators/mps_basic](https://lightning.ai/docs/pytorch/stable/accelerators/mps_basic.html)

**Geometry**
- Solar panel tilt/latitude guidance — [pvgis.com tilt guide](https://pvgis.com/en/blog/solar-panel-tilt-angle-calculation), [ratedpower.com](https://ratedpower.com/blog/pv-panel-tilt/)
- Ground coverage ratio (GCR) — [ScienceDirect: optimal GCR for tracked/fixed/vertical PV](https://www.sciencedirect.com/science/article/pii/S0038092X23002682), [detrasolar.com GCR explainer](https://detrasolar.com/understanding-ground-covering-ratio-gcr-in-solar-pv-systems/)
- Standard module dimensions — [solarreviews.com panel size guide](https://www.solarreviews.com/blog/complete-guide-to-solar-panel-size), [unboundsolar.com](https://www.unboundsolar.com/blog/solar-panel-size-guide)

**Where I could not fully verify a claim**, I've flagged it inline above (SAM2's reported improvement on small PV cells in low-res imagery; whether SolarFormer/SolarFormer++ ship a downloadable trained checkpoint; exact SAM ViT-L file size). Recommend Marc spot-check those specific points against the primary repos before relying on them.
