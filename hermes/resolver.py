#!/usr/bin/env python3
"""Entity-resolution funnel for dc_watch v2. Replaces the old naive match_project() with the
research-backed pipeline: cheap deterministic blocking (alias → geo → fuzzy) narrows the field
to a handful of candidates, and an LLM confirmation is invoked ONLY for the genuinely ambiguous
remainder — so the paid step stays rare. Human `overrides` and `human` aliases always win.

The LLM step is injected as a callable so this module is testable with zero API calls and the
production DeepSeek call lives in dc_watch.py.
"""
import difflib
import math

import kb

# ---- tunables (all interpretable; adjust from test evidence, not vibes) ----
R_SAME_SITE_KM = 3.0     # within this, a physical site is almost certainly the same project
R_BLOCK_KM = 25.0        # geo-blocking radius: only entities this close are candidates
HIGH = 0.72              # ≥ this → auto-match, no LLM
LOW = 0.45               # [LOW, HIGH) → ambiguous → LLM confirm (or flag for review)
GENERIC_ALIAS_MINLEN = 6 # shorter single-word aliases (e.g. "apto") don't auto-decide on their own


def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _tokens(s):
    return set(t for t in kb.alias_key(s).split() if t)


def _token_set_ratio(a, b):
    """Order-independent token overlap — robust to reordered/partial names."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _name_sim(a, b):
    ka, kb_ = kb.alias_key(a), kb.alias_key(b)
    if not ka or not kb_:
        return 0.0
    return max(difflib.SequenceMatcher(None, ka, kb_).ratio(), _token_set_ratio(a, b))


def _entity_blob(ent):
    """All the strings we can match a mention against for one entity."""
    return " ".join(filter(None, [ent.get("canonical_name"), ent.get("region")] + ent.get("aliases", [])))


def load_entities(con):
    """Load all entities with their alias list. At a few hundred rows this is cheap; blocking
    below still keeps the SCORED set tiny, which is what matters for the LLM budget."""
    ents = []
    for r in con.execute("SELECT id,canonical_name,company_hint,region,lat,lon,status FROM ("
                         "SELECT e.*, (SELECT value_text FROM observations o WHERE o.entity_id=e.id "
                         "AND o.attribute='company' ORDER BY id DESC LIMIT 1) AS company_hint "
                         "FROM entities e)"):
        ents.append({"id": r[0], "canonical_name": r[1], "company": r[2], "region": r[3],
                     "lat": r[4], "lon": r[5], "status": r[6], "aliases": []})
    by_id = {e["id"]: e for e in ents}
    for alias, eid in con.execute("SELECT alias, entity_id FROM aliases"):
        if eid in by_id:
            by_id[eid]["aliases"].append(alias)
    return ents


def alias_hit(con, mention):
    """Authoritative only when the alias is specific enough (multi-word or long). A short generic
    token like 'apto' becomes a mere candidate, not an instant decision."""
    keys = {kb.alias_key(mention.get("name"))}
    if mention.get("company") and mention.get("municipality"):
        keys.add(kb.alias_key(f"{mention['company']} {mention['municipality']}"))
    keys = {k for k in keys if k}
    for k in keys:
        specific = " " in k or len(k) >= GENERIC_ALIAS_MINLEN
        rows = con.execute("SELECT entity_id FROM aliases WHERE alias=?", (k,)).fetchall()
        if rows and specific:
            return rows[0][0]
    return None


def score(mention, ent):
    """Interpretable 0..1 match score + a human-readable reason string."""
    reasons = []
    ns = _name_sim(mention.get("name", ""), ent["canonical_name"])
    for al in ent.get("aliases", []):
        ns = max(ns, _name_sim(mention.get("name", ""), al))
    s = 0.5 * ns
    if ns > 0.3:
        reasons.append(f"name~{ns:.2f}")

    blob = kb.alias_key(_entity_blob(ent))
    comp = kb.alias_key(mention.get("company", ""))
    comp_match = bool(comp) and any(t in blob.split() for t in comp.split() if len(t) > 2)
    if comp_match:
        s += 0.25; reasons.append("company✓")

    muni = kb.alias_key(mention.get("municipality", ""))
    muni_match = bool(muni) and muni in blob
    if muni_match:
        s += 0.20; reasons.append("municipality✓")

    d = haversine(mention.get("lat"), mention.get("lon"), ent.get("lat"), ent.get("lon"))
    if d is not None:
        if d < R_SAME_SITE_KM:
            # strong boost, but NOT enough to auto-match on its own — two distinct DCs can share
            # an industrial park. Only geo + real name agreement clears HIGH; geo + weak name
            # lands in the LLM-confirm band, which is exactly where a sibling-facility call belongs.
            s += 0.30; reasons.append(f"geo {d:.1f}km✓")
        elif d < R_BLOCK_KM:
            s += 0.15 * (1 - d / R_BLOCK_KM); reasons.append(f"geo {d:.0f}km")
        else:
            s -= 0.25; reasons.append(f"geo {d:.0f}km far")
    return max(0.0, min(1.0, s)), ", ".join(reasons)


def block(mention, ents):
    """Shrink to plausible candidates: geo within radius, OR sharing a name/company token.
    Falls back to the full set only if blocking finds nothing (keeps recall safe at small N)."""
    mtok = _tokens(mention.get("name", "")) | _tokens(mention.get("company", ""))
    out = []
    for e in ents:
        d = haversine(mention.get("lat"), mention.get("lon"), e.get("lat"), e.get("lon"))
        if d is not None and d <= R_BLOCK_KM:
            out.append(e); continue
        if mtok & (_tokens(e["canonical_name"]) | set(" ".join(e.get("aliases", [])).split())):
            out.append(e)
    return out or ents


def resolve(con, mention, llm_confirm=None):
    """Return a decision dict:
      {decision: 'match'|'new'|'uncertain', entity_id, score, reason, candidates:[(id,score,reason)]}
    llm_confirm(mention, candidate_ent) -> 'same'|'different'|'uncertain' is called ONLY for the
    ambiguous band; if not provided, ambiguous cases return 'uncertain' (flagged for human review).
    """
    # 1. authoritative alias hit — instant, free
    eid = alias_hit(con, mention)
    if eid:
        return {"decision": "match", "entity_id": eid, "score": 1.0,
                "reason": "alias exact", "candidates": [(eid, 1.0, "alias exact")]}

    # 2. block → 3. score
    ents = load_entities(con)
    cands = block(mention, ents)
    scored = sorted(((e, *score(mention, e)) for e in cands), key=lambda x: x[1], reverse=True)
    if not scored:
        return {"decision": "new", "entity_id": None, "score": 0.0, "reason": "no candidates", "candidates": []}
    top = [(e["id"], round(sc, 3), rs) for e, sc, rs in scored[:3]]

    best_e, best_s, best_r = scored[0]
    base = {"score": round(best_s, 3), "reason": best_r, "candidates": top}

    # 4. decide with hysteresis band
    if best_s >= HIGH:
        return {"decision": "match", "entity_id": best_e["id"], **base}
    if best_s >= LOW:
        if llm_confirm is not None:
            verdict = llm_confirm(mention, best_e)
            if verdict == "same":
                return {"decision": "match", "entity_id": best_e["id"], **base, "reason": best_r + " +LLM:same"}
            if verdict == "different":
                return {"decision": "new", "entity_id": None, **base, "reason": best_r + " +LLM:different"}
        return {"decision": "uncertain", "entity_id": best_e["id"], **base}
    return {"decision": "new", "entity_id": None, **base}


def find_duplicates(con, threshold=LOW):
    """One-off sweep over EXISTING entities to surface likely dupes already in the KB (the
    'entries that already exist but weren't cross-checked' problem), respecting 'different'
    overrides. Returns pairs sorted by score for human review — never auto-merges."""
    ents = load_entities(con)
    diff = {(a, b) for a, b, dec in
            con.execute("SELECT entity_a,entity_b,decision FROM overrides") if dec == "different"
            for (a, b) in [(a, b), (b, a)]}
    pairs = []
    for i, e in enumerate(ents):
        m = {"name": e["canonical_name"], "company": e.get("company"),
             "municipality": e.get("region"), "lat": e.get("lat"), "lon": e.get("lon")}
        for f in ents[i + 1:]:
            if (e["id"], f["id"]) in diff:
                continue
            sc, rs = score(m, f)
            if sc >= threshold:
                pairs.append((round(sc, 3), e["id"], f["id"], rs))
    return sorted(pairs, reverse=True)
