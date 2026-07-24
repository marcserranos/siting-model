-- dc_watch knowledge base — v2 normalized schema.
-- Design goals (from research): entity identity + aliases (cheap dedup), append-only
-- observations (facts never overwritten → range/confidence derived, no flip-flop),
-- human overrides + locks (agent respects hand edits), full changelog + run ledger
-- (traceability), enrichment cadence. No graph DB, no vector store — plain SQLite.

-- ---- canonical entities (projects; type leaves room for companies/locations later) ----
CREATE TABLE IF NOT EXISTS entities(
  id             TEXT PRIMARY KEY,          -- stable slug, e.g. 'aws-zaragoza-0007'
  type           TEXT NOT NULL DEFAULT 'project',
  canonical_name TEXT NOT NULL,
  country        TEXT DEFAULT 'ES',
  region         TEXT,
  lat            REAL,
  lon            REAL,
  status         TEXT,                       -- ratcheted (announced→…→operating; cancelled wins)
  src            TEXT,                       -- how the entity was born: seed|news|enrich
  review         INTEGER DEFAULT 0,          -- 1 = provisional, needs human confirmation
  created_at     TEXT,
  created_by     TEXT,                       -- run_id | 'seed' | 'human'
  updated_at     TEXT,
  updated_by     TEXT,
  last_enriched  TEXT                        -- NULL = never; drives the rolling enrichment queue
);

-- ---- surface names → entity. The alias hit-rate is what keeps LLM dedup calls rare. ----
CREATE TABLE IF NOT EXISTS aliases(
  alias      TEXT NOT NULL,                  -- normalized (lower, no diacritics, suffixes stripped)
  raw        TEXT,                           -- original form as seen
  entity_id  TEXT NOT NULL REFERENCES entities(id),
  source     TEXT,                           -- 'seed' | 'news' | 'human' | article url
  first_seen TEXT,
  PRIMARY KEY(alias, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_alias ON aliases(alias);

-- ---- append-only observations: the core of conflict handling. NEVER updated in place. ----
CREATE TABLE IF NOT EXISTS observations(
  id            INTEGER PRIMARY KEY,
  entity_id     TEXT NOT NULL REFERENCES entities(id),
  attribute     TEXT NOT NULL,               -- 'mw' | 'investment_eur_m' | 'status' | 'company' | ...
  value_num     REAL,                        -- numeric attributes
  value_text    TEXT,                        -- categorical/text attributes
  unit          TEXT,
  source_url    TEXT,
  source_tier   TEXT,                        -- official|wire|national|trade|research|local|unverified|human
  reported_date TEXT,                        -- when the source reported it (valid-time)
  first_seen    TEXT,                        -- when we recorded it (transaction-time)
  run_id        TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs ON observations(entity_id, attribute);

-- ---- human entity-resolution decisions. Resolver consults this BEFORE matching. ----
CREATE TABLE IF NOT EXISTS overrides(
  id       INTEGER PRIMARY KEY,
  entity_a TEXT,
  entity_b TEXT,
  decision TEXT,                             -- 'same' | 'different'
  note     TEXT,
  ts       TEXT
);

-- ---- fields a human pinned. Agent may log a disagreement but must not overwrite. ----
CREATE TABLE IF NOT EXISTS human_locks(
  entity_id TEXT NOT NULL REFERENCES entities(id),
  attribute TEXT NOT NULL,
  value_num REAL,
  value_text TEXT,
  note      TEXT,
  ts        TEXT,
  PRIMARY KEY(entity_id, attribute)
);

-- ---- news articles (kept; now tier-tagged and run-stamped) ----
CREATE TABLE IF NOT EXISTS news(
  id          INTEGER PRIMARY KEY,
  entity_id   TEXT REFERENCES entities(id),
  url         TEXT UNIQUE,
  source      TEXT,
  source_tier TEXT,
  date        TEXT,
  title       TEXT,
  event_type  TEXT,
  summary     TEXT,
  confidence  REAL,
  run_id      TEXT
);

-- ---- full audit trail: every create/update/enrich/merge/human_edit ----
CREATE TABLE IF NOT EXISTS changelog(
  id         INTEGER PRIMARY KEY,
  ts         TEXT,
  run_id     TEXT,
  entity_id  TEXT,
  action     TEXT,                           -- create|update|enrich|merge|status|alias|human_edit
  attribute  TEXT,
  old        TEXT,
  new        TEXT,
  source_url TEXT,
  note       TEXT
);
CREATE INDEX IF NOT EXISTS idx_chg ON changelog(entity_id);

-- ---- run ledger: how the platform is being maintained, run by run ----
CREATE TABLE IF NOT EXISTS runs(
  run_id      TEXT PRIMARY KEY,
  type        TEXT,                          -- watch | enrich | migrate | seed
  started_at  TEXT,
  finished_at TEXT,
  n_articles  INTEGER DEFAULT 0,
  n_new       INTEGER DEFAULT 0,
  n_changed   INTEGER DEFAULT 0,
  n_enriched  INTEGER DEFAULT 0,
  notes       TEXT
);

-- ---- URL dedup (unchanged role): the LLM is never called twice for the same article ----
CREATE TABLE IF NOT EXISTS seen(url TEXT PRIMARY KEY, ts TEXT, relevant INTEGER);
