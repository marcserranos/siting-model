#!/usr/bin/env python3
"""REAL enrichment run (spends DeepSeek tokens) against the disposable dev DB, for the first
end-to-end test. Prints, per project, what was searched, what DeepSeek extracted, and what the
resolver/ingest did — so we can judge quality before wiring this into production.

Reads DEEPSEEK_API_KEY from hermes/.env (which is gitignored — the key never leaves your machine).

Usage:
  python3 enrich_live.py --stale 5              # the 5 stalest projects
  python3 enrich_live.py --name "Meta" --name "Microsoft"   # target specific projects by name
  python3 enrich_live.py --stale 3 --dry        # search + extract + print, but DON'T write to DB
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import enrich
import ingest
import kb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "dc_kb_dev.sqlite")


def load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def pick_projects(con, args):
    """Named projects first (if any), then fill with the stalest — deduped by id."""
    projs, ids = [], set()
    for nm in (args.name or []):
        r = con.execute(
            "SELECT e.id,e.canonical_name,e.region,e.lat,e.lon,"
            "(SELECT value_text FROM observations o WHERE o.entity_id=e.id AND o.attribute='company' LIMIT 1) "
            "FROM entities e WHERE e.canonical_name LIKE ? AND e.lat IS NOT NULL LIMIT 1", (f"%{nm}%",)).fetchone()
        if r and r[0] not in ids:
            projs.append(dict(zip(["id", "name", "region", "lat", "lon", "company"], r))); ids.add(r[0])
    for p in enrich.stale_projects(con, args.stale):
        if p["id"] not in ids:
            projs.append(p); ids.add(p["id"])
    return projs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale", type=int, default=None,
                    help="how many stalest projects to enrich (default: 0 if --name given, else 5)")
    ap.add_argument("--name", action="append")
    ap.add_argument("--dry", action="store_true", help="search+extract+print only, no DB writes")
    ap.add_argument("--pause", type=float, default=4.0, help="seconds between projects (rate-limit safety)")
    args = ap.parse_args()
    if args.stale is None:
        args.stale = 0 if args.name else 5

    load_env()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        sys.exit("No DEEPSEEK_API_KEY — create hermes/.env with a line:  DEEPSEEK_API_KEY=sk-...")
    if not os.path.exists(DB):
        sys.exit("dev DB missing — run: python3 kb_build_dev.py ../../spain-dc-map/data/dc_live.json")

    con = kb.connect(DB)
    run_id = "live-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    projects = pick_projects(con, args)
    print(f"== live enrichment: {len(projects)} project(s), run {run_id}"
          f"{' [DRY RUN]' if args.dry else ''} ==\n")

    def extract_fn(project, articles):
        return enrich.deepseek_extract(project, articles)

    import time
    for pi, p in enumerate(projects):
        if pi:
            time.sleep(args.pause)   # space out calls so DeepSeek/Google don't rate-limit
        print(f"— {p['name']}  [{p['id']}]  ({p.get('region') or '?'})")
        arts = enrich.rss_search(enrich.build_query(p))
        print(f"   search → {len(arts)} article(s): " +
              ", ".join(f"{a['source']}" for a in arts[:5]) if arts else "   search → 0 articles")
        if not arts:
            if not args.dry:
                con.execute("UPDATE entities SET last_enriched=date('now') WHERE id=?", (p["id"],))
            print()
            continue
        ext = enrich.deepseek_extract(p, arts)
        print(f"   extracted: about_this_project={ext.get('about_this_project')} "
              f"fields={json.dumps(ext.get('fields', []), ensure_ascii=False)}")
        if not args.dry:
            res = enrich.enrich_project(con, p, lambda q, _a=arts: _a, lambda _p, _a, _e=ext: _e, run_id)
            print(f"   applied → {res['applied']}  (skipped {res['skipped']} on drift guard)")
        print()

    if not args.dry:
        con.commit()
        # show the resulting headline facts for what we just touched
        print("== resulting headline facts ==")
        for p in projects:
            fields = {a: ingest.headline(con, p["id"], a) for a in ("mw", "investment_eur_m", "status", "company")}
            fields = {k: v["value"] for k, v in fields.items() if v and v.get("value") is not None}
            print(f"   {p['name']}: {fields}")
    con.close()


if __name__ == "__main__":
    main()
