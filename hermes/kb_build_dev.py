#!/usr/bin/env python3
"""Reconstruct a realistic v2 KB from the deployed dc_live.json snapshot, for LOCAL testing
only (the real DB lives on the VM). Proves the schema + derive() hold on the real 210
projects before any of this touches production.

Usage: python3 kb_build_dev.py ../../spain-dc-map/data/dc_live.json  [out.sqlite]
"""
import json
import os
import sys
from datetime import date, datetime, timezone

import kb


def utcnow():
    return datetime.now(timezone.utc)


RUN_ID = "devbuild-" + utcnow().strftime("%Y%m%dT%H%M%SZ")


def tier_for(src):
    s = (src or "").lower()
    if "datacenterdynamics" in s or "dcd" in s:
        return "trade"
    if any(k in s for k in ("reuters", "efe", "europa press")):
        return "wire"
    if any(k in s for k in ("expansion", "cinco", "pais", "mundo", "vanguardia", "confidencial")):
        return "national"
    if s in ("seed", "research", "baxtel"):
        return "research"
    return "national" if src else "unverified"


def obs(con, eid, attr, num=None, text=None, unit=None, url=None, tier="research",
        reported=None, run=RUN_ID):
    con.execute(
        "INSERT INTO observations(entity_id,attribute,value_num,value_text,unit,source_url,"
        "source_tier,reported_date,first_seen,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (eid, attr, num, text, unit, url, tier, reported, date.today().isoformat(), run))


def chg(con, eid, action, attr=None, old=None, new=None, url=None, note=None):
    con.execute(
        "INSERT INTO changelog(ts,run_id,entity_id,action,attribute,old,new,source_url,note) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (date.today().isoformat(), RUN_ID, eid, action, attr,
         None if old is None else str(old), None if new is None else str(new), url, note))


def add_alias(con, alias_raw, eid, source):
    k = kb.alias_key(alias_raw)
    if not k:
        return
    con.execute("INSERT OR IGNORE INTO aliases(alias,raw,entity_id,source,first_seen) "
                "VALUES(?,?,?,?,?)", (k, alias_raw, eid, source, date.today().isoformat()))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "../../spain-dc-map/data/dc_live.json"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "dc_kb_dev.sqlite")
    if os.path.exists(out):
        os.remove(out)
    data = json.load(open(src))
    projects = data.get("projects", [])
    con = kb.connect(out)

    con.execute("INSERT INTO runs(run_id,type,started_at,notes) VALUES(?,?,?,?)",
                (RUN_ID, "migrate", utcnow().isoformat(timespec="seconds") + "Z",
                 f"dev rebuild from {os.path.basename(src)} ({len(projects)} projects)"))

    slugs = set()
    n_obs = 0
    for p in projects:
        eid = kb.slugify(p["name"], slugs)
        slugs.add(eid)
        born = "news" if p.get("review") else (p.get("src") or "seed")
        con.execute(
            "INSERT INTO entities(id,type,canonical_name,region,lat,lon,status,src,review,"
            "created_at,created_by,updated_at,updated_by,last_enriched) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "project", p["name"], p.get("region"), p.get("lat"), p.get("lon"),
             p.get("status"), born, int(bool(p.get("review"))),
             p.get("updated") or date.today().isoformat(), "seed",
             p.get("updated") or date.today().isoformat(), "seed", None))
        chg(con, eid, "create", note=f"born:{born}")

        # aliases: name + company + region give future mentions something to resolve against
        add_alias(con, p["name"], eid, "seed")
        if p.get("company"):
            add_alias(con, p["company"], eid, "seed")
        if p.get("region"):
            add_alias(con, f"{p.get('company','')} {p['region']}".strip(), eid, "seed")

        # backfill current scalar values as observations (tier by source)
        st = tier_for(p.get("src"))
        if p.get("company"):
            obs(con, eid, "company", text=p["company"], tier=st); n_obs += 1
        if p.get("status"):
            obs(con, eid, "status", text=p["status"], tier=st); n_obs += 1
        if p.get("mw"):
            obs(con, eid, "mw", num=p["mw"], unit="MW", tier=st); n_obs += 1
        if p.get("inv"):
            obs(con, eid, "investment_eur_m", num=p["inv"], unit="EUR_m", tier=st); n_obs += 1

        # news → news rows + as observations where they carry structured facts
        for nrow in p.get("news", []):
            ntier = tier_for(nrow.get("source"))
            try:
                con.execute(
                    "INSERT OR IGNORE INTO news(entity_id,url,source,source_tier,date,title,"
                    "event_type,summary,confidence,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (eid, nrow.get("url"), nrow.get("source"), ntier, nrow.get("date"),
                     nrow.get("title"), nrow.get("event"), nrow.get("summary"), None, RUN_ID))
            except Exception:
                pass

        # historical changes → changelog (preserve prior provenance)
        for c in p.get("changes", []):
            con.execute(
                "INSERT INTO changelog(ts,run_id,entity_id,action,attribute,old,new,source_url,note) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (c.get("ts"), "history", eid, "update", c.get("field"),
                 c.get("old"), c.get("new"), c.get("url"), "migrated from v1 changes"))

    con.execute("UPDATE runs SET finished_at=?, n_new=?, notes=notes WHERE run_id=?",
                (utcnow().isoformat(timespec="seconds") + "Z", len(projects), RUN_ID))
    con.commit()

    # ---- report ----
    def one(q):
        return con.execute(q).fetchone()[0]
    print(f"built {out}")
    print(f"  entities:      {one('SELECT COUNT(*) FROM entities')}")
    print(f"  aliases:       {one('SELECT COUNT(*) FROM aliases')}")
    print(f"  observations:  {one('SELECT COUNT(*) FROM observations')}")
    print(f"  news:          {one('SELECT COUNT(*) FROM news')}")
    print(f"  changelog:     {one('SELECT COUNT(*) FROM changelog')}")
    print(f"  review-flagged:{one('SELECT COUNT(*) FROM entities WHERE review=1')}")
    print(f"  need enrich (no mw & no inv obs): "
          f"{one('SELECT COUNT(*) FROM entities e WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.entity_id=e.id AND o.attribute IN (\"mw\",\"investment_eur_m\"))')}")

    # spot-check derive() on a project that actually has an investment observation
    row = con.execute(
        "SELECT entity_id FROM observations WHERE attribute='investment_eur_m' LIMIT 1").fetchone()
    if row:
        eid = row[0]
        name = con.execute("SELECT canonical_name FROM entities WHERE id=?", (eid,)).fetchone()[0]
        obs_rows = [dict(zip([c[0] for c in cur.description], r)) for cur in
                    [con.execute("SELECT value_num,value_text,source_tier,reported_date,first_seen,"
                                 "source_url FROM observations WHERE entity_id=? AND attribute='investment_eur_m'", (eid,))]
                    for r in cur.fetchall()]
        print(f"\n  derive() sample — {name} [{eid}] investment_eur_m:")
        print("   ", kb.derive(obs_rows))
        print("    aliases:", [r[0] for r in con.execute("SELECT alias FROM aliases WHERE entity_id=?", (eid,))])
    con.close()


if __name__ == "__main__":
    main()
