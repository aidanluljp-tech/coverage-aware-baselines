"""Run an entirely in-memory, offline example."""
import json
from baseline import calculate_baseline
from synthetic import fresh_connection, populate, SYMBOL, PROVIDER


def main():
    conn = fresh_connection()
    try:
        populate(conn)
        print(json.dumps(calculate_baseline(conn, SYMBOL, 'total_premium', 450,
                         '2040-03-01', provider=PROVIDER), indent=2))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
