#!/bin/bash
# Polls the public repo every 2 min (via cron) for two things the static site can't do itself:
#  1. a manual ingestion request from the "Trigger ingestion" button (data/trigger.json)
#  2. queued human review decisions from the Audit view - approvals, merges, "not a
#     duplicate" calls (data/decisions.json, applied by apply_decisions.py)
# Requires GH_REPO (+ GH_TOKEN for decisions) in .env; state kept in .last_trigger;
# flock prevents the ingestion trigger overlapping a running/cron watch.
cd "$(dirname "$0")"
set -a; source .env 2>/dev/null; set +a
[ -z "$GH_REPO" ] && exit 0

.venv/bin/python3 apply_decisions.py >> decisions.log 2>&1

TS=$(curl -sf -m 15 "https://raw.githubusercontent.com/$GH_REPO/main/data/trigger.json?nocache=$(date +%s)" \
     | grep -o '"requested":"[^"]*"' | cut -d'"' -f4)
[ -z "$TS" ] && exit 0
LAST=$(cat .last_trigger 2>/dev/null)
[ "$TS" = "$LAST" ] && exit 0
echo "$TS" > .last_trigger
echo "$(date -u +%FT%TZ) manual trigger $TS" >> dc_watch.log
flock -n /tmp/dc_watch.lock .venv/bin/python dc_watch2.py --enrich 5 >> cron.log 2>&1
