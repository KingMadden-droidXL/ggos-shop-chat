"""Paper tracker — test whether scored moves mean anything, with no money.

A prediction is just a record: coin, price and score at scan time, plus
the direction of the past 24h move. Nothing is bought or sold.

Evaluation happens only after the horizon has passed, using a real
current price supplied by the caller. It records the forward return::

    forward_return_pct = (eval_price - scan_price) / scan_price * 100

Summary statistics are computed only from evaluated rows, and are
labelled exploratory until there are enough of them (30+). Two questions
are tracked separately, because they are different claims:

- Momentum: did the price keep going the same direction as the past
  24h move? (sign of ``change_24h_pct`` == sign of forward return)
- Size: did bigger past moves come before bigger forward moves, in
  either direction? (mean absolute forward return, split at the median
  ``raw_alpha``)

No claim of an edge is made here, and no trade is ever placed from
these numbers.
"""
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

MIN_EVALUATED_FOR_A_CLAIM = 30


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def record_prediction(
    conn,
    *,
    coin_id: str,
    scanned_at: str,
    price_usd: float,
    change_24h_pct: float,
    composite_score: float,
    raw_alpha: float,
    volatility: float,
    horizon_hours: float = 24.0,
    decision_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Record one paper prediction. Re-recording the same coin/time/horizon
    returns the existing row instead of duplicating it."""
    if not coin_id or not isinstance(coin_id, str):
        raise ValueError("coin_id must be a non-empty string")
    if horizon_hours < 0:
        raise ValueError("horizon_hours must be >= 0")
    for name, value in (
        ("price_usd", price_usd),
        ("change_24h_pct", change_24h_pct),
        ("composite_score", composite_score),
        ("raw_alpha", raw_alpha),
        ("volatility", volatility),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if price_usd <= 0:
        raise ValueError("price_usd must be > 0")
    _parse_time(scanned_at)

    existing = conn.execute(
        "SELECT * FROM paper_predictions"
        " WHERE coin_id = ? AND scanned_at = ? AND horizon_hours = ?",
        (coin_id, scanned_at, float(horizon_hours)),
    ).fetchone()
    if existing:
        return dict(existing)

    cur = conn.execute(
        "INSERT INTO paper_predictions (coin_id, decision_id, scanned_at,"
        " price_usd, change_24h_pct, composite_score, raw_alpha, volatility,"
        " horizon_hours) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            coin_id,
            decision_id,
            scanned_at,
            float(price_usd),
            float(change_24h_pct),
            float(composite_score),
            float(raw_alpha),
            float(volatility),
            float(horizon_hours),
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM paper_predictions WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def list_predictions(conn, limit: int = 100) -> List[Dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM paper_predictions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    ]


def evaluate_due_predictions(
    conn,
    *,
    price_fetcher: Callable[[str], float],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Evaluate every prediction whose horizon has passed.

    ``price_fetcher(coin_id)`` must return the real current USD price.
    A failed fetch raises and leaves the row unevaluated — no guessed
    price is ever written. Each coin is fetched at most once per run.
    """
    now = now or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    rows = conn.execute(
        "SELECT * FROM paper_predictions WHERE evaluated_at IS NULL"
        " ORDER BY id"
    ).fetchall()

    prices: Dict[str, float] = {}
    evaluated: List[Dict[str, Any]] = []
    for row in rows:
        due_at = _parse_time(row["scanned_at"]) + timedelta(
            hours=float(row["horizon_hours"])
        )
        if now < due_at:
            continue
        coin_id = row["coin_id"]
        if coin_id not in prices:
            price = price_fetcher(coin_id)
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                raise TypeError(f"price_fetcher returned a non-number for {coin_id}")
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"price_fetcher returned an invalid price for {coin_id}")
            prices[coin_id] = float(price)
        eval_price = prices[coin_id]
        forward_return = (eval_price - float(row["price_usd"])) / float(
            row["price_usd"]
        ) * 100.0
        conn.execute(
            "UPDATE paper_predictions SET evaluated_at = ?, eval_price_usd = ?,"
            " forward_return_pct = ? WHERE id = ?",
            (now.isoformat(), eval_price, forward_return, row["id"]),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM paper_predictions WHERE id = ?", (row["id"],)
        ).fetchone()
        evaluated.append(dict(updated))
    return evaluated


def paper_summary(conn) -> Dict[str, Any]:
    """Summarise evaluated predictions only. No extrapolation."""
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM paper_predictions WHERE evaluated_at IS NOT NULL"
        ).fetchall()
    ]
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM paper_predictions"
        " WHERE evaluated_at IS NULL"
    ).fetchone()["c"]

    summary: Dict[str, Any] = {
        "evaluated": len(rows),
        "pending": pending,
        "enough_data_for_a_claim": len(rows) >= MIN_EVALUATED_FOR_A_CLAIM,
        "mean_forward_return_pct": None,
        "momentum_same_direction_rate": None,
        "mean_abs_forward_return_high_past_move_pct": None,
        "mean_abs_forward_return_low_past_move_pct": None,
    }
    if not rows:
        return summary

    returns = [float(r["forward_return_pct"]) for r in rows]
    summary["mean_forward_return_pct"] = round(statistics.fmean(returns), 4)

    same_direction = sum(
        1
        for r in rows
        if float(r["change_24h_pct"]) != 0
        and (float(r["change_24h_pct"]) > 0)
        == (float(r["forward_return_pct"]) > 0)
    )
    with_direction = sum(
        1 for r in rows if float(r["change_24h_pct"]) != 0
    )
    if with_direction:
        summary["momentum_same_direction_rate"] = round(
            same_direction / with_direction, 4
        )

    alphas = sorted(float(r["raw_alpha"]) for r in rows)
    median_alpha = statistics.median(alphas)
    high = [
        abs(float(r["forward_return_pct"]))
        for r in rows
        if float(r["raw_alpha"]) >= median_alpha
    ]
    low = [
        abs(float(r["forward_return_pct"]))
        for r in rows
        if float(r["raw_alpha"]) < median_alpha
    ]
    if high:
        summary["mean_abs_forward_return_high_past_move_pct"] = round(
            statistics.fmean(high), 4
        )
    if low:
        summary["mean_abs_forward_return_low_past_move_pct"] = round(
            statistics.fmean(low), 4
        )
    return summary
