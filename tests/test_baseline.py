"""Independent reference tests, using only newly generated SQLite data."""
from datetime import date, timedelta
from pathlib import Path
import unittest
import baseline as b
from synthetic import fresh_connection, coverage, event, populate, SYMBOL, PROVIDER


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_connection()
        self.addCleanup(self.conn.close)

    def result(self, metric='total_premium', value=20, day='2041-01-01',
               symbol=SYMBOL, provider=PROVIDER):
        return b.calculate_baseline(self.conn, symbol, metric, value, day,
                                    provider=provider)

    def series(self, metric='total_premium'):
        return b._get_historical_series(self.conn, SYMBOL, metric,
                                        '2041-01-01', PROVIDER)

    def test_complete_events_and_certified_zero_all_metrics(self):
        coverage(self.conn, '2040-01-01')
        coverage(self.conn, '2040-01-02')
        event(self.conn, '2040-01-01', 10, 3)
        event(self.conn, '2040-01-01', 30, 7, 'PUT')
        expected = [2, 40, 10, 30, 10, 30]
        for metric, value in zip(b.METRICS, expected):
            with self.subTest(metric=metric):
                self.assertEqual(self.series(metric), [value, 0])

    def test_unknown_incomplete_failed_and_missing_excluded(self):
        for i, status in enumerate(['unknown', 'incomplete', 'failed'], 1):
            day = f'2040-01-0{i}'
            coverage(self.conn, day, status)
            event(self.conn, day, 999)
        event(self.conn, '2040-01-04', 999)
        self.assertEqual(self.series(), [])
        self.assertIsNone(self.result()['window_20'])

    def test_duplicate_attempts_count_date_once_any_complete_wins(self):
        for status in ['failed', 'complete', 'complete', 'incomplete']:
            coverage(self.conn, '2040-01-01', status)
        event(self.conn, '2040-01-01', 42)
        self.assertEqual(self.series(), [42])
        self.assertEqual(self.result()['sample_size'], 1)

    def test_same_day_and_future_excluded(self):
        for day in ['2040-01-01', '2040-01-02', '2040-01-03']:
            coverage(self.conn, day)
            event(self.conn, day, 10)
        result = self.result(day='2040-01-02')
        self.assertEqual(result['sample_size'], 1)
        self.assertEqual(result['baseline_end'], '2040-01-01')

    def test_provider_and_symbol_isolate_coverage_and_events(self):
        coverage(self.conn, '2040-01-01')
        event(self.conn, '2040-01-01', 7)
        for symbol, provider in [(SYMBOL, 'synthetic_beta'), ('SYNTH_NEBULA', PROVIDER)]:
            for day in ['2040-01-01', '2040-01-02']:
                coverage(self.conn, day, symbol=symbol, provider=provider)
                event(self.conn, day, 900, symbol=symbol, provider=provider)
            other = self.result(symbol=symbol, provider=provider)
            self.assertEqual(other['sample_size'], 2)
        self.assertEqual(self.series(), [7])
        self.assertEqual(self.result()['sample_size'], 1)

    def test_percentile_ties_and_extremes(self):
        self.assertEqual(b._percentile([0, 10, 10, 20], 10), 50)
        self.assertEqual(b._percentile([0, 10], -1), 0)
        self.assertEqual(b._percentile([0, 10], 11), 100)
        self.assertEqual(b._percentile([3] * 20, 3), 50)

    def test_zero_median_is_undefined_ratio(self):
        for i in range(20):
            coverage(self.conn, (date(2040, 1, 1) + timedelta(days=i)).isoformat())
        r = self.result()['window_20']
        self.assertEqual(r['median'], 0)
        self.assertEqual(r['mean'], 0)
        self.assertIsNone(r['vs_median_pct'])

    def test_maturity_boundaries_and_latest_windows(self):
        expected = {9:'INSUFFICIENT_HISTORY', 10:'EARLY_BASELINE',
                    19:'EARLY_BASELINE', 20:'20D_BASELINE',
                    59:'20D_BASELINE', 60:'20D_60D_BASELINE'}
        for n, status in expected.items():
            with self.subTest(n=n):
                conn = fresh_connection()
                try:
                    for i in reversed(range(n)):
                        day = (date(2040, 1, 1) + timedelta(days=i)).isoformat()
                        coverage(conn, day)
                        event(conn, day, i + 1)
                    r = b.calculate_baseline(conn, SYMBOL, 'total_premium', 10,
                                              '2041-01-01', provider=PROVIDER)
                    self.assertEqual(r['status'], status)
                    self.assertEqual(r['sample_size'], n)
                    if n < 10:
                        self.assertIsNone(r['window_20'])
                    else:
                        w = r['window_20']
                        self.assertEqual(w['sample_size'], min(n, 20))
                        self.assertEqual(w['median'], (n+1)/2 if n<20 else n-9.5)
                        self.assertEqual(w['provisional'], n<20)
                        if n<20: self.assertIsNone(w['rarity'])
                    if n<60: self.assertIsNone(r['window_60'])
                    else: self.assertEqual(r['window_60']['median'], 30.5)
                finally:
                    conn.close()

    def test_rarity_thresholds(self):
        for percentile, label in [(74.9,'NORMAL'),(75,'ELEVATED'),(90,'HIGH'),
                                   (97,'EXTREME'),(99,'EXCEPTIONAL')]:
            self.assertEqual(b._rarity(percentile, '20D_BASELINE'), label)
        self.assertIsNone(b._rarity(100, 'EARLY_BASELINE'))

    def test_unknown_metric_and_empty_scope(self):
        self.assertEqual(self.result(metric='invalid')['status'], 'ERROR')
        self.assertEqual(self.result()['sample_size'], 0)
        self.assertIsNone(self.result()['baseline_start'])

    def test_sql_fixture_reproduces_generator(self):
        self.conn.executescript('DROP TABLE collection_coverage; DROP TABLE option_events;')
        self.conn.executescript((Path(__file__).resolve().parents[1] /
                                 'fixtures' / 'synthetic.sql').read_text())
        self.assertEqual(self.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.result()['sample_size'], 60)
        other = fresh_connection()
        try:
            populate(other)
            self.assertEqual('\n'.join(self.conn.iterdump()), '\n'.join(other.iterdump()))
        finally:
            other.close()


if __name__ == '__main__':
    unittest.main()
