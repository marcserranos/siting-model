# Deploying dc_watch v2 to the Hermes VM

The v2 knowledge base runs **alongside** v1, never over it. v1's `dc_watch.py` and
`dc_watch.sqlite` are left untouched the whole way through, so rollback is a one-line cron edit.

Run these yourself on your Mac / the server. **Check the prompt says `root@hermes-agent`** before
anything server-side (see the lesson in the project CLAUDE.md).

---

## 1. Back up the live v1 database (Mac)

```bash
scp root@46.225.123.54:/root/dc_watch/dc_watch.sqlite ~/Desktop/dc_watch_backup_$(date +%F).sqlite
```

## 2. Copy the v2 files up (Mac, from siting-model/)

```bash
scp hermes/kb.py hermes/kb_schema.sql hermes/resolver.py hermes/ingest.py hermes/enrich.py hermes/migrate_v1.py hermes/dc_watch2.py root@46.225.123.54:/root/dc_watch/
```

## 3. Migrate v1 → v2 (server)

```bash
ssh root@46.225.123.54
cd /root/dc_watch
.venv/bin/pip install -r requirements.txt      # picks up googlenewsdecoder if missing
.venv/bin/python migrate_v1.py dc_watch.sqlite dc_kb.sqlite
```

Expect a summary like `entities: 210 · observations: N · news: N · changelog: N`.
It refuses to overwrite an existing `dc_kb.sqlite`, and it never writes to `dc_watch.sqlite`.

## 4. Dry run — no writes, no publish (server)

```bash
.venv/bin/python dc_watch2.py --dry
```

Prints one line per article showing the resolution decision (`match` / `new` / `uncertain`) with
its score and reason. Check that renamed mentions of known projects say **match** rather than
**new**. A dry run operates on an in-memory copy, so it cannot touch the real DB.

## 5. First real run (server)

```bash
.venv/bin/python dc_watch2.py
```

Publishes `data/dc_live.json` to the Pages repo and sends the Telegram digest.
The export stays **backward-compatible** — it emits the flat `mw`/`inv`/`company` keys the current
map reads *and* the new `fields{}` (value + range + confidence + sources), so the live site keeps
working before the new UI ships.

## 6. Switch the cron over (server)

```bash
crontab -e
```

Change the daily line from `dc_watch.py` to `dc_watch2.py`, adding a small enrichment budget:

```
15 12 * * * cd /root/dc_watch && .venv/bin/python dc_watch2.py --enrich 5 >> cron.log 2>&1
```

`--enrich 5` visits the 5 stalest projects per run (~$0.11/month) to fill gaps the news never
covers. Drop it to run news-only; raise it to refresh the KB faster.

## Rollback

Point the cron line back at `dc_watch.py`. v1's database was never modified, so it resumes exactly
where it left off. `dc_kb.sqlite` can be deleted or kept for a later retry.

---

## Notes

- **One-time backfill.** After migrating, filling every sparse project at once costs ~$0.15:
  ```bash
  cd /root/dc_watch && DC_KB_PATH=/root/dc_watch/dc_kb.sqlite .venv/bin/python -c "
  import kb, enrich; con = kb.connect('dc_kb.sqlite')
  enrich.run_enrichment(con, 250, enrich.rss_search, enrich.deepseek_extract, 'backfill')"
  ```
  It commits per project and skips anything already enriched, so it is safe to re-run after an
  interruption.
- **Uncertain matches** are created flagged (`review=1`) with a changelog note naming the possible
  duplicate — they are never silently merged nor silently duplicated. The Telegram digest lists them.
- **Existing duplicates** already in the KB: `resolver.find_duplicates(con)` returns scored candidate
  pairs for review. It never merges automatically.
- **Backups.** `dc_kb.sqlite` is the only state that matters:
  `scp root@46.225.123.54:/root/dc_watch/dc_kb.sqlite .`
