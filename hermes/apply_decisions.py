#!/usr/bin/env python3
"""Applies human review decisions queued from the website's Audit view.

The Audit view has no backend of its own — it's a static site — so a "Merge" or "Approve"
click there writes a small record to data/decisions.json in the public repo (via the GitHub
Contents API, using a token the user pastes into their own browser and that never leaves it).
This script is the other half: it runs on the VM (polled by trigger_poll.sh, same cadence as
the manual-ingestion trigger), fetches that queue, applies each undone decision to the real
dc_kb.sqlite, and clears the queue on GitHub so it doesn't reapply.

Decision shapes:
  {"id": "...", "type": "merge",     "keep": "<entity id>", "drop": "<entity id>", "note": "..."}
  {"id": "...", "type": "different", "a": "<entity id>", "b": "<entity id>", "note": "..."}
  {"id": "...", "type": "review",    "entity_id": "<entity id>", "decision": "approve"|"reject", "note": "..."}

Every decision is idempotent to re-apply (merge_entities no-ops if already merged; set_review
just re-sets a flag; overrides insert is INSERT-only and duplicate-safe) — if the GitHub clear
step fails after a successful local apply, the next poll re-applying the same decision is safe.
"""
import base64
import json
import os
import sys
from datetime import date, datetime, timezone

import requests

import ingest
import kb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DC_KB_PATH", os.path.join(HERE, "dc_kb.sqlite"))
QUEUE_PATH = "data/decisions.json"   # flat path — see the note in trigger_poll.sh / views.js


def _env():
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fetch_queue(repo, token):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"https://api.github.com/repos/{repo}/contents/{QUEUE_PATH}", headers=h, timeout=30)
    if r.status_code == 404:
        return [], None
    r.raise_for_status()
    body = r.json()
    content = json.loads(base64.b64decode(body["content"]))
    return content.get("decisions", []), body["sha"]


def clear_queue(repo, token, sha, remaining):
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    body = {"message": f"decisions applied {date.today().isoformat()}",
            "content": base64.b64encode(json.dumps({"decisions": remaining}).encode()).decode(),
            "sha": sha}
    r = requests.put(f"https://api.github.com/repos/{repo}/contents/{QUEUE_PATH}",
                     headers=h, json=body, timeout=30)
    return r.status_code in (200, 201)


def apply_one(con, d, run_id):
    """Returns (ok, message)."""
    t = d.get("type")
    try:
        if t == "merge":
            ingest.merge_entities(con, d["keep"], d["drop"], run_id, note=d.get("note"))
            return True, f"merged {d['drop']} -> {d['keep']}"
        if t == "different":
            con.execute("INSERT INTO overrides(entity_a,entity_b,decision,note,ts) VALUES(?,?,?,?,?)",
                        (d["a"], d["b"], "different", d.get("note"),
                         datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"))
            con.commit()
            return True, f"marked different: {d['a']} / {d['b']}"
        if t == "review":
            cleared = d.get("decision") == "approve"
            ingest.set_review(con, d["entity_id"], cleared, run_id, note=d.get("note"))
            return True, f"review {'approved' if cleared else 're-flagged'}: {d['entity_id']}"
        return False, f"unknown decision type: {t!r}"
    except Exception as e:
        return False, f"error: {e}"


def main():
    _env()
    repo, token = os.environ.get("GH_REPO"), os.environ.get("GH_TOKEN")
    if not repo or not token:
        print("GH_REPO/GH_TOKEN unset — skipping"); return
    if not os.path.exists(DB):
        print(f"KB not found at {DB} — skipping"); return

    decisions, sha = fetch_queue(repo, token)
    if not decisions:
        return   # nothing queued — normal, quiet exit (this runs every 2 minutes)

    con = kb.connect(DB)
    run_id = "decisions-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    applied, failed = [], []
    for d in decisions:
        ok, msg = apply_one(con, d, run_id)
        (applied if ok else failed).append((d, msg))
        print(("OK  " if ok else "FAIL") + f" [{d.get('id','?')}] {msg}")
    con.close()

    # failed decisions stay in the queue for a human to look at; applied ones are cleared
    remaining = [d for d, _ in failed]
    if applied:
        clear_queue(repo, token, sha, remaining)
    print(f"applied {len(applied)}, left pending {len(remaining)}")


if __name__ == "__main__":
    main()
