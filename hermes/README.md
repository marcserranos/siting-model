# dc_watch — daily Spanish datacenter news pipeline (runs on the Hermes VM)

RSS → keyword filter → DeepSeek V4 Flash extraction (batched, ≤40 articles/day) →
SQLite knowledge base → `dc_live.json` pushed to GitHub → Telegram digest.
Cost: well under $1/month. Cron at **12:15 UTC** (outside DeepSeek peak windows 01–04 & 06–10 UTC).

## Marc's one-time setup (~15 min total)

### A. GitHub repo + token (5 min, on github.com)
1. Top-right **+** → **New repository** → name `spain-dc-map` → **Public** → Create.
2. **Settings → Pages** → Source: "Deploy from a branch" → Branch `main`, folder `/ (root)` → Save.
3. Token: click your avatar → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**. Name `hermes-dc-watch`, expiration 1 year,
   **Repository access: Only select repositories → spain-dc-map**,
   **Permissions → Repository permissions → Contents: Read and write**. Generate, copy the
   `github_pat_...` string once — that's `GH_TOKEN`.

### B. Telegram bot (3 min, on your phone)
1. In Telegram, open **@BotFather** → `/newbot` → pick a name (e.g. `MarcDCWatch`) and a
   username ending in `bot`. Copy the token `123456:ABC...` — that's `TG_BOT_TOKEN`.
2. Open your new bot's chat and send it any message ("hola").
3. In a browser: `https://api.telegram.org/bot<TOKEN>/getUpdates` — find `"chat":{"id":NNNNNN`.
   That number is `TG_CHAT_ID`.

### C. Server install (paste these, one block at a time — check prompt says root@hermes-agent!)
```bash
# from your Mac, in the siting-model folder:
scp -r hermes web/data/datacenters.json root@46.225.123.54:/root/dc_watch/

# on the server (ssh root@46.225.123.54):
cd /root/dc_watch
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp env.example .env && nano .env     # fill the 5 values (DeepSeek key is in /root/.hermes/.env)
.venv/bin/python seed_db.py datacenters.json          # → "seeded 200 projects"
.venv/bin/python dc_watch.py                          # first manual run; expect a Telegram digest
crontab -e                                            # add the line below
```
```
15 12 * * * cd /root/dc_watch && .venv/bin/python dc_watch.py >> cron.log 2>&1
*/2 * * * * /root/dc_watch/trigger_poll.sh
```
(`chmod +x trigger_poll.sh` after copying. The second line is the **manual-trigger poller**:
the viewer's "⚡ Trigger ingestion now" button writes `web/data/trigger.json` to the repo
using a token you paste once into the browser (stored in localStorage, nowhere else);
the VM notices within ≤2 min, runs the pipeline, publishes, and the page auto-reloads
when fresh data lands. Perfect for live demos.)

### D. Publish the viewer (on your Mac, once)
```bash
git clone git@github.com:YOURUSER/spain-dc-map.git ../spain-dc-map
./deploy_pages.sh        # re-run whenever the viewer changes
```
Viewer URL: `https://YOURUSER.github.io/spain-dc-map/` — the daily VM push updates
`web/data/dc_live.json` in the same repo, so the news layer refreshes itself.

## Design notes
- **Matching** news→project: company/municipality/name fuzzy score ≥0.6 joins an existing
  project; otherwise a new project is auto-created (geocoded via Nominatim) flagged
  `review=1` and shown "unreviewed" in the viewer. Watch the digest for false merges.
- **Status only upgrades** (announced→construction→operating; `cancelled` always wins),
  so a retrospective article can't demote a live project.
- All state is one file: `dc_watch.sqlite`. Back it up occasionally
  (`scp root@46.225.123.54:/root/dc_watch/dc_watch.sqlite .`).
- To re-run safely: `seen` table dedupes URLs; the LLM is never called twice for the same article.
- Ask Hermes things like "resume dc_watch.log" or wire it a skill later — the pipeline is
  deliberately plain cron so it can't be broken by agent behavior.
