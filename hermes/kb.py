#!/usr/bin/env python3
"""Shared knowledge-base helpers for dc_watch v2: normalization, slugs, source tiers,
and the deterministic derive() that turns an append-only observation list into a single
{value, range, confidence, status} — the thing that stops numbers flip-flopping.

Deliberately dependency-free (stdlib only) so it runs anywhere the pipeline does.
"""
import re
import sqlite3
import unicodedata
from datetime import date, datetime

SCHEMA = None  # loaded lazily from kb_schema.sql next to this file

# ---- source reliability tiers (higher = trusted more in the confidence weighting) ----
TIER_WEIGHT = {
    "human":      1.30,   # a hand entry outranks any single source (locks handle hard pins)
    "official":   1.00,   # company IR, government registry, grid operator
    "wire":       1.00,   # Reuters/EFE/AP
    "national":   0.80,   # El País, Expansión, Cinco Días
    "trade":      0.70,   # DataCenterDynamics and sector press
    "research":   0.60,   # our own seed / baxtel scrape baseline
    "seed":       0.60,   # alias for research
    "local":      0.50,   # regional/local outlet
    "unverified": 0.30,   # blog, aggregator, unclear provenance
}
DEFAULT_TIER = "unverified"

# numeric attributes are bucketed by relative closeness; two values within this ratio
# are treated as "the same claim" and corroborate each other rather than competing.
NUM_TOLERANCE = 0.15
# a competing value must exceed the leader's confidence by this margin to take over the
# headline (hysteresis — prevents run-to-run thrash between two comparably-sourced numbers).
SUPERSEDE_MARGIN = 0.10

LEGAL_SUFFIXES = re.compile(
    r"\b(data\s*center|datacenter|centro de datos|cpd|campus|s\.?l\.?u?|s\.?a\.?u?|inc|ltd|llc|holdings?)\b",
    re.I,
)


def tier_for(source):
    """Map a source name/domain to a reliability tier (drives confidence weighting). Shared by
    every module so a source is scored the same wherever it enters the pipeline."""
    s = norm(source)  # strip accents/case so 'Expansión' matches 'expansion'
    if any(k in s for k in ("reuters", "efe", "europa press", "ap ", "bloomberg")):
        return "wire"
    if "datacenterdynamics" in s or "dcd" in s or "datacenter" in s and "dynamics" in s:
        return "trade"
    if any(k in s for k in ("expansion", "cinco dias", "cincodias", "elpais", "el pais", "elmundo",
                            "el mundo", "vanguardia", "confidencial", "eleconomista", "abc.es")):
        return "national"
    if any(k in s for k in ("boe", "gob.es", ".gov", "ir.", "investor", "press release", "prnewswire")):
        return "official"
    if s in ("seed", "research", "baxtel"):
        return "research"
    if any(k in s for k in ("blog", "medium", "reddit", "forum")):
        return "unverified"
    return "local" if source else "unverified"


def norm(s):
    """Lowercase, strip diacritics — the canonical comparison form for names/aliases."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def alias_key(s):
    """Aggressive normalization for the alias lookup: also drops boilerplate suffixes and
    collapses whitespace/punctuation, so 'AWS Zaragoza Data Center, S.L.' → 'aws zaragoza'."""
    s = norm(s)
    s = LEGAL_SUFFIXES.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def slugify(name, existing=None):
    """Stable, human-readable entity id from a name; de-duplicates against `existing` set."""
    base = re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")[:40] or "project"
    if existing is None:
        return base
    slug, n = base, 1
    while slug in existing:
        n += 1
        slug = f"{base}-{n:02d}"
    return slug


def _recency(d):
    """Recency multiplier from an ISO date string: fresh news counts more than stale. An undated
    fact (no reported date — e.g. a seed value of unknown vintage) is treated as OLD/low-confidence,
    so any properly-dated news reliably overrides it rather than losing to a 'fresh-looking' import."""
    if not d:
        return 0.4
    try:
        dt = datetime.fromisoformat(str(d)[:10]).date()
    except Exception:
        return 0.5
    age = (date.today() - dt).days
    if age < 0:
        return 1.0
    if age < 30:
        return 1.0
    if age < 180:
        return 0.7
    if age < 540:
        return 0.5
    return 0.35


def derive(observations, locked=None):
    """Collapse an attribute's observation list into a single derived view.

    observations: list of dicts with keys value_num|value_text, source_tier, reported_date,
                  first_seen, source_url.
    locked:       an optional {value_num|value_text} the human pinned — always wins.

    Returns {value, range, confidence, status, n_sources, contributing[]} or None if empty.
    status ∈ {'stable','contested','locked','single'}.
    """
    obs = [o for o in observations if (o.get("value_num") is not None or o.get("value_text"))]
    if not obs:
        return None

    numeric = any(o.get("value_num") is not None for o in obs)

    # group observations into "same claim" buckets
    buckets = []  # each: {"key", "value", "score", "obs":[...]}
    for o in obs:
        w = TIER_WEIGHT.get((o.get("source_tier") or "").lower(), TIER_WEIGHT[DEFAULT_TIER])
        # recency uses the REPORTED date (valid-time). Undated seed values → low recency (0.4), so
        # dated news overrides them; we deliberately do NOT fall back to first_seen (transaction-time).
        score = w * _recency(o.get("reported_date"))
        if numeric:
            v = o.get("value_num")
            if v is None:
                continue
            placed = False
            for b in buckets:
                if b["value"] and abs(v - b["value"]) / max(abs(b["value"]), 1) <= NUM_TOLERANCE:
                    # corroboration: keep the more-recent/larger-sample representative value
                    b["obs"].append(o)
                    b["score"] += score
                    placed = True
                    break
            if not placed:
                buckets.append({"value": v, "score": score, "obs": [o]})
        else:
            v = norm(o.get("value_text"))
            b = next((b for b in buckets if b["key"] == v), None)
            if b:
                b["obs"].append(o); b["score"] += score
            else:
                buckets.append({"key": v, "value": o.get("value_text"), "score": score, "obs": [o]})

    buckets.sort(key=lambda b: b["score"], reverse=True)
    top = buckets[0]
    total = sum(b["score"] for b in buckets) or 1.0
    confidence = round(top["score"] / total, 2)

    if locked is not None and (locked.get("value_num") is not None or locked.get("value_text")):
        value = locked.get("value_num") if locked.get("value_num") is not None else locked.get("value_text")
        status = "locked"
    else:
        value = top["value"]
        if len(buckets) == 1:
            status = "single" if len(top["obs"]) == 1 else "stable"
        else:
            runner = buckets[1]
            # contested if a competitor is within the hysteresis margin of the leader
            status = "contested" if runner["score"] >= top["score"] * (1 - SUPERSEDE_MARGIN) else "stable"

    out = {
        "value": value,
        "confidence": confidence,
        "status": status,
        "n_sources": len({o.get("source_url") for o in obs if o.get("source_url")}) or len(obs),
    }
    if numeric:
        vals = [o["value_num"] for o in obs if o.get("value_num") is not None]
        lo, hi = min(vals), max(vals)
        out["range"] = [lo, hi] if lo != hi else None
    else:
        out["range"] = None
    return out


def load_schema():
    global SCHEMA
    if SCHEMA is None:
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_schema.sql")
        SCHEMA = open(p).read()
    return SCHEMA


def connect(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(load_schema())
    return con


if __name__ == "__main__":
    # tiny self-test of derive(): the €500M↔€1B case from the brief should NOT thrash.
    demo = [
        {"value_num": 500, "source_tier": "wire",  "reported_date": "2026-06-01", "source_url": "a"},
        {"value_num": 1000, "source_tier": "trade", "reported_date": "2026-07-10", "source_url": "b"},
        {"value_num": 500, "source_tier": "national", "reported_date": "2026-07-20", "source_url": "c"},
    ]
    import json
    print(json.dumps(derive(demo), indent=2))
