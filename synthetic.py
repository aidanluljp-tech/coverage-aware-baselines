"""Deterministic invented fixtures. No external inputs or market data."""
from datetime import date, timedelta
from pathlib import Path
import sqlite3

SYMBOL = 'SYNTH_ORBIT'
PROVIDER = 'synthetic_alpha'


def fresh_connection():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript((Path(__file__).parent / 'fixtures' / 'schema.sql').read_text())
    return conn


def coverage(conn, day, status='complete', symbol=SYMBOL, provider=PROVIDER):
    conn.execute('INSERT INTO collection_coverage VALUES (NULL,?,?,?,?)',
                 (provider, symbol, day, status))


def event(conn, day, premium, volume=2, kind='CALL', symbol=SYMBOL,
          provider=PROVIDER):
    identity = str(conn.execute('SELECT COUNT(*) FROM option_events').fetchone()[0])
    conn.execute('INSERT INTO option_events VALUES (?,?,?,?,?,?,?)',
                 (identity, provider, symbol, day, kind, premium, volume))


def populate(conn, count=60):
    for i in range(count):
        day = (date(2040, 1, 1) + timedelta(days=i)).isoformat()
        coverage(conn, day)
        if i % 5:  # Each fifth observation is a certified zero.
            event(conn, day, (i + 1) * 10, kind='CALL' if i % 2 else 'PUT')
    conn.commit()


if __name__ == '__main__':
    # Portable text fixture that SQLite can execute in a fresh database.
    with fresh_connection() as conn:
        populate(conn)
        print('\n'.join(conn.iterdump()))
