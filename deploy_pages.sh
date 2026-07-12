#!/bin/bash
# Publish web/ to the public GitHub Pages repo (spain-dc-map).
# One-time: create the repo on github.com, then: git clone git@github.com:YOURUSER/spain-dc-map.git ../spain-dc-map
set -e
DEST="${1:-../spain-dc-map}"
[ -d "$DEST/.git" ] || { echo "clone your spain-dc-map repo to $DEST first"; exit 1; }
rsync -a --delete --exclude '.git' --exclude 'data/dc_live.json' web/ "$DEST/"
cp hermes/dc_watch.py hermes/seed_db.py hermes/requirements.txt hermes/env.example "$DEST/" 2>/dev/null || true
cd "$DEST"
git add -A && git commit -m "deploy $(date +%F)" && git push
echo "pushed. Pages URL: https://$(git remote get-url origin | sed -E 's#.*[:/]([^/]+)/([^/.]+).*#\1.github.io/\2#')/"
