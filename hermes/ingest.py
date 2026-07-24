#!/usr/bin/env python3
"""Write path for dc_watch v2: append observations, derive the headline with hysteresis,
respect human locks + the status ratchet, log to the changelog only when the headline actually
moves, and export the enriched dc_live.json the new UI renders. Pure stdlib + kb.py.
"""
from datetime import date, datetime, timezone

import kb

# attributes we track as headline facts (order = display order)
TRACKED = ["status", "company", "mw", "investment_eur_m", "type"]
NUMERIC = {"mw", "investment_eur_m"}

STATUS_RANK = {"announced": 1, "land": 1, "permit": 2, "construction": 3,
               "operating": 4, "operational": 4}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


# ---------------- reads ----------------
def get_lock(con, eid, attr):
    r = con.execute("SELECT value_num, value_text FROM human_locks WHERE entity_id=? AND attribute=?",
                    (eid, attr)).fetchone()
    return {"value_num": r[0], "value_text": r[1]} if r else None


def _obs_rows(con, eid, attr):
    return [dict(zip(["value_num", "value_text", "source_tier", "reported_date", "first_seen", "source_url"], r))
            for r in con.execute(
                "SELECT value_num,value_text,source_tier,reported_date,first_seen,source_url "
                "FROM observations WHERE entity_id=? AND attribute=?", (eid, attr))]


def _status_headline(con, eid):
    """Status ratchets — it only ever moves forward, and 'cancelled' always wins. This is why a
    retrospective 'announced' article can't demote a project that's already under construction."""
    lock = get_lock(con, eid, "status")
    if lock and lock["value_text"]:
        return {"value": lock["value_text"], "status": "locked", "confidence": 1.0,
                "range": None, "n_sources": 0}
    stats = [r[0] for r in con.execute(
        "SELECT value_text FROM observations WHERE entity_id=? AND attribute='status' AND value_text IS NOT NULL", (eid,))]
    if not stats:
        return None
    n = len(set(stats))
    if "cancelled" in stats:
        val = "cancelled"
    else:
        val = max(stats, key=lambda s: STATUS_RANK.get(s, 0))
    return {"value": val, "status": "stable" if n <= 1 else "ratcheted",
            "confidence": 1.0, "range": None, "n_sources": len(stats)}


def headline(con, eid, attr):
    """The single derived value for an attribute: lock > status-ratchet > confidence-weighted derive."""
    if attr == "status":
        return _status_headline(con, eid)
    lock = get_lock(con, eid, attr)
    d = kb.derive(_obs_rows(con, eid, attr), locked=lock)
    return d


# ---------------- writes ----------------
def _changelog(con, eid, action, run_id, attr=None, old=None, new=None, url=None, note=None):
    con.execute("INSERT INTO changelog(ts,run_id,entity_id,action,attribute,old,new,source_url,note) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (date.today().isoformat(), run_id, eid, action, attr,
                 None if old is None else str(old), None if new is None else str(new), url, note))


def add_alias(con, eid, raw, source, when=None):
    k = kb.alias_key(raw)
    if not k:
        return
    con.execute("INSERT OR IGNORE INTO aliases(alias,raw,entity_id,source,first_seen) VALUES(?,?,?,?,?)",
                (k, raw, eid, source, when or date.today().isoformat()))


def create_entity(con, mention, run_id, review=1, existing_slugs=None):
    """Mint a new project entity + seed its alias list. Caller then applies observations."""
    if existing_slugs is None:
        existing_slugs = {r[0] for r in con.execute("SELECT id FROM entities")}
    eid = kb.slugify(mention.get("name") or "project", existing_slugs)
    con.execute("INSERT INTO entities(id,type,canonical_name,region,lat,lon,status,src,review,"
                "created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, "project", mention.get("name") or "?", mention.get("municipality") or mention.get("province"),
                 mention.get("lat"), mention.get("lon"), None, mention.get("src", "news"), review,
                 _now(), run_id, _now(), run_id))
    add_alias(con, eid, mention.get("name") or "", "news")
    if mention.get("company"):
        add_alias(con, eid, mention["company"], "news")
        if mention.get("municipality"):
            add_alias(con, eid, f"{mention['company']} {mention['municipality']}", "news")
    _changelog(con, eid, "create", run_id, note=f"src:{mention.get('src','news')} review:{review}")
    return eid


def apply_observation(con, eid, attr, *, value_num=None, value_text=None, unit=None,
                      source_url=None, tier="unverified", reported_date=None, run_id=None):
    """Append a fact and move the headline only if the evidence warrants it.

    Data is NEVER discarded — every observation is stored for audit/range even when it doesn't win.
    Returns {changed, old, new, status, locked}.
    """
    before = headline(con, eid, attr)
    old_val = before["value"] if before else None

    con.execute("INSERT INTO observations(entity_id,attribute,value_num,value_text,unit,source_url,"
                "source_tier,reported_date,first_seen,run_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (eid, attr, value_num, value_text, unit, source_url, tier,
                 reported_date, date.today().isoformat(), run_id))

    lock = get_lock(con, eid, attr)
    after = headline(con, eid, attr)
    new_val = after["value"] if after else None

    # locked field: record the disagreement but never move the headline
    if lock is not None:
        incoming = value_num if value_num is not None else value_text
        locked_val = lock["value_num"] if lock["value_num"] is not None else lock["value_text"]
        differs = incoming is not None and str(incoming) != str(locked_val)
        if attr in NUMERIC and value_num is not None and lock["value_num"] is not None:
            differs = abs(value_num - lock["value_num"]) / max(abs(lock["value_num"]), 1) > kb.NUM_TOLERANCE
        if differs:
            _changelog(con, eid, "conflict", run_id, attr, locked_val, incoming, source_url,
                       "source disagrees with human-locked value — not applied")
        return {"changed": False, "old": old_val, "new": old_val, "status": "locked", "locked": True}

    changed = str(old_val) != str(new_val)
    if changed:
        _changelog(con, eid, "status" if attr == "status" else "update",
                   run_id, attr, old_val, new_val, source_url,
                   None if after is None else f"conf={after['confidence']} {after['status']}")
        con.execute("UPDATE entities SET updated_at=?, updated_by=? WHERE id=?", (_now(), run_id, eid))
        if attr == "status":
            con.execute("UPDATE entities SET status=? WHERE id=?", (new_val, eid))
    return {"changed": changed, "old": old_val, "new": new_val,
            "status": after["status"] if after else None, "locked": False}


def human_lock(con, eid, attr, *, value_num=None, value_text=None, note="pinned by hand"):
    """Pin a field so the agent can flag but never overwrite it. Marc's manual-control lever."""
    con.execute("INSERT OR REPLACE INTO human_locks(entity_id,attribute,value_num,value_text,note,ts) "
                "VALUES(?,?,?,?,?,?)", (eid, attr, value_num, value_text, note, _now()))
    _changelog(con, eid, "human_edit", "human", attr, None,
               value_num if value_num is not None else value_text, None, note)


# ---------------- export ----------------
def export_v2(con, repo=None):
    """Build the enriched dc_live.json: each field carries {value, range, confidence, status,
    n_sources} so the UI can show ranges + confidence + provenance, not a bare number."""
    projects = []
    for eid, name, region, lat, lon, review, updated, src in con.execute(
            "SELECT id,canonical_name,region,lat,lon,review,updated_at,src FROM entities "
            "WHERE lat IS NOT NULL"):
        fields = {}
        for attr in TRACKED:
            h = headline(con, eid, attr)
            if h and h.get("value") is not None:
                fields[attr] = h
        news = [{"date": d, "title": t, "url": u, "source": s, "tier": tr, "event": ev, "summary": sm}
                for (d, t, u, s, tr, ev, sm) in con.execute(
                    "SELECT date,title,url,source,source_tier,event_type,summary FROM news "
                    "WHERE entity_id=? ORDER BY date DESC LIMIT 12", (eid,))]
        changes = [{"ts": ts, "action": ac, "field": f, "old": o, "new": n, "url": u, "note": nt}
                   for (ts, ac, f, o, n, u, nt) in con.execute(
                       "SELECT ts,action,attribute,old,new,source_url,note FROM changelog "
                       "WHERE entity_id=? ORDER BY id DESC LIMIT 10", (eid,))]
        st = fields.get("status", {})
        # LEGACY MIRROR: the deployed app.js reads flat p.mw / p.inv / p.company. Emit those
        # alongside fields{} so v2 can go live WITHOUT breaking the current map — the new UI reads
        # fields{} (value+range+confidence+provenance), the old one keeps working unchanged.
        def _v(a):
            f = fields.get(a)
            return f.get("value") if f else None
        projects.append({"id": eid, "name": name, "lat": lat, "lon": lon, "region": region,
                         "status": st.get("value"), "review": review, "updated": updated,
                         "company": _v("company"), "mw": _v("mw"), "inv": _v("investment_eur_m"),
                         "src": src,
                         "fields": fields, "news": news, "changes": changes})

    feed = [{"date": d, "title": t, "url": u, "source": s, "tier": tr, "event": ev,
             "summary": sm, "project": pn}
            for (d, t, u, s, tr, ev, sm, pn) in con.execute(
                "SELECT n.date,n.title,n.url,n.source,n.source_tier,n.event_type,n.summary,e.canonical_name "
                "FROM news n LEFT JOIN entities e ON e.id=n.entity_id ORDER BY n.id DESC LIMIT 120")]

    runs = [{"run_id": r[0], "type": r[1], "at": r[2], "new": r[3], "changed": r[4], "enriched": r[5]}
            for r in con.execute("SELECT run_id,type,finished_at,n_new,n_changed,n_enriched FROM runs "
                                 "ORDER BY started_at DESC LIMIT 20")]
    counts = {
        "projects": con.execute("SELECT COUNT(*) FROM entities WHERE lat IS NOT NULL").fetchone()[0],
        "observations": con.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
        "review": con.execute("SELECT COUNT(*) FROM entities WHERE review=1").fetchone()[0],
        "changes": con.execute("SELECT COUNT(*) FROM changelog").fetchone()[0],
    }
    return {"generated": _now(), "repo": repo, "schema": 2,
            "counts": counts, "runs": runs, "projects": projects, "news_feed": feed}
