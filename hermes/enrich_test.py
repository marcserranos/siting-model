#!/usr/bin/env python3
"""Offline enrichment test (zero tokens): pick a real sparse project from the dev DB, enrich it
with mock search + extraction, and prove (a) facts land with provenance, (b) last_enriched is
stamped, (c) the stale queue advances, and (d) the drift guard rejects facts whose mention
resolves to a DIFFERENT existing project.
"""
import os
import sys

import enrich
import ingest
import kb

DB = os.path.join(os.path.dirname(__file__), "dc_kb_dev.sqlite")
RUN = "enrich-test"


def check(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}   {detail}")
    return bool(cond)


def main():
    if not os.path.exists(DB):
        sys.exit("dev DB missing — run kb_build_dev.py first")
    con = kb.connect(DB)
    ok = tot = 0

    # a real sparse project: has coords, no mw and no investment observation yet
    row = con.execute(
        "SELECT e.id,e.canonical_name,e.region,e.lat,e.lon FROM entities e WHERE e.lat IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.entity_id=e.id "
        "AND o.attribute IN ('mw','investment_eur_m')) LIMIT 1").fetchone()
    proj = dict(zip(["id", "name", "region", "lat", "lon"], row))
    print(f"enriching: {proj['name']} [{proj['id']}]  ({proj['region']})\n")

    before = con.execute("SELECT COUNT(*) FROM observations WHERE entity_id=? "
                         "AND attribute IN ('mw','investment_eur_m')", (proj["id"],)).fetchone()[0]

    # mock search returns two plausible articles about THIS project
    def mock_search(q):
        return [
            {"url": "https://expansion.com/x", "title": f"{proj['name']} ampliación",
             "source": "Expansión", "published": "2026-07-15",
             "text": "El proyecto sumará 180 MW y una inversión de 900 millones de euros."},
            {"url": "https://datacenterdynamics.com/y", "title": f"{proj['name']} construction",
             "source": "DataCenterDynamics", "published": "2026-07-18",
             "text": "Construction has begun on the campus."},
        ]

    # mock extractor pulls structured facts, tagging each with its source article index
    def mock_extract(project, articles):
        return {"about_this_project": True, "fields": [
            {"attribute": "mw", "value_num": 180, "unit": "MW", "source_idx": 0},
            {"attribute": "investment_eur_m", "value_num": 900, "unit": "EUR_m", "source_idx": 0},
            {"attribute": "status", "value_text": "construction", "source_idx": 1},
        ]}

    res = enrich.enrich_project(con, proj, mock_search, mock_extract, RUN)
    con.commit()

    after = con.execute("SELECT COUNT(*) FROM observations WHERE entity_id=? "
                        "AND attribute IN ('mw','investment_eur_m')", (proj["id"],)).fetchone()[0]
    tot += 1; ok += check("1. facts applied (mw + investment now present)", after - before >= 2,
                          f"observations {before}→{after}, applied={res['applied']}")

    mw = ingest.headline(con, proj["id"], "mw")
    inv = ingest.headline(con, proj["id"], "investment_eur_m")
    tot += 1; ok += check("2. headline values set with provenance", mw and mw["value"] == 180 and inv["value"] == 900,
                          f"mw={mw['value'] if mw else None} inv={inv['value']}")

    src_ok = con.execute("SELECT COUNT(*) FROM observations WHERE entity_id=? AND attribute='mw' "
                         "AND source_url IS NOT NULL AND source_tier='national'", (proj["id"],)).fetchone()[0]
    tot += 1; ok += check("3. observation carries source_url + tier", src_ok >= 1, f"tiered_rows={src_ok}")

    le = con.execute("SELECT last_enriched FROM entities WHERE id=?", (proj["id"],)).fetchone()[0]
    tot += 1; ok += check("4. last_enriched stamped (queue advances)", le is not None, f"last_enriched={le}")

    news_ok = con.execute("SELECT COUNT(*) FROM news WHERE entity_id=? AND event_type='enrichment'",
                          (proj["id"],)).fetchone()[0]
    tot += 1; ok += check("5. source articles recorded in news trail", news_ok >= 1, f"news_rows={news_ok}")

    # 6. DRIFT GUARD: an article whose mention clearly belongs to a DIFFERENT existing project
    #    (a distant one with a different name/company) must be rejected.
    other = con.execute(
        "SELECT e.id,e.canonical_name,e.region,e.lat,e.lon,"
        "(SELECT value_text FROM observations o WHERE o.entity_id=e.id AND o.attribute='company' LIMIT 1) "
        "FROM entities e WHERE e.lat IS NOT NULL AND e.id!=? "
        "ORDER BY ABS(e.lat-?)+ABS(e.lon-?) DESC LIMIT 1", (proj["id"], proj["lat"], proj["lon"])).fetchone()
    other_m = {"name": other[1], "company": other[5], "municipality": other[2],
               "lat": other[3], "lon": other[4]}
    guard_pass = enrich._same_project(con, proj, other_m)  # should be False → rejected
    tot += 1; ok += check("6. drift guard rejects a different project's facts", guard_pass is False,
                          f"other={other[1]} guard_allows={guard_pass}")

    # ---- cost model (DeepSeek V4-Flash placeholder prices; confirmed separately) ----
    print("\n--- token/cost model (per run, DeepSeek V4-Flash: $0.14/M in, $0.28/M out) ---")
    for n in (5, 20, 194):
        est = enrich.estimate_cost(n, price_in_per_m=0.14, price_out_per_m=0.28)
        monthly = f" → ${round(est['usd']*30,2)}/mo daily" if n < 194 else " (one-time backfill)"
        print(f"  {n:>3} projects: {est['in_tokens']:,} in / {est['out_tokens']:,} out → "
              f"${est['usd']}/run{monthly}")

    print(f"\n==== {ok}/{tot} enrichment checks passed ====")
    con.close()
    sys.exit(0 if ok == tot else 1)


if __name__ == "__main__":
    main()
