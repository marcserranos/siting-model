#!/usr/bin/env python3
"""Adversarial tests for the resolver, run against the dev DB (built from the live snapshot).
Proves: exact match, same-site-different-name MERGE, the APTO/Fuenlabrada duplicate that the
old pipeline created, a genuinely-new far-away project, and the over-merge trap (two different
projects in the same town must NOT auto-merge — they route to the LLM instead).
"""
import os
import sys

import kb
import resolver

DB = os.path.join(os.path.dirname(__file__), "dc_kb_dev.sqlite")


def pick(con, where=""):
    """Grab a real entity (with coords + a company) to build realistic mentions from."""
    row = con.execute(
        "SELECT e.id,e.canonical_name,e.region,e.lat,e.lon,"
        "(SELECT value_text FROM observations o WHERE o.entity_id=e.id AND o.attribute='company' "
        " ORDER BY id DESC LIMIT 1) "
        "FROM entities e WHERE e.lat IS NOT NULL " + where + " LIMIT 1").fetchone()
    return dict(zip(["id", "name", "region", "lat", "lon", "company"], row)) if row else None


def show(label, expect, dec):
    ok = dec["decision"] == expect
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"       expected={expect}  got={dec['decision']}  score={dec['score']}  reason={dec['reason']}")
    if dec.get("candidates"):
        print(f"       top: {dec['candidates'][:2]}")
    return ok


def main():
    if not os.path.exists(DB):
        sys.exit("dev DB missing — run: python3 kb_build_dev.py ../../spain-dc-map/data/dc_live.json")
    con = kb.connect(DB)

    # a scripted stand-in for the DeepSeek confirmation call, so tests are deterministic.
    # returns 'same' only when names genuinely look like one project; 'different' otherwise.
    def fake_llm(mention, ent):
        a, b = kb.alias_key(mention.get("name", "")), kb.alias_key(ent["canonical_name"])
        shared = set(a.split()) & set(b.split())
        return "same" if len(shared) >= 2 else "different"

    passed = total = 0

    # 1. EXACT existing name → instant alias/name match
    e = pick(con)
    m = {"name": e["name"], "company": e["company"], "municipality": e["region"],
         "lat": e["lat"], "lon": e["lon"]}
    total += 1; passed += show("1. exact existing project", "match", resolver.resolve(con, m, fake_llm))

    # 2. SAME SITE, DIFFERENT NAME (media renames it) → should MERGE, not duplicate
    m2 = {"name": f"Nuevo CPD de {e['company'] or 'operador'}", "company": e["company"],
          "municipality": e["region"], "lat": e["lat"] + 0.003, "lon": e["lon"] + 0.003}  # ~450m away
    total += 1; passed += show("2. same site, renamed by press", "match", resolver.resolve(con, m2, fake_llm))

    # 3. THE APTO/FUENLABRADA DUPLICATE the old pipeline created
    apto_ids = [r[0] for r in con.execute(
        "SELECT id FROM entities WHERE canonical_name LIKE '%Apto%' AND lat IS NOT NULL")]
    apto = con.execute("SELECT id,canonical_name,region,lat,lon FROM entities "
                       "WHERE canonical_name LIKE '%Apto%' AND lat IS NOT NULL LIMIT 1").fetchone()
    if apto:
        am = {"name": "APTO Fuenlabrada", "company": "APTO", "municipality": apto[2],
              "lat": apto[3], "lon": apto[4]}
        dec = resolver.resolve(con, am, fake_llm)
        # must resolve to an EXISTING apto entity (the KB already has two dupes), never make a third
        ok = dec["decision"] == "match" and dec.get("entity_id") in apto_ids
        print(f"[{'PASS' if ok else 'FAIL'}] 3. APTO Fuenlabrada → existing entity (no new duplicate)")
        print(f"       got={dec['decision']} entity={dec.get('entity_id')} in {apto_ids}  score={dec['score']} reason={dec['reason']}")
        total += 1; passed += ok
    else:
        print("[SKIP] 3. no APTO entity in this snapshot")

    # 4. GENUINELY NEW project, far from everything (Galicia coast, novel name)
    m4 = {"name": "Proyecto Costa Atlántica Nubaris", "company": "Nubaris Cloud",
          "municipality": "Ferrol", "lat": 43.49, "lon": -8.24}
    total += 1; passed += show("4. brand-new far-away project", "new", resolver.resolve(con, m4, fake_llm))

    # 5. OVER-MERGE TRAP: different developer & name, but SAME TOWN + close coords.
    #    Must NOT auto-match — the LLM (fake) says 'different' → decision 'new'.
    m5 = {"name": "Data Tower Beta", "company": "Vantage", "municipality": e["region"],
          "lat": e["lat"] + 0.004, "lon": e["lon"] - 0.004}  # ~600m, unrelated project
    dec5 = resolver.resolve(con, m5)  # no LLM → should be 'uncertain' (flag for human), not silent match
    ok5 = dec5["decision"] in ("uncertain", "new")
    print(f"[{'PASS' if ok5 else 'FAIL'}] 5. over-merge trap (same town, diff project, no LLM)")
    print(f"       got={dec5['decision']} score={dec5['score']} reason={dec5['reason']}  (must be uncertain/new, never silent match)")
    total += 1; passed += ok5

    # 6. duplicate sweep over existing KB — surfaces likely dupes already present
    dups = resolver.find_duplicates(con, threshold=0.6)
    print(f"\n[info] find_duplicates: {len(dups)} candidate pairs ≥0.6 in the current KB")
    for sc, a, b, rs in dups[:6]:
        print(f"       {sc}  {a}  ~  {b}   ({rs})")

    print(f"\n==== {passed}/{total} tests passed ====")
    con.close()
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
