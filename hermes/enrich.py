#!/usr/bin/env python3
"""Enrichment loop for dc_watch v2: backfill the sparse projects (name+location, nothing else)
by searching per-project, extracting structured facts, and piping them through the SAME resolver
(so enrichment can't misattribute facts to the wrong project) and the SAME ingest path (so every
enriched fact carries source + tier + confidence).

Strategy: a thorough one-time backfill, then a rolling re-visit of the N stalest projects/day.
search_fn and extract_fn are injected so the whole flow is testable offline with zero tokens; the
production defaults (Google-News RSS + DeepSeek) live at the bottom.
"""
from datetime import date

import ingest
import kb
import resolver

ARTICLES_PER_PROJECT = 3   # how many search hits to feed the extractor (cost + Google-load knob)
TRUNC = 3500               # chars of each article sent to the LLM (cost knob)

# extract_fn contract:
#   extract_fn(project: dict, articles: list[dict]) -> {
#     "about_this_project": bool,          # LLM's own guard: are these articles really this project?
#     "fields": [ {"attribute": "mw"|"investment_eur_m"|"company"|"status"|"type",
#                  "value_num": float|None, "value_text": str|None,
#                  "unit": str|None, "source_idx": int} ]   # source_idx → articles[i]
#   }


def stale_projects(con, n):
    """The N projects most in need of enrichment: never-enriched first, then oldest-enriched."""
    # never-enriched first, then least-recently-touched-by-ANYTHING. Because ordering falls back to
    # updated_at, a project the news loop just refreshed sinks down the queue — enrichment spends its
    # budget where news ISN'T looking, instead of competing with it.
    rows = con.execute(
        "SELECT e.id, e.canonical_name, e.region, e.lat, e.lon, "
        "(SELECT value_text FROM observations o WHERE o.entity_id=e.id AND o.attribute='company' "
        " ORDER BY id DESC LIMIT 1) AS company "
        "FROM entities e WHERE e.lat IS NOT NULL "
        "ORDER BY (e.last_enriched IS NOT NULL), "
        "         COALESCE(e.last_enriched, e.updated_at, '2000-01-01') ASC, e.id LIMIT ?", (n,))
    return [dict(zip(["id", "name", "region", "lat", "lon", "company"], r)) for r in rows]


def clean_company(comp):
    """Return the company string only if it looks like an actual NAME, else None. Some seed rows
    stored polluted free-text in this field (e.g. 'Hyperscale; national water-controversy reference
    case') which wrecks both search queries and the LLM's project anchor."""
    comp = (comp or "").strip()
    if comp and len(comp.split()) <= 4 and not any(p in comp for p in ";,.:") and comp != "?":
        return comp
    return None


def build_query(project):
    """The core subject string for the search — the project name, plus the company if it looks
    clean. Deliberately UNQUOTED: exact-phrase quoting the full name returns almost nothing on
    Google News, while a loose token query returns the right articles. The edition-specific topic
    term ('centro de datos' / 'data center') is appended in rss_search."""
    name = project.get("name", "") or ""
    comp = clean_company(project.get("company"))
    if comp and kb.alias_key(comp) not in kb.alias_key(name):
        return f"{name} {comp}".strip()
    return name.strip()


def _same_project(con, project, article_mention):
    """Guard: does an article's extracted mention actually refer to THIS project? If it resolves
    to a DIFFERENT existing entity with confidence, the search drifted — reject those facts."""
    dec = resolver.resolve(con, article_mention)  # no LLM in the guard; deterministic only
    if dec["decision"] == "match" and dec.get("entity_id") not in (None, project["id"]):
        return False   # confidently about a different project
    return True


def enrich_project(con, project, search_fn, extract_fn, run_id):
    """Search → extract → guard → apply. Always stamps last_enriched so the queue advances even
    when nothing is found (a project with no news shouldn't be retried every single day)."""
    out = {"id": project["id"], "found": 0, "applied": [], "skipped": 0}
    articles = (search_fn(build_query(project)) or [])[:ARTICLES_PER_PROJECT]
    if articles:
        ext = extract_fn(project, articles) or {}
        if ext.get("error"):
            # a failed LLM call must NOT advance the queue, or the project is lost until it happens
            # to come round again — leave last_enriched untouched so it retries next run.
            out["error"] = ext["error"]
            return out
        if ext.get("about_this_project", True):
            for f in ext.get("fields", []):
                idx = f.get("source_idx", 0)
                art = articles[idx] if 0 <= idx < len(articles) else {}
                # per-field guard using the article's own mention of the project
                mention = {"name": project["name"], "company": project.get("company"),
                           "municipality": project.get("region"),
                           "lat": project.get("lat"), "lon": project.get("lon")}
                if not _same_project(con, project, mention):
                    out["skipped"] += 1
                    continue
                r = ingest.apply_observation(
                    con, project["id"], f["attribute"],
                    value_num=f.get("value_num"), value_text=f.get("value_text"),
                    unit=f.get("unit"), source_url=art.get("url"),
                    tier=kb.tier_for(art.get("source")), reported_date=art.get("published"),
                    run_id=run_id)
                out["found"] += 1
                if r["changed"]:
                    out["applied"].append(f"{f['attribute']}={r['new']}")
                # record the article so it shows in the project's news trail
                if art.get("url"):
                    try:
                        con.execute("INSERT OR IGNORE INTO news(entity_id,url,source,source_tier,date,"
                                    "title,event_type,summary,run_id) VALUES(?,?,?,?,?,?,?,?,?)",
                                    (project["id"], art.get("url"), art.get("source"),
                                     kb.tier_for(art.get("source")), art.get("published"),
                                     art.get("title"), "enrichment", None, run_id))
                    except Exception:
                        pass
    con.execute("UPDATE entities SET last_enriched=? WHERE id=?", (date.today().isoformat(), project["id"]))
    return out


def run_enrichment(con, n, search_fn, extract_fn, run_id):
    con.execute("INSERT OR IGNORE INTO runs(run_id,type,started_at) VALUES(?,?,?)",
                (run_id, "enrich", date.today().isoformat()))
    projects = stale_projects(con, n)
    results = [enrich_project(con, p, search_fn, extract_fn, run_id) for p in projects]
    n_enriched = sum(1 for r in results if r["applied"])
    con.execute("UPDATE runs SET finished_at=?, n_enriched=?, notes=? WHERE run_id=?",
                (date.today().isoformat(), n_enriched,
                 f"visited {len(projects)}, applied to {n_enriched}", run_id))
    con.commit()
    return results


# ---------------- cost model ----------------
def estimate_cost(n_projects, *, articles=ARTICLES_PER_PROJECT, trunc=TRUNC,
                  price_in_per_m, price_out_per_m, prompt_overhead=400, out_tokens=350):
    """Rough token + $ estimate. 1 token ≈ 4 chars. One LLM call per project (articles batched)."""
    in_tokens = prompt_overhead + articles * (trunc / 4)
    tot_in = in_tokens * n_projects
    tot_out = out_tokens * n_projects
    cost = tot_in / 1e6 * price_in_per_m + tot_out / 1e6 * price_out_per_m
    return {"in_tokens": int(tot_in), "out_tokens": int(tot_out),
            "in_per_project": int(in_tokens), "usd": round(cost, 4)}


# ---------------- production defaults (used by dc_watch.py, not by tests) ----------------
def rss_search(query, editions=(("es", "ES", "ES:es", "centro de datos"),
                                 ("en", "US", "US:en", "data center"))):
    """Query Google News in Spanish AND English editions and merge (dedup by URL), so international
    trade press covering Spanish projects is captured too. Each edition appends its own topic term
    and a 12-month recency window. Fetches article text for the top hits."""
    import time
    import feedparser, trafilatura  # noqa: local import so tests never need these installed
    seen, arts, net_error = set(), [], False
    for hl, gl, ceid, topic in editions:
        if len(arts) >= ARTICLES_PER_PROJECT:
            break
        time.sleep(1.2)   # politeness — Google News returns empty feeds under rapid-fire querying
        full = f"{query} {topic} when:365d"
        url = ("https://news.google.com/rss/search?q=" +
               requests.utils.quote(full) + f"&hl={hl}&gl={gl}&ceid={ceid}")
        try:
            fd = feedparser.parse(url)
            if not fd.entries:        # Google rate-limits rapid queries → back off once and retry
                time.sleep(3.0)
                fd = feedparser.parse(url)
        except Exception:             # RemoteDisconnected etc under throttling — back off, skip edition
            net_error = True
            time.sleep(6.0)
            continue
        for e in fd.entries[:ARTICLES_PER_PROJECT]:
            if len(arts) >= ARTICLES_PER_PROJECT:
                break
            link = e.get("link", "")
            if not link or link in seen:
                continue
            seen.add(link)
            try:
                # Google News RSS links are ENCODED redirect wrappers — fetching them yields no
                # article body. Decode to the real URL first (else the LLM sees only the headline).
                real = link
                if "news.google.com" in link:
                    from googlenewsdecoder import new_decoderv1
                    d = new_decoderv1(link)
                    if not (d.get("status") and d.get("decoded_url")):
                        continue
                    real = d["decoded_url"]
                html = trafilatura.fetch_url(real)
                text = (trafilatura.extract(html) or "")[:TRUNC] if html else ""
            except Exception:
                continue              # any per-article network hiccup: skip that article, keep going
            if len(text) < 120:
                continue   # paywalled/unreadable — no usable body, skip rather than feed a title-only stub
            # feedparser gives RFC-822 dates ("Mon, 14 Jul 2026 …"); convert to ISO so recency works
            pp = e.get("published_parsed")
            iso = time.strftime("%Y-%m-%d", pp) if pp else None
            arts.append({"url": real, "title": e.get("title", ""),
                         "source": (e.get("source", {}) or {}).get("title", "google news"),
                         "published": iso, "text": text})
    # a throttle that produced NO articles must not look like "genuinely no news" (which would get
    # the project falsely stamped done) — signal it so the caller skips + retries next run.
    if not arts and net_error:
        raise RuntimeError("google news throttled (network error, no articles)")
    return arts[:ARTICLES_PER_PROJECT]


try:
    import requests  # only needed by the production rss_search / deepseek_extract
except Exception:
    requests = None

# NOTE ON CACHING: this prompt is a STABLE PREFIX — byte-identical on every call — so DeepSeek's
# automatic prefix cache charges it at the cache-HIT rate ($0.0028/M) for every project after the
# first in a run. That lets it be long and example-rich (better extraction) at ~zero added cost.
# The only cache-MISS tokens are the per-project articles, appended strictly AFTER this block.
EXTRACT_PROMPT = """You are a data-center infrastructure analyst. Given ONE known project and a set
of news articles (Spanish or English), extract ONLY facts you are highly confident refer to THIS
specific project. Do not invent; omit anything not stated. Return JSON:
{"about_this_project": bool,   // false if the articles are not about this specific project
 "fields": [
   {"attribute": "mw"|"investment_eur_m"|"company"|"status"|"type",
    "value_num": number|null,   // mw = capacity in MW (IT load if stated); investment_eur_m = MILLIONS of EUR
    "value_text": string|null,  // company = developer/owner; status = announced|land|permit|construction|operating|cancelled; type = hyperscale|colocation|edge|ai
    "unit": string|null, "source_idx": int}   // source_idx = index of the article backing this fact
 ]}

Rules:
- If a source gives a range (e.g. "€500M–€1B"), report the figure it presents as current/most likely.
- Convert billions to millions (€1.2 bn → 1200). Convert GW to MW (0.3 GW → 300).
- 'status': land purchase → "land"; permit/licence granted → "permit"; groundbreaking/works started → "construction"; live/operational → "operating".
- Only set company to the developer/operator/owner, never a mere contractor or journalist's employer.

Example input: project "AWS Aragón", articles: [0] "Amazon invertirá 1.500 millones en un centro de datos de 200 MW en construcción en Villanueva".
Example output: {"about_this_project": true, "fields": [
  {"attribute":"investment_eur_m","value_num":1500,"unit":"EUR_m","source_idx":0},
  {"attribute":"mw","value_num":200,"unit":"MW","source_idx":0},
  {"attribute":"status","value_text":"construction","source_idx":0},
  {"attribute":"company","value_text":"Amazon","source_idx":0}]}"""


def deepseek_extract(project, articles, *, api_key=None, model=None, retries=2):
    """Production extractor: one DeepSeek V4-Flash call per project (articles batched). The stable
    EXTRACT_PROMPT goes first (cache-hit); the variable project+articles block goes last (cache-miss).

    Transient errors are retried and, if still failing, surfaced as {"error": ...} — NOT masked as a
    false 'about_this_project: False', which would look like the model judged the articles irrelevant.
    """
    import json
    import os
    import sys
    import time
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    comp = clean_company(project.get("company")) or "?"
    ctx = (f"\n\n=== TASK INPUT ===\nPROJECT: {project.get('name')} | company: {comp} | "
           f"area: {project.get('region') or '?'}\n\nARTICLES:")
    for i, a in enumerate(articles):
        ctx += f"\n[{i}] {a.get('title','')}\n{(a.get('text') or '')[:TRUNC]}\n"
    payload = {"model": model, "response_format": {"type": "json_object"},
               "messages": [{"role": "user", "content": EXTRACT_PROMPT + ctx}],
               "temperature": 0.1, "max_tokens": 800}
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.post("https://api.deepseek.com/chat/completions",
                              headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=120)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:150]}"
                time.sleep(2 * (attempt + 1)); continue
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    print(f"   [deepseek_extract failed after {retries + 1} tries: {last}]", file=sys.stderr)
    return {"fields": [], "error": last}   # no 'about_this_project' → caller sees an error, not a verdict
