#!/usr/bin/env python3
"""Write-path tests: the real €500M↔€1B sequence must not thrash; a human lock must hold against
contradicting sources; status must ratchet forward only; export must carry ranges + confidence.
Runs on a throwaway in-memory DB — no API calls, no production data.
"""
import kb
import ingest

RUN = "test-run"


def fresh_entity(con):
    con.execute("INSERT INTO entities(id,type,canonical_name,region,lat,lon,src,review,created_at,updated_at) "
                "VALUES('p1','project','Test DC Zaragoza','Zaragoza',41.6,-0.9,'seed',0,'2026-01-01','2026-01-01')")
    return "p1"


def check(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}   {detail}")
    return bool(cond)


def main():
    con = kb.connect(":memory:")
    eid = fresh_entity(con)
    ok = tot = 0

    # ---- 1. the oscillation sequence: 500 (wire) → 1000 (trade) → 500 (national) ----
    seq = [
        (500, "wire", "2026-06-01", "a.com"),
        (1000, "trade", "2026-07-10", "b.com"),
        (500, "national", "2026-07-20", "c.com"),
    ]
    moves = []
    for val, tier, when, url in seq:
        r = ingest.apply_observation(con, eid, "investment_eur_m", value_num=val, unit="EUR_m",
                                     source_url=url, tier=tier, reported_date=when, run_id=RUN)
        moves.append((val, r["changed"], r["new"]))
    h = ingest.headline(con, eid, "investment_eur_m")
    # headline should have moved exactly ONCE (None→500) and stayed 500 despite the 1000 spike
    n_moves = sum(1 for _, changed, _ in moves if changed)
    tot += 1; ok += check("1a. no flip-flop: headline stays 500", h["value"] == 500,
                          f"value={h['value']} moves={n_moves}")
    tot += 1; ok += check("1b. headline moved only once (initial set)", n_moves == 1, f"moves={n_moves}")
    tot += 1; ok += check("1c. range surfaces the disagreement [500,1000]", h["range"] == [500, 1000], f"range={h['range']}")
    # 500 has 2 sources (incl. recent national) vs one trade at 1000 → a clear leader, so 'stable'
    # is correct; the RANGE is what tells the UI sources disagree. 'contested' is for real near-ties.
    tot += 1; ok += check("1d. clear leader → stable (not a false 'contested' alarm)",
                          h["status"] == "stable", f"status={h['status']}")

    # 1d2. a genuine near-tie (equal support, two distinct values) MUST flag contested
    for val, url in ((100, "m1.com"), (200, "m2.com")):
        ingest.apply_observation(con, eid, "mw", value_num=val, unit="MW", source_url=url,
                                 tier="wire", reported_date="2026-07-23", run_id=RUN)
    hmw = ingest.headline(con, eid, "mw")
    tot += 1; ok += check("1d2. real near-tie flagged contested", hmw["status"] == "contested",
                          f"status={hmw['status']} range={hmw['range']}")

    # changelog should show a single investment 'update', not one per article
    n_inv_changes = con.execute("SELECT COUNT(*) FROM changelog WHERE attribute='investment_eur_m' "
                                "AND action='update'").fetchone()[0]
    tot += 1; ok += check("1e. one changelog entry, not three", n_inv_changes == 1, f"entries={n_inv_changes}")

    # ---- 2. evidence CAN move the headline when it genuinely accumulates ----
    for url in ("d.com", "e.com"):
        ingest.apply_observation(con, eid, "investment_eur_m", value_num=1000, unit="EUR_m",
                                 source_url=url, tier="wire", reported_date="2026-07-23", run_id=RUN)
    h2 = ingest.headline(con, eid, "investment_eur_m")
    tot += 1; ok += check("2. headline moves to 1000 once well-corroborated", h2["value"] == 1000,
                          f"value={h2['value']} conf={h2['confidence']}")

    # ---- 3. human lock holds against a contradicting source ----
    ingest.human_lock(con, eid, "investment_eur_m", value_num=750, note="Marc: per filing")
    ingest.apply_observation(con, eid, "investment_eur_m", value_num=3000, unit="EUR_m",
                             source_url="rumor.com", tier="unverified", reported_date="2026-07-24", run_id=RUN)
    h3 = ingest.headline(con, eid, "investment_eur_m")
    tot += 1; ok += check("3a. locked value holds (750, not 3000)", h3["value"] == 750, f"value={h3['value']}")
    tot += 1; ok += check("3b. lock status surfaced", h3["status"] == "locked", f"status={h3['status']}")
    n_conflict = con.execute("SELECT COUNT(*) FROM changelog WHERE action='conflict'").fetchone()[0]
    tot += 1; ok += check("3c. disagreement logged, not applied", n_conflict == 1, f"conflicts={n_conflict}")

    # ---- 4. status ratchets forward only ----
    for st, when in [("announced", "2026-02-01"), ("construction", "2026-06-01"), ("announced", "2026-07-01")]:
        ingest.apply_observation(con, eid, "status", value_text=st, source_url="x", tier="national",
                                 reported_date=when, run_id=RUN)
    hs = ingest.headline(con, eid, "status")
    tot += 1; ok += check("4a. status ratchets to construction (not back to announced)",
                          hs["value"] == "construction", f"value={hs['value']}")
    ingest.apply_observation(con, eid, "status", value_text="cancelled", source_url="y", tier="wire",
                             reported_date="2026-07-24", run_id=RUN)
    hs2 = ingest.headline(con, eid, "status")
    tot += 1; ok += check("4b. cancelled always wins", hs2["value"] == "cancelled", f"value={hs2['value']}")

    # ---- 5. export carries the rich structure ----
    payload = ingest.export_v2(con, repo="test/repo")
    p = payload["projects"][0]
    inv = p["fields"].get("investment_eur_m", {})
    tot += 1; ok += check("5a. export has schema=2 + counts", payload.get("schema") == 2 and "counts" in payload)
    tot += 1; ok += check("5b. field carries value+range+confidence+status",
                          all(k in inv for k in ("value", "range", "confidence", "status")),
                          f"keys={list(inv)}")

    print(f"\n==== {ok}/{tot} write-path checks passed ====")
    import sys
    sys.exit(0 if ok == tot else 1)


if __name__ == "__main__":
    main()
