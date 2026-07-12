#!/bin/bash
# Polls the public repo for a manual ingestion request written by the viewer's
# "trigger now" button (web/data/trigger.json). Runs every 2 min via cron.
# Requires GH_REPO in .env; state kept in .last_trigger; flock prevents overlap.
cd "$(dirname "$0")"
set -a; source .env 2>/dev/null; set +a
[ -z "$GH_REPO" ] && exit 0
TS=$(curl -sf -m 15 "https://raw.githubusercontent.com/$GH_REPO/main/web/data/trigger.json?nocache=$(date +%s)" \
     | grep -o '"requested":"[^"]*"' | cut -d'"' -f4)
[ -z "$TS" ] && exit 0
LAST=$(cat .last_trigger 2>/dev/null)
[ "$TS" = "$LAST" ] && exit 0
echo "$TS" > .last_trigger
echo "$(date -u +%FT%TZ) manual trigger $TS" >> dc_watch.log
flock -n /tmp/dc_watch.lock .venv/bin/python dc_watch.py >> cron.log 2>&1
