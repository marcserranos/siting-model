#!/usr/bin/env python3
"""dc_watch v2 — the daily pipeline on the v2 knowledge base.

Loop A (news-first, primary): RSS → keyword prefilter → article text → DeepSeek extraction →
  ENTITY RESOLUTION (alias → geo → fuzzy → LLM confirm only when ambiguous) → append observations
  (never overwrite) → export → publish → Telegram digest.
Loop B (enrichment, optional, --enrich N): visit the N stalest projects and fill gaps the news
  never covers. Skipped by default so the daily run stays fast and cheap.

Reuses v1's collection/extraction (import dc_watch) so this file only contains what actually
CHANGED — the reconcile step. v1's dc_watch.py is left untouched for rollback.

Usage:
  python3 dc_watch2.py                 # daily news run
  python3 dc_watch2.py --enrich 5      # + enrich the 5 stalest projects
  python3 dc_watch2.py --dry           # no DB writes, no publish (inspect only)
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

import dc_watch as v1          # collect/fetch_text/extract/geocode/tg/log/push_github (unchanged)
import enrich
import ingest
import kb
import resolver

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DC_KB_PATH", os.path.join(HERE, "dc_kb.sqlite"))

EVENT_TO_STATUS = {"land_purchase": "land", "announcement": "announced", "permit": "permit",
                   "construction_start": "construction", "operational": "operating",
                   "expansion": None, "deal": None, "cancelled": "cancelled"}

CONFIRM_PROMPT = """Do these two refer to the SAME physical data-center project? Two distinct
facilities can share a town or an owner — same owner + same town is NOT sufficient; they must be
the same project. Answer JSON only: {"verdict":"same"|"different"|"uncertain","why":"<8 words"}"""


def llm_confirm(mention, ent):
    """One cheap DeepSeek call, invoked ONLY for the ambiguous band of the resolution funnel."""
    import requests
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return "uncertain"
    a = (f'A: name="{mention.get("name")}" company="{mention.get("company")}" '
         f'town="{mention.get("municipality")}"')
    b = (f'B: name="{ent.get("canonical_name")}" company="{ent.get("company")}" '
         f'area="{ent.get("region")}"')
    try:
        r = requests.post("https://api.deepseek.com/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                                "response_format": {"type": "json_object"},
                                "messages": [{"role": "user", "content": f"{CONFIRM_PROMPT}\n{a}\n{b}"}],
                                "temperature": 0, "max_tokens": 60}, timeout=60)
        if r.status_code != 200:
            return "uncertain"
        return json.loads(r.json()["choices"][0]["message"]["content"]).get("verdict", "uncertain")
    except Exception:
        return "uncertain"


def reconcile_v2(con, results, run_id, dry=False):
    """The v2 replacement for v1's reconcile(): resolve identity first, then append observations."""
    new_p, changed, uncertain = [], [], []
    geo_cache = {}

    for it in results:
        a = it["_a"]
        if not dry:
            con.execute("INSERT OR IGNORE INTO seen VALUES(?,?,?)",
                        (a["url"], date.today().isoformat(), int(bool(it.get("relevant")))))
        if not it.get("relevant") or it.get("confidence", 0) < 0.4:
            continue

        muni, prov = it.get("municipality") or "", it.get("province") or ""
        mention = {"name": it.get("project_name") or "?", "company": it.get("company"),
                   "municipality": muni, "province": prov}
        # geocode BEFORE resolving so geo-blocking can work (cached per run — Nominatim is slow)
        gk = f"{muni}|{prov}"
        if muni or prov:
            if gk not in geo_cache:
                geo_cache[gk] = v1.geocode(muni, prov)
            mention["lat"], mention["lon"] = geo_cache[gk]

        dec = resolver.resolve(con, mention, llm_confirm)
        tier = kb.tier_for(a.get("source"))
        when = (a.get("published") or "")[:10] or date.today().isoformat()

        if dry:
            print(f"  {dec['decision']:9s} score={dec['score']:.2f}  {mention['name'][:40]:40s} "
                  f"→ {dec.get('entity_id') or '(new)'}  [{dec['reason']}]")
            continue

        if dec["decision"] == "match":
            eid = dec["entity_id"]
        else:
            eid = ingest.create_entity(con, {**mention, "src": "news"}, run_id, review=1)
            if dec["decision"] == "uncertain":
                # never silently merge OR silently duplicate — create flagged, record the candidate
                con.execute("INSERT INTO changelog(ts,run_id,entity_id,action,note,source_url) "
                            "VALUES(?,?,?,?,?,?)",
                            (date.today().isoformat(), run_id, eid, "review",
                             f"possible duplicate of {dec['entity_id']} (score {dec['score']})", a["url"]))
                uncertain.append(f"{mention['name']} ~ {dec['entity_id']}")
            else:
                new_p.append(f"{mention['name']} ({it.get('company')}, {muni})")

        # every surface name we resolve becomes an alias → future mentions match for free
        ingest.add_alias(con, eid, mention["name"], a["url"], when)
        if it.get("company"):
            ingest.add_alias(con, eid, it["company"], a["url"], when)

        facts = []
        st = EVENT_TO_STATUS.get(it.get("event_type"))
        if st:
            facts.append(("status", None, st, None))
        if it.get("mw"):
            facts.append(("mw", it["mw"], None, "MW"))
        if it.get("eur_m"):
            facts.append(("investment_eur_m", it["eur_m"], None, "EUR_m"))
        if it.get("company"):
            facts.append(("company", None, it["company"], None))
        for attr, num, text, unit in facts:
            r = ingest.apply_observation(con, eid, attr, value_num=num, value_text=text, unit=unit,
                                         source_url=a["url"], tier=tier, reported_date=when,
                                         run_id=run_id)
            if r["changed"]:
                changed.append(f"{mention['name']}: {attr} {r['old']}→{r['new']}")

        con.execute("INSERT OR IGNORE INTO news(entity_id,url,source,source_tier,date,title,"
                    "event_type,summary,confidence,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (eid, a["url"], a["source"], tier, when, a["title"], it.get("event_type"),
                     it.get("summary"), it.get("confidence"), run_id))
    if not dry:
        con.commit()
    return new_p, changed, uncertain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enrich", type=int, default=0, help="also enrich N stalest projects (Loop B)")
    ap.add_argument("--dry", action="store_true", help="resolve + print, no writes, no publish")
    args = ap.parse_args()

    if not os.path.exists(DB):
        sys.exit(f"v2 KB not found at {DB} — run migrate_v1.py first (or set DC_KB_PATH)")
    con = kb.connect(DB)
    if args.dry:
        # work on an in-memory COPY so a dry run has zero side effects — the reused v1 collect()
        # commits `seen` rows internally, which would otherwise make articles skip on the real run.
        mem = kb.connect(":memory:")
        con.backup(mem)
        con.close()
        con = mem
    run_id = "watch-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not args.dry:
        con.execute("INSERT OR IGNORE INTO runs(run_id,type,started_at) VALUES(?,?,?)",
                    (run_id, "watch", datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"))

    items = v1.collect(con)
    v1.log(f"[v2] candidates: {len(items)}")
    for a in items:
        a["text"] = v1.fetch_text(a["url"])
        if len(a["text"]) < 200:
            a["text"] = f"(solo titular y resumen RSS) {a['title']}. {a.get('rss_summary','')}"
    results = v1.extract(items) if items else []
    new_p, changed, uncertain = reconcile_v2(con, results, run_id, dry=args.dry)

    n_enriched = 0
    if args.enrich and not args.dry:
        er = enrich.run_enrichment(con, args.enrich, enrich.rss_search, enrich.deepseek_extract, run_id)
        n_enriched = sum(1 for r in er if r.get("applied"))
        v1.log(f"[v2] enriched {n_enriched}/{len(er)} projects")

    if args.dry:
        print("\n[dry run] no writes, no publish")
        con.close()
        return

    payload = ingest.export_v2(con, repo=os.environ.get("GH_REPO"))
    pushed = v1.push_github(payload)
    con.execute("UPDATE runs SET finished_at=?, n_articles=?, n_new=?, n_changed=?, n_enriched=? "
                "WHERE run_id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z", len(items),
                 len(new_p), len(changed), n_enriched, run_id))
    con.commit()

    rel = sum(1 for r in results if r.get("relevant"))
    msg = (f"🛰 DC-watch v2 {date.today().isoformat()}\n"
           f"{len(items)} articulos, {rel} relevantes\n"
           f"➕ nuevos: {len(new_p)}" + "".join(f"\n  · {p}" for p in new_p[:5]) +
           f"\n♻️ cambios: {len(changed)}" + "".join(f"\n  · {c}" for c in changed[:5]) +
           (f"\n❓ revisar (posible duplicado): {len(uncertain)}" +
            "".join(f"\n  · {u}" for u in uncertain[:3]) if uncertain else "") +
           (f"\n🔎 enriquecidos: {n_enriched}" if args.enrich else "") +
           f"\n📦 {payload['counts']['projects']} proyectos · {payload['counts']['observations']} "
           f"observaciones · publicado: {'sí' if pushed else 'NO'}")
    v1.tg(msg)
    v1.log("[v2] done")
    con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        v1.log(f"[v2] FATAL: {e}")
        v1.tg(f"⚠️ dc_watch v2 FALLÓ: {e}")
        raise
