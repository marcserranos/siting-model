#!/usr/bin/env python3
"""Fill in each project's region from its coordinates — offline, no API calls, no tokens.

Only ~7% of records carried a region (the seed rarely set it, and news extraction only supplies
one when the article happens to name a province), which left every "by region" aggregate covering
a fraction of the base. But 100% of records have lat/lon, and the siting model's own grid already
tags every cell with its CCAA code — so the region is derivable by a spatial join against data we
already ship. Projects with no cell nearby are outside peninsular Spain and are marked as such
rather than being forced into a Spanish region.

Usage: python3 backfill_regions.py [dc_kb.sqlite] [--apply]
       (dry-run by default; --apply writes and records each change in the changelog)
"""
import json
import math
import os
import sys
from datetime import date, datetime, timezone

import kb

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "..", "web", "data")
MAX_KM = 25.0          # a project further than this from any grid cell is not in the grid's area
RUN_ID = "regions-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * r * math.asin(math.sqrt(a))


def load_grid():
    cells = json.load(open(os.path.join(WEB, "cells.json")))["cells"]
    regions = json.load(open(os.path.join(WEB, "regions.json")))
    names = {k: v.get("name") for k, v in regions.items() if isinstance(v, dict)}
    # bucket cells by whole degree so the nearest-cell lookup stays cheap
    buckets = {}
    for c in cells:
        buckets.setdefault((int(c[0]), int(c[1])), []).append(c)
    return buckets, names


def nearest_region(lat, lon, buckets, names):
    best, bestd = None, 1e9
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for c in buckets.get((int(lat) + dy, int(lon) + dx), []):
                d = haversine(lat, lon, c[0], c[1])
                if d < bestd:
                    best, bestd = c, d
    if best is None or bestd > MAX_KM:
        return None, bestd
    return names.get(str(best[2])), bestd


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply_it = "--apply" in sys.argv
    db = args[0] if args else os.path.join(HERE, "dc_kb_dev.sqlite")
    if not os.path.exists(db):
        sys.exit(f"KB not found: {db}")

    buckets, names = load_grid()
    con = kb.connect(db)
    rows = con.execute("SELECT id, canonical_name, lat, lon, region FROM entities "
                       "WHERE lat IS NOT NULL").fetchall()
    filled = outside = kept = 0
    ccaa = {v for v in names.values() if v}
    normalised = 0
    for eid, name, lat, lon, cur in rows:
        reg, dist = nearest_region(lat, lon, buckets, names)
        if cur and cur in ccaa:      # already an autonomous community — leave it alone
            kept += 1
            continue
        if cur and reg and cur not in ccaa:
            # news extraction supplies a province ("Zaragoza") while the grid supplies the
            # autonomous community ("Aragón"). Mixing the two granularities silently breaks every
            # by-region aggregate, so normalise to CCAA and keep the province as an alias.
            normalised += 1
            if apply_it:
                con.execute("UPDATE entities SET region=? WHERE id=?", (reg, eid))
                con.execute("INSERT OR IGNORE INTO aliases(alias,raw,entity_id,source,first_seen) "
                            "VALUES(?,?,?,?,?)",
                            (kb.alias_key(cur), cur, eid, "region-normalise", date.today().isoformat()))
                con.execute("INSERT INTO changelog(ts,run_id,entity_id,action,attribute,old,new,note) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (date.today().isoformat(), RUN_ID, eid, "update", "region", cur, reg,
                             "normalised province to autonomous community"))
            continue
        if reg is None:
            outside += 1
            if apply_it:
                con.execute("INSERT INTO changelog(ts,run_id,entity_id,action,attribute,old,new,note) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (date.today().isoformat(), RUN_ID, eid, "update", "region", None, None,
                             f"outside the modelled grid ({dist:.0f} km from nearest cell)"))
            continue
        filled += 1
        if apply_it:
            con.execute("UPDATE entities SET region=? WHERE id=?", (reg, eid))
            con.execute("INSERT INTO changelog(ts,run_id,entity_id,action,attribute,old,new,note) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (date.today().isoformat(), RUN_ID, eid, "update", "region", None, reg,
                         f"derived from coordinates (nearest grid cell {dist:.1f} km)"))
    if apply_it:
        con.execute("INSERT OR IGNORE INTO runs(run_id,type,started_at,finished_at,n_changed,notes) "
                    "VALUES(?,?,?,?,?,?)",
                    (RUN_ID, "regions", datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
                     datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z", filled,
                     f"regions derived from coordinates for {filled} projects"))
        con.commit()

    print(f"{'APPLIED' if apply_it else 'DRY RUN'} — {db}")
    print(f"  already correct:      {kept}")
    print(f"  province→CCAA fixed:  {normalised}")
    print(f"  filled from coords:   {filled}")
    print(f"  outside the grid:     {outside}  (kept blank — not peninsular Spain/Balearics)")
    if not apply_it:
        print("\n  re-run with --apply to write")
    con.close()


if __name__ == "__main__":
    main()
