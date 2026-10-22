-- Newly authored minimal schema; no production schema or data copied.
CREATE TABLE collection_coverage (
    attempt_id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    observation_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('complete','unknown','incomplete','failed'))
);
CREATE TABLE option_events (
    event_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    observation_date TEXT NOT NULL,
    option_type TEXT NOT NULL CHECK(option_type IN ('CALL','PUT')),
    premium REAL NOT NULL CHECK(premium >= 0),
    volume INTEGER NOT NULL CHECK(volume >= 0)
);
