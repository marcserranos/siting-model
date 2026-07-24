#!/usr/bin/env python3
"""Migrate a live v1 dc_watch.sqlite (projects/news/seen/changes) into the v2 knowledge base
(entities/aliases/observations/changelog/runs). NON-DESTRUCTIVE: reads v1, writes a NEW v2 file,
never modifies the source.

The interesting part is provenance reconstruction: v1 stored only the CURRENT scalar per project,
but its `news` rows (mw/eur_m/event_type + date + source) and its `changes` rows (field/old/new +
ts + url) are a historical record we can replay into dated observations — so the migrated KB starts
with real per-fact provenance instead of a flat snapshot.

Usage: python3 migrate_v1.py /root/dc_watch/dc_watch.sqlite /root/dc_watch/dc_kb.sqlite
"""
import os
import sqlite3
import sys
from datetime import date, datetime, timezone

import kb

EVENT_TO_STATUS = {"land_purchase": "land", "announcement": "announced", "permit": "permit",
                   "construction_start": "construction", "operational": "operating",
                   "expansion": None, "deal": None, "cancelled": "cancelled"}
RUN_ID = "migrate-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def obs(con, eid, attr, *, num=None, text=None, unit=None, url=None, tier="research", reported=None):
    con.execute("INSERT INTO observations(entity_id,attribute,value_num,value_text,unit,source_url,"
                "source_tier,reported_date,first_seen,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (eid, attr, num, text, unit, url, tier, reported, date.today().isoformat(), RUN_ID))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    if not os.path.exists(src):
        sys.exit(f"source v1 DB not found: {src}")
    if os.path.exists(dst):
        sys.exit(f"refusing to overwrite existing {dst} — move it aside first")

    v1 = sqlite3.connect(src)
    v1.row_factory = sqlite3.Row
    con = kb.connect(dst)
    con.execute("INSERT INTO runs(run_id,type,started_at,notes) VALUES(?,?,?,?)",
                (RUN_ID, "migrate", datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
                 f"v1→v2 migration from {os.path.basename(src)}"))

    cols = {r[1] for r in v1.execute("PRAGMA table_info(projects)")}
    has_inv = "investment_eur_m" in cols
    pid2eid, slugs = {}, set()
    n_obs = 0

    for p in v1.execute("SELECT * FROM projects"):
        eid = kb.slugify(p["name"] or "project", slugs)
        slugs.add(eid)
        pid2eid[p["id"]] = eid
        born = p["src"] or "seed"
        con.execute("INSERT INTO entities(id,type,canonical_name,region,lat,lon,status,src,review,"
                    "created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, "project", p["name"], p["region"], p["lat"], p["lon"], p["status"], born,
                     p["review"] or 0, p["updated"] or date.today().isoformat(), "migrate",
                     p["updated"] or date.today().isoformat(), "migrate"))
        con.execute("INSERT INTO changelog(ts,run_id,entity_id,action,note) VALUES(?,?,?,?,?)",
                    (date.today().isoformat(), RUN_ID, eid, "create", f"migrated from v1 id={p['id']}"))

        # aliases: name, company, and company+region — the surface forms future mentions will hit
        for raw, s in ((p["name"], "seed"), (p["company"], "seed")):
            if raw:
                k = kb.alias_key(raw)
                if k:
                    con.execute("INSERT OR IGNORE INTO aliases(alias,raw,entity_id,source,first_seen) "
                                "VALUES(?,?,?,?,?)", (k, raw, eid, s, date.today().isoformat()))
        if p["company"] and p["region"]:
            k = kb.alias_key(f"{p['company']} {p['region']}")
            if k:
                con.execute("INSERT OR IGNORE INTO aliases(alias,raw,entity_id,source,first_seen) "
                            "VALUES(?,?,?,?,?)", (k, f"{p['company']} {p['region']}", eid, "seed",
                                                  date.today().isoformat()))

        # current scalars → UNDATED baseline observations (unknown vintage → low recency, so any
        # properly-dated news reliably supersedes them rather than being outranked by a stale import)
        tier = kb.tier_for(born)
        if p["company"]:
            obs(con, eid, "company", text=p["company"], tier=tier); n_obs += 1
        if p["status"]:
            obs(con, eid, "status", text=p["status"], tier=tier); n_obs += 1
        if p["mw"]:
            obs(con, eid, "mw", num=p["mw"], unit="MW", tier=tier); n_obs += 1
        if has_inv and p["investment_eur_m"]:
            obs(con, eid, "investment_eur_m", num=p["investment_eur_m"], unit="EUR_m", tier=tier); n_obs += 1

    # news rows carry DATED, SOURCED facts — replay them as observations (the real provenance win)
    n_news = 0
    for n in v1.execute("SELECT * FROM news"):
        eid = pid2eid.get(n["project_id"])
        if not eid:
            continue
        t = kb.tier_for(n["source"])
        con.execute("INSERT OR IGNORE INTO news(entity_id,url,source,source_tier,date,title,"
                    "event_type,summary,confidence,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (eid, n["url"], n["source"], t, n["date"], n["title"], n["event_type"],
                     n["summary"], n["confidence"], RUN_ID))
        n_news += 1
        if n["mw"]:
            obs(con, eid, "mw", num=n["mw"], unit="MW", url=n["url"], tier=t, reported=n["date"]); n_obs += 1
        if n["eur_m"]:
            obs(con, eid, "investment_eur_m", num=n["eur_m"], unit="EUR_m", url=n["url"], tier=t,
                reported=n["date"]); n_obs += 1
        st = EVENT_TO_STATUS.get(n["event_type"])
        if st:
            obs(con, eid, "status", text=st, url=n["url"], tier=t, reported=n["date"]); n_obs += 1

    # v1 change history → changelog (preserves "when did this platform learn what")
    n_chg = 0
    try:
        for c in v1.execute("SELECT * FROM changes"):
            eid = pid2eid.get(c["project_id"])
            if not eid:
                continue
            con.execute("INSERT INTO changelog(ts,run_id,entity_id,action,attribute,old,new,source_url,note) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (c["ts"], "v1-history", eid, "update", c["field"], c["old"], c["new"],
                         c["news_url"], "migrated from v1 changes"))
            n_chg += 1
    except sqlite3.OperationalError:
        pass

    n_seen = 0
    for s in v1.execute("SELECT url, ts, relevant FROM seen"):
        con.execute("INSERT OR IGNORE INTO seen VALUES(?,?,?)", (s["url"], s["ts"], s["relevant"]))
        n_seen += 1

    con.execute("UPDATE runs SET finished_at=?, n_new=?, notes=? WHERE run_id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z", len(pid2eid),
                 f"entities={len(pid2eid)} observations={n_obs} news={n_news} changelog={n_chg}", RUN_ID))
    con.commit()

    print(f"migrated {src} → {dst}")
    print(f"  entities:     {len(pid2eid)}")
    print(f"  aliases:      {con.execute('SELECT COUNT(*) FROM aliases').fetchone()[0]}")
    print(f"  observations: {n_obs}  (dated from news + undated baselines)")
    print(f"  news:         {n_news}")
    print(f"  changelog:    {con.execute('SELECT COUNT(*) FROM changelog').fetchone()[0]}")
    print(f"  seen urls:    {n_seen}")
    print(f"\nsource v1 DB untouched: {src}")
    con.close(); v1.close()


if __name__ == "__main__":
    main()
