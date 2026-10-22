"""Offline coverage-certified baseline reference library. See LICENSE.

Coverage is supplied by the caller; observation dates are not verified dates.
"""

from __future__ import annotations

# ─── MATURITY ─────────────────────────────────────────────────────────────────

def _maturity(n: int) -> str:
    """Map sample size to maturity level."""
    if n < 10:
        return "INSUFFICIENT_HISTORY"
    if n < 20:
        return "EARLY_BASELINE"
    if n < 60:
        return "20D_BASELINE"
    return "20D_60D_BASELINE"


# ─── PERCENTILE ───────────────────────────────────────────────────────────────

def _percentile(history: list[float], current: float) -> float:
    """Deterministic empirical mid-rank percentile.

    percentile = 100 × (less + 0.5 × equal) / N
    """
    if not history:
        return 0.0
    less = sum(1 for v in history if v < current)
    equal = sum(1 for v in history if v == current)
    return 100.0 * (less + 0.5 * equal) / len(history)


# ─── RARITY ───────────────────────────────────────────────────────────────────

def _rarity(percentile: float, maturity: str) -> str | None:
    """Map percentile + maturity to rarity label.

    Returns None for early/insufficient maturity.
    """
    if maturity in ("INSUFFICIENT_HISTORY", "EARLY_BASELINE"):
        return None
    p = percentile
    if p < 75:
        return "NORMAL"
    if p < 90:
        return "ELEVATED"
    if p < 97:
        return "HIGH"
    if p < 99:
        return "EXTREME"
    return "EXCEPTIONAL"


# ─── WINDOW ───────────────────────────────────────────────────────────────────

def _window(values: list[float], size: int) -> list[float]:
    """Last `size` values from an ordered list."""
    return values[-size:] if len(values) >= size else values


def _median(vals: list[float]) -> float:
    """Simple median (sorted)."""
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _mean(vals: list[float]) -> float:
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def _vs_median_pct(current: float, median_val: float) -> float | None:
    if median_val == 0:
        return None
    return ((current - median_val) / median_val) * 100.0


# ─── DAILY METRICS ────────────────────────────────────────────────────────────

METRICS = [
    "event_count",
    "total_premium",
    "call_premium",
    "put_premium",
    "total_volume",
    "max_event_premium",
]


def _get_eligible_dates(conn, symbol: str, before_date: str, provider: str) -> list[str]:
    """Return sorted list of observation_date strings eligible for baseline.

    Eligibility: coverage.status='complete' AND observation_date < before_date.
    """
    rows = conn.execute("""
        SELECT DISTINCT cc.observation_date
        FROM collection_coverage cc
        WHERE cc.provider = ?
          AND cc.underlying_symbol = ?
          AND cc.status = 'complete'
          AND cc.observation_date < ?
        ORDER BY cc.observation_date ASC
    """, (provider, symbol, before_date)).fetchall()
    return [r["observation_date"] for r in rows]


def _get_daily_metrics(conn, symbol: str, observation_date: str, provider: str) -> dict:
    """Aggregate option_events for a specific symbol × observation_date.

    Returns dict with all 6 metrics. Complete-zero days return all zeros.
    """
    row = conn.execute("""
        SELECT
            COUNT(*)                                           AS event_count,
            COALESCE(SUM(premium), 0)                          AS total_premium,
            COALESCE(SUM(CASE WHEN option_type='CALL' THEN premium ELSE 0 END), 0) AS call_premium,
            COALESCE(SUM(CASE WHEN option_type='PUT'  THEN premium ELSE 0 END), 0) AS put_premium,
            COALESCE(SUM(volume), 0)                           AS total_volume,
            COALESCE(MAX(premium), 0)                          AS max_event_premium
        FROM option_events
        WHERE provider = ?
          AND underlying_symbol = ?
          AND observation_date = ?
    """, (provider, symbol, observation_date)).fetchone()
    return dict(row)


def _get_historical_series(conn, symbol: str, metric: str,
                           before_date: str, provider: str) -> list[float]:
    """Return ordered list of historical daily metric values.

    Driven by coverage (not option_events directly).
    Complete-zero days → value = 0.
    Unknown/incomplete/failed days → excluded.
    """
    eligible = _get_eligible_dates(conn, symbol, before_date, provider)
    values = []
    for md in eligible:
        daily = _get_daily_metrics(conn, symbol, md, provider)
        values.append(float(daily[metric]))
    return values


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def calculate_baseline(conn, symbol: str, metric: str,
                       current_value: float,
                       evaluation_date: str, *, provider: str) -> dict:
    """Compute baseline statistics for a symbol × metric.

    Args:
        conn: SQLite connection with sqlite3.Row row_factory
        symbol: fictional identifier, e.g. 'SYNTH_ORBIT'
        provider: explicit scope, used for BOTH coverage and event queries
        metric: one of METRICS
        current_value: today's aggregate value for this metric
        evaluation_date: YYYY-MM-DD of the observation date being evaluated

    Returns dict with status, windows, and statistics.
    """
    if metric not in METRICS:
        return {"status": "ERROR", "error": f"unknown metric: {metric}"}

    series = _get_historical_series(conn, symbol, metric, evaluation_date, provider)
    dates = _get_eligible_dates(conn, symbol, evaluation_date, provider)
    n = len(series)
    maturity = _maturity(n)

    result = {
        "provider": provider,
        "symbol": symbol,
        "metric": metric,
        "evaluation_date": evaluation_date,
        "current": current_value,
        "current_value": current_value,
        "baseline_start": dates[0] if dates else None,
        "baseline_end": dates[-1] if dates else None,
        "status": maturity,
        "sample_size": n,
        "required_for_early": 10,
        "required_for_20d": 20,
        "window_20": None,
        "window_60": None,
    }

    if n < 10:
        return result

    # Early baseline: compute with all available, no rarity
    if n < 20:
        med = _median(series)
        result["window_20"] = {
            "sample_size": n,
            "baseline_start": dates[0], "baseline_end": dates[-1],
            "median": med,
            "mean": _mean(series),
            "percentile": _percentile(series, current_value),
            "vs_median_pct": _vs_median_pct(current_value, med),
            "rarity": None,
            "provisional": True,
        }
        return result

    # 20D baseline
    w20 = _window(series, 20)
    med20 = _median(w20)
    vs20 = _vs_median_pct(current_value, med20)
    result["window_20"] = {
        "sample_size": len(w20),
        "baseline_start": dates[-20], "baseline_end": dates[-1],
        "median": med20,
        "mean": _mean(w20),
        "percentile": round(_percentile(w20, current_value), 1),
        "vs_median_pct": round(vs20, 1) if vs20 is not None else None,
        "rarity": _rarity(_percentile(w20, current_value), maturity),
        "provisional": False,
    }

    # 60D baseline (if enough data)
    if n >= 60:
        w60 = _window(series, 60)
        med60 = _median(w60)
        vs60 = _vs_median_pct(current_value, med60)
        result["window_60"] = {
            "sample_size": len(w60),
            "baseline_start": dates[-60], "baseline_end": dates[-1],
            "median": med60,
            "mean": _mean(w60),
            "percentile": round(_percentile(w60, current_value), 1),
            "vs_median_pct": round(vs60, 1) if vs60 is not None else None,
            "rarity": _rarity(_percentile(w60, current_value), maturity),
        }

    return result
