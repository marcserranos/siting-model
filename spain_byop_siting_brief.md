# Spain BYOP Datacenter Siting Model — Research Brief

*Written 2026-07-06. This supersedes `siting_model_vision.md`, `spain_ai_infra_thesis.md`, `spain_ai_infra_learning_plan-2.md`, and `marc_thesis_context.md` for the purposes of this project. Those docs reflected an earlier direction (deal-by-deal syndication into AGI-infrastructure companies) that is no longer the objective. This document is self-contained — do not assume the reader has seen the other files or this conversation.*

**How to use this doc:** this is a brief for a *research phase*, not a build spec. The scope decisions below (marked "locked") are genuinely fixed — don't relitigate them. Everything marked as an open question is genuinely open — don't silently resolve it by picking the most obvious-sounding answer; surface it back for a decision once you have real information (data availability, what a source actually contains, etc.).

---

## Operating protocol for this handoff

Marc wants high autonomy here, not a back-and-forth clarifying-questions loop. Work in two phases, then stop for a checkpoint:

1. **Phase 1 — Research.** Actually go find out: what's downloadable vs. merely browsable on MITECO Geoportal, what the "oferta y demanda" layers contain, whether PVGIS/AEMET have usable solar and climate data for Spain, what catastro access actually looks like in practice, and what real primary material exists on regional/municipal political reception of datacenters (Aragon's fast-tracking, any other region's resistance). Resolve as many of the open questions in this doc as the evidence allows. Where evidence is genuinely inconclusive, say so plainly rather than guessing.
2. **Phase 2 — High-level plan.** Based on what Phase 1 actually found (not on assumptions made before finding it), produce: a recommended unit of analysis, a narrowed variable shortlist with reasoning for what got cut, a proposed approach to the scoring/weighting mechanism, a rough data pipeline sketch, and an honest read on how much of the aspirational end-state (toggleable live-reweighted map, size-mode partitioning) is realistically buildable in the remaining timeline versus what should be deferred.
3. **Checkpoint — stop here.** Do not proceed to implementation/code until this plan has been reviewed. Come back with the completed research + plan and a short list of the real forks that need Marc's judgment call, rather than mid-stream questions. Exercise judgment and take positions on the open questions rather than punting all of them back — but flag which of your positions are confident calls versus close judgment calls Marc might want to weigh in on.
4. **Self-checkpointing.** Given session/context limits are a real constraint here, maintain a running progress log (what's been checked, what was found, what's still open) and update it at natural breakpoints — end of each research question, not just at the very end — so that if the session cuts off mid-task, the work up to that point is not lost and is resumable.

---

## Objective

Marc is applying to SemiAnalysis (an intelligence firm that sells research to hyperscalers and hedge funds). He has already spoken informally with a recruiter there — no formal task was given, no grading rubric exists, Marc proposed the idea himself. The recruiter reacted positively to the general direction. Marc has roughly one week before he talks to them again, and wants to use that week to build a real work sample: a model that identifies and ranks good sites in Spain for datacenter construction.

The dual purpose is explicit: this is both a recruiting artifact and a genuine learning vehicle. Depth and correctness matter more than polish or breadth.

---

## Recruiter signal (context, not spec)

In the informal conversation, Marc pitched sun exposure and BYOP framing. The recruiter's own instincts leaned toward a more conventional variable set: grid connection quality, proximity to other datacenters, proximity to gas pipelines, plus sun exposure. He warned that too many variables without a throughline produces something inconclusive rather than sharp, and suggested narrowing down — but did not specify to what. All of this was said very informally, off the cuff — treat it as color and raw candidate variables, not as a spec or a final list.

Variables raised so far, from both sides, none final:

- **From the recruiter:** grid connection quality/proximity, proximity to other datacenters, proximity to gas pipelines, sun exposure.
- **From Marc:** proximity to population centers — genuinely ambiguous in direction. Closer could mean better networking/fiber/labor access, but also more exposure to local social pushback once a community starts objecting to a datacenter's water/power/noise footprint. Given that local political/social reception is already flagged as a core layer above (Aragon fast-tracking vs. other regions resisting), population proximity may end up as an input to that reception layer rather than a standalone distance metric — worth exploring both framings rather than assuming one.

None of these variables are locked. The instruction to carry forward is: everything above is open for exploration, but the goal is to narrow the final variable set down as much as possible — a sharp model on a few well-argued variables beats a broad one on many. The one variable that *is* locked, per the scope section below, is the framing around **bring-your-own-power / behind-the-meter siting** — that's the throughline the rest should narrow toward, not away from. This is a deliberate divergence from the recruiter's own grid-centric leanings, made with eyes open: it's not that grid/gas/proximity variables are wrong, it's that Marc is betting the sharper, more differentiated thesis is "where can you build without waiting on the grid at all," and that a scattershot multi-variable model — not the specific choice of variables — was the recruiter's actual complaint.

---

## Core thesis (compressed)

Data centers will be the most power- and permitting-constrained buildable asset on the planet over the next decade, and Europe is structurally behind on the ability to site them fast. Spain specifically:

- ~83% of Spain's grid connection nodes are reported at full capacity (as of the last check — verify current figure, this moves).
- Grid interconnection approval can take up to ~4 years.
- Tens of billions of euros in investment are stalled on grid access nationally.
- Spain hit a record month of renewable curtailment in July 2025 — curtailing generation it cannot deliver to demand, in the same country/moments where interconnection queues are years long. This is the core anomaly BYOP siting exploits: generation and demand potential co-exist without a grid link between them.
- The April 2025 Iberian peninsula blackout is a live reminder that grid fragility is not hypothetical.

**The bet:** if grid interconnection is the actual multi-year bottleneck, the sites worth finding are the ones where a data center could be powered *without* going through that queue at all — behind-the-meter solar + battery, sited on land with the right combination of solar resource, buildable terrain, low environmental-permitting friction, and (this is the genuinely underexplored part) local/regional political appetite for fast-tracking this kind of build. This is a demand-siting problem, not a generation-siting problem — compute doesn't care about resource quality the way a solar developer does; it cares about firm, reliable power delivered on-site, plus land, plus (eventually, downstream) connectivity.

---

## Scope decisions (locked for this build)

- **BYOP / off-grid only.** The model exclusively surfaces and ranks sites for behind-the-meter solar+battery+datacenter co-location. Grid-tied siting variables (interconnection capacity, substation proximity) are explicitly out of scope for v1 — not because they're unimportant in general, but because this is the differentiated bet being made (see recruiter signal above).
- **Geography: whole Spain, not pre-narrowed.** Marc's reasoning: most of the relevant public data appears to come from the same national sources (see MITECO Geoportal below), so restricting to one region likely doesn't meaningfully reduce data-acquisition difficulty. Default to national coverage. Pivot to a regional subset (Aragon and/or Extremadura are the standing fallback candidates, given known solar resource and existing datacenter developer interest there) only if a specific data source turns out to be genuinely regional-only or the national version proves intractable.
- **Output form: deliberately undecided on stack, but there is an aspirational end-state worth designing toward from the start.** Marc's own words: forcing the *tech stack* decision early is "the kind of question that collapses the project too early" — UI is considered cheap and secondary, expected to be built quickly with coding agents once data/methodology is solid. Do not spend the research phase deciding UI stack. But the *shape* of the ideal end-state is worth stating now, because it has real implications for how the data and scoring layer need to be designed underneath:
  - A fully interactive map where every variable/layer is toggleable on/off.
  - A heatmap view of composite scores, which updates live as the user changes what's included.
  - The user can pick which variables factor into the score, assign relative weights to them, and possibly reorder/prioritize them via some kind of programmable heuristic — with the map recomputing live as these are adjusted, not requiring a re-run/rebuild.
  - Clicking a location/parcel surfaces supporting detail — why it scored the way it did, what each underlying layer said there.
  - A **size/mode selector** — e.g. "1 GW campus" vs. a much smaller "100 kW edge site" mode — where the model scouts for and aggregates terrain that actually meets the land + power + siting requirements for that scale, rather than presenting one fixed unit regardless of project size.
  - This last point has a direct consequence for the "unit of analysis" open question below: a single fixed unit (one parcel, one grid cell) is unlikely to serve both a gigawatt-campus search and a 100kW edge-site search. The underlying data likely needs to be a fine-grained base layer (small parcels/cells) that can be dynamically aggregated into larger contiguous candidate areas depending on the selected scale — worth designing for this from the start even if only the small-scale or only the large-scale mode ships first given the one-week timeline.
- **Timeline: ~1 week** for the full build, before Marc talks to the recruiter again. This means the research phase itself should be days, not weeks — move toward a working v1 with known-imperfect data rather than chasing complete data first.

---

## Known data leads (seed list — verify, expand, don't treat as exhaustive)

- **MITECO Geoportal** (`sig.mapama.gob.es/geoportal/`) — the main Spanish government environmental GIS portal. Confirmed layers Marc has already viewed:
  - "Energía fotovoltaica. Índice de sensibilidad ambiental" (photovoltaic environmental sensitivity index) — scored numerically (example seen: value 10.000, classified as "Baja"/Low).
  - "Energía eólica. Mapa de sensibilidad ambiental" (wind environmental sensitivity map).
  - Marc has also seen "supply and demand" ("oferta y demanda") layers on the same portal — likely grid-related, unconfirmed relevance given BYOP-only scope, worth checking what these actually contain before dismissing.
  - Open problem: these layers are browsable in the web GIS viewer but it's unconfirmed whether they're bulk-downloadable in a standardized format (shapefile/GeoTIFF/etc.) rather than just viewable. This is itself one of the two structural problems below — resolve it early, it gates everything else.
- **Catastro** (Sede Electrónica del Catastro) — cadastral parcel data, including ownership and parcel status. Flagged by Marc as possibly overkill or hard to parse at national scale, but potentially valuable applied narrowly — e.g., only for the top-N candidate sites the model surfaces, to answer "who owns this land and what's its legal state" rather than as a national-scale input layer.
- **Solar irradiance / sun exposure** — not yet found in the Geoportal layers Marc has seen. Likely candidates to check: PVGIS (EU Joint Research Centre's solar irradiance database, standard for this), AEMET (Spain's meteorological agency), or a direct API.
- **Climate/weather data (rain, cloud cover, etc.)** — unexplored. Marc's own hypothesis, stated tentatively and not verified: rain might actually be a *positive* for panel performance (cleans panels) rather than a negative, contrary to naive intuition — this needs actual investigation, not assumption either way. Candidate source: a weather API, or AEMET historical climate series.
- **Geo-legal / regulatory & political reception layer** — Marc considers this a core, high-value, and genuinely hard-to-model part of the project. The observation motivating it: Aragon is reportedly loosening/fast-tracking regulation specifically to accelerate datacenter buildout, which suggests regional and municipal political appetite varies substantially and is a real siting variable — but it's interpretive and non-deterministic in a way the other (numeric, geospatial) layers aren't. How to encode this (a score? a qualitative annotation layer displayed alongside the quantitative ranking? case studies per region?) is an open methodological question, not a solved one — see open questions below.

---

## The two structural problems (solve first, they gate everything)

1. **Data fragmentation and access, not data absence.** Marc's read, likely correct: the Spanish government has a lot of relevant maps, but they're siloed across portals/agencies and often only browsable through web GIS viewers rather than bulk-downloadable in a standardized format. Confirming what's actually downloadable (and in what format, at what resolution) versus merely viewable is close to the first real task of the research phase — it determines what's even buildable in a week.
2. **Some needed layers don't appear to exist pre-assembled at all** — notably solar irradiance/climate (may need PVGIS/AEMET/a weather API, unconfirmed) and the regulatory-reception layer (which likely doesn't exist as a dataset anywhere and needs to be constructed from primary documents/news/regulatory filings on a per-region basis).

---

## Principles carried forward (from the prior vision doc — still hold)

- Primary sources over secondary narrative — a regulatory filing or published dataset outranks an article describing it.
- Falsifiable over impressive — a precise claim that could be wrong beats a confident synthesis that can't be checked.
- Mechanistic over thematic — explain *why* a location works, not just that it scores well on a composite index.
- Preserve uncertainty from source data (e.g., an environmental sensitivity score's caveats) rather than laundering it into a clean number.
- Legible to a skeptical expert — every output should survive a conversation with someone who actually develops these sites for a living, not just look good to a general audience.
- Not trying to be comprehensive across Europe, not trying to incorporate every exotic data layer (e.g. satellite ML embeddings) before a simpler correct version exists, not trying to duplicate existing renewable-siting tools — the wedge is compute-specific, BYOP-specific siting, not redoing grid-capacity visualization that already exists elsewhere.

---

## What "done" looks like for this one-week v1

Someone with real domain expertise in Spanish energy/infrastructure (or the SemiAnalysis recruiter) looks at the specific sites the model surfaces and reacts with "huh, I hadn't thought about that spot" or "that's roughly right, here's the nuance you're missing" — not "this is just a renewables suitability map with extra steps" and not "this is 15 variables and no clear conclusion." Given the one-week constraint, a defensible, narrow, mechanistically-argued v1 beats a broad but shallow one.

---

## Open questions — resolve during/after research, not now

- **Unit of analysis.** Is a "candidate site" a parcel, a municipality, a grid-free zone, a raster cell? This shapes the entire scoring and data-join design and should be decided once the actual resolution of available layers (Geoportal, catastro, solar data) is known.
- **Does pure BYOP survive contact with the data?** It's possible that even off-grid sites end up needing *some* grid signal (e.g. minimal grid tie for redundancy/export of excess solar) — worth staying alert to whether the data itself pushes back on the strict off-grid framing.
- **How to encode the geo-legal/regulatory-reception layer.** Score, annotate, or narrative case-study — genuinely undecided, and probably the most novel/differentiated part of the whole project if solved well.
- **Catastro depth.** Whether cadastral ownership data is worth pursuing at all, and if so, only for a short-listed set of top candidates rather than nationally.
- **Output form**, per the scope section above — deliberately deferred, revisit once data/methodology is solid.
