#!/bin/bash
# Resume (or start) the enrichment backfill. Safe to run any number of times:
# already-enriched projects are skipped (--fresh-only checks last_enriched IS NULL),
# each project commits individually, so a halted run never loses prior progress —
# re-running this just continues from wherever it stopped.
#
# Usage:  ./resume_backfill.sh
set -e
cd "$(dirname "$0")"

# Match only the actual python worker. A plain `pgrep -f enrich_live.py` also matches any
# wrapper shell whose command-line TEXT happens to mention enrich_live.py (e.g. a polling
# loop) even though that shell isn't running python at all — filter by real executable name.
RUNNING_PID=""
for p in $(pgrep -f "enrich_live.py" 2>/dev/null); do
    case "$(ps -p "$p" -o comm= 2>/dev/null)" in
        *python*) RUNNING_PID="$p"; break ;;
    esac
done
if [ -n "$RUNNING_PID" ]; then
    echo "Already running (PID $RUNNING_PID) — nothing to do."
    echo "Progress: $(grep -oE '^\[[0-9]+/[0-9]+\]' backfill.log 2>/dev/null | tail -1)"
    exit 0
fi

if [ ! -f dc_kb_dev.sqlite ]; then
    echo "No dc_kb_dev.sqlite found — building it fresh first."
    python3 kb_build_dev.py ../../spain-dc-map/data/dc_live.json
    ../.venv/bin/python backfill_regions.py dc_kb_dev.sqlite --apply
fi

remaining=$(../.venv/bin/python -c "
import kb
con = kb.connect('dc_kb_dev.sqlite')
print(con.execute('SELECT COUNT(*) FROM entities WHERE lat IS NOT NULL AND last_enriched IS NULL').fetchone()[0])
")

if [ "$remaining" = "0" ]; then
    echo "All projects already enriched — nothing left to do."
    exit 0
fi

echo "Resuming: $remaining project(s) still need enrichment."
echo "resume — $(date '+%Y-%m-%d %H:%M:%S') — $remaining remaining" >> backfill.log
nohup ../.venv/bin/python -u enrich_live.py --stale 250 --fresh-only --pause 5 >> backfill.log 2>&1 &
disown
echo "Started in background (PID $!). Log: hermes/backfill.log"
echo "Check progress any time with:  tail -f hermes/backfill.log"
