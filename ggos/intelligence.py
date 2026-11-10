"""IntelligenceModule — decision scoring over real, read-only price data.

What is real here, and what is not:

- ``scan_market_signals`` now reads real prices from CoinGecko's public
  API (no key, no account, no money). One request per coin to
  ``/coins/{id}/market_chart`` for the last 24 hours, then ``raw_alpha``
  and ``volatility`` are computed from those actual price points:
  ``raw_alpha`` is the size of the 24h move in percent, ``volatility`` is
  the dispersion of the 24h prices (standard deviation / mean). No random
  numbers, no invented sources. The old invented sources
  (``DEX_Liquidity``, ``OrderBook_Depth``, ``Space_Compute_Data``,
  ``Agentic_Workflow_Index``) are gone.
- This module does NOT trade, does NOT predict, and does NOT make money
  on its own. A 24h move that already happened is not evidence the next
  move goes the same way. There is no exchange connection, no wallet,
  no capital, and no backtested edge in this tree. Every scored signal
  persists as ``HOLD`` (unapproved, unexecuted) for a human to review.
- If the price API fails or rate-limits (HTTP 429), the scan raises
  instead of falling back to made-up data. Do not retry in a tight loop.
- ``causal.world_model.CausalWorldModel`` still does not exist, so
  ``causal_status`` stays ``NOT_EVALUATED``. The ``decisions`` /
  ``agent_runs`` writes use the real schema in ``ggos.database``.
- Paper tracking (``ggos.paper_tracker``) records each live scan's price
  and score, then evaluates it only after the horizon passes, against a
  fresh real price. No money, no trades, and no edge is claimed until
  at least 30 evaluated predictions exist — and even then the summary
  is exploratory, not a promise.

Scoring (kept from the paste, inputs now measured, not supplied)::

    composite = (raw_alpha * 0.7) / (1.0 + volatility)

Sync-only, stdlib only. The only network use is the read-only price
fetch in ``scan_market_signals``.
"""
import json
import math
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import config, database as db, paper_tracker
from .money_engine import get_balance_cents

AGENT_NAME = "IntelligenceModule"
DEFAULT_COIN_IDS = ("bitcoin", "ethereum")
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
_COIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_COINS_PER_SCAN = 5
_FETCH_TIMEOUT_SECONDS = 10


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_json(url: str) -> Dict[str, Any]:
    """GET one JSON document. Raises RuntimeError on any failure.

    No retry, no fallback data. A 429 is reported as rate-limiting so the
    caller stops instead of hammering the free endpoint.
    """
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "GGOS/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError(
                "CoinGecko rate limited (HTTP 429): stop, do not retry "
                "in a loop; scan again later."
            ) from exc
        raise RuntimeError(f"CoinGecko request failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"CoinGecko request failed: {exc.reason}") from exc
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("CoinGecko returned non-JSON data") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("CoinGecko returned an unexpected payload shape")
    return payload


def _signal_from_chart(
    coin_id: str, payload: Dict[str, Any], fetched_at: str
) -> Dict[str, Any]:
    """Build one signal from a real ``market_chart`` payload.

    ``payload["prices"]`` is a list of ``[timestamp_ms, price_usd]`` pairs.
    """
    prices_raw = payload.get("prices")
    if not isinstance(prices_raw, list) or len(prices_raw) < 2:
        raise RuntimeError(f"CoinGecko returned too few prices for {coin_id}")
    prices: List[float] = []
    for point in prices_raw:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise RuntimeError(f"CoinGecko returned a bad price point for {coin_id}")
        price = point[1]
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise RuntimeError(f"CoinGecko returned a non-numeric price for {coin_id}")
        if not math.isfinite(price) or price <= 0:
            raise RuntimeError(f"CoinGecko returned an invalid price for {coin_id}")
        prices.append(float(price))

    first, last = prices[0], prices[-1]
    change_pct = (last - first) / first * 100.0
    mean_price = statistics.fmean(prices)
    dispersion = statistics.pstdev(prices) / mean_price if mean_price else 0.0
    volatility = min(1.0, max(0.0, dispersion))

    return {
        "source": f"CoinGecko:{coin_id}",
        "coin_id": coin_id,
        "raw_alpha": round(abs(change_pct), 4),
        "volatility": round(volatility, 6),
        "price_usd": last,
        "first_price_usd": first,
        "change_24h_pct": round(change_pct, 4),
        "prices_count": len(prices),
        "fetched_at": fetched_at,
    }


def _validate_coin_ids(coin_ids: Sequence[str]) -> List[str]:
    if not isinstance(coin_ids, (list, tuple)) or not coin_ids:
        raise ValueError("coin_ids must be a non-empty list/tuple")
    if len(coin_ids) > _MAX_COINS_PER_SCAN:
        raise ValueError(f"at most {_MAX_COINS_PER_SCAN} coins per scan")
    seen: List[str] = []
    for coin_id in coin_ids:
        if not isinstance(coin_id, str) or not _COIN_ID_RE.match(coin_id):
            raise ValueError(f"invalid coin id: {coin_id!r}")
        if coin_id not in seen:
            seen.append(coin_id)
    return seen


class IntelligenceModule:
    """Fetch real prices, score the moves, persist the scores for review."""

    def __init__(
        self,
        db_path=None,
        name: str = AGENT_NAME,
        fetch_json: Optional[Callable[[str], Dict[str, Any]]] = None,
        coin_ids: Sequence[str] = DEFAULT_COIN_IDS,
        base_url: str = COINGECKO_BASE_URL,
    ):
        self.name = name
        self.db_path = Path(db_path) if db_path else config.DB_PATH
        # Injectable only so tests can run without the network. Production
        # uses the real HTTP fetcher above; tests supply fixed chart data
        # and must say so in the test name.
        self._fetch_json = fetch_json or _fetch_json
        self.coin_ids = _validate_coin_ids(coin_ids)
        self.base_url = base_url.rstrip("/")

    # -- real scan: read-only public prices -------------------------------

    def scan_market_signals(
        self, coin_ids: Optional[Sequence[str]] = None
    ) -> List[Dict[str, Any]]:
        """Fetch real 24h price charts and compute one signal per coin.

        Read-only: no account, no key, no trade, no money moves. Raises
        on API failure or bad data instead of inventing a signal.
        """
        ids = _validate_coin_ids(coin_ids) if coin_ids is not None else self.coin_ids
        fetched_at = _utc_now()
        signals = []
        for coin_id in ids:
            query = urllib.parse.urlencode({"vs_currency": "usd", "days": "1"})
            url = (
                f"{self.base_url}/coins/{urllib.parse.quote(coin_id)}"
                f"/market_chart?{query}"
            )
            payload = self._fetch_json(url)
            signals.append(_signal_from_chart(coin_id, payload, fetched_at))
        return signals

    # -- pure scoring ------------------------------------------------------

    def compute_decision_score(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Score one signal. Persists nothing.

        ``signal`` must carry ``source`` (str), ``raw_alpha`` (finite number)
        and ``volatility`` (finite number in [0, 1]). Anything else raises
        ``ValueError``/``TypeError`` rather than being silently defaulted.
        Extra fields (price, change, coin) are carried through untouched.
        """
        if not isinstance(signal, dict):
            raise TypeError("signal must be a dict")
        source = signal.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("signal['source'] must be a non-empty string")
        raw_alpha = signal.get("raw_alpha")
        volatility = signal.get("volatility")
        if raw_alpha is None:
            raise ValueError("signal['raw_alpha'] is required")
        if volatility is None:
            raise ValueError("signal['volatility'] is required")
        if isinstance(raw_alpha, bool) or not isinstance(raw_alpha, (int, float)):
            raise TypeError("signal['raw_alpha'] must be a number")
        if isinstance(volatility, bool) or not isinstance(volatility, (int, float)):
            raise TypeError("signal['volatility'] must be a number")
        if not math.isfinite(raw_alpha) or not math.isfinite(volatility):
            raise ValueError("raw_alpha and volatility must be finite")
        if not 0.0 <= volatility <= 1.0:
            raise ValueError("signal['volatility'] must be in [0, 1]")

        # No causal model exists: risk is the measured volatility, plainly
        # labelled, and no causal approval is claimed.
        risk_score = float(volatility)
        composite_score = round((float(raw_alpha) * 0.7) / (1.0 + risk_score), 4)

        decision = {
            "source": source,
            "raw_alpha": float(raw_alpha),
            "risk_score": risk_score,
            "composite_score": composite_score,
            "action": "HOLD",
            "causal_status": "NOT_EVALUATED",
            "timestamp": _utc_now(),
        }
        for key in ("coin_id", "price_usd", "change_24h_pct", "prices_count", "fetched_at"):
            if key in signal:
                decision[key] = signal[key]
        return decision

    # -- paper tracking: record now, judge later, no money -----------

    def _current_price(self, coin_id: str) -> float:
        """Real current USD price via CoinGecko simple/price (read-only)."""
        query = urllib.parse.urlencode(
            {"ids": coin_id, "vs_currencies": "usd"}
        )
        payload = self._fetch_json(f"{self.base_url}/simple/price?{query}")
        try:
            price = payload[coin_id]["usd"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"CoinGecko returned no USD price for {coin_id}"
            ) from exc
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise RuntimeError(f"CoinGecko returned a non-numeric price for {coin_id}")
        if not math.isfinite(price) or price <= 0:
            raise RuntimeError(f"CoinGecko returned an invalid price for {coin_id}")
        return float(price)

    def evaluate_paper_predictions(
        self,
        price_fetcher: Optional[Callable[[str], float]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Evaluate due paper predictions against real current prices.

        Returns what was evaluated plus the summary. No trades, no money.
        """
        conn = db.get_connection(self.db_path)
        try:
            state = self._read_state(conn)
            if not state["ok"]:
                raise RuntimeError(f"schema mismatch: {state}")
            evaluated = paper_tracker.evaluate_due_predictions(
                conn,
                price_fetcher=price_fetcher or self._current_price,
                now=now,
            )
            if evaluated:
                db.insert_event(
                    conn,
                    "paper_evaluation",
                    agent_name=self.name,
                    description=f"evaluated {len(evaluated)} paper prediction(s)",
                    data=json.dumps({"evaluated_ids": [r["id"] for r in evaluated]}),
                )
            summary = paper_tracker.paper_summary(conn)
            conn.commit()
        finally:
            conn.close()
        return {"evaluated": evaluated, "paper_summary": summary}

    def paper_summary(self) -> Dict[str, Any]:
        conn = db.get_connection(self.db_path)
        try:
            return paper_tracker.paper_summary(conn)
        finally:
            conn.close()

    # -- real cycle: read real aggregates, persist real rows ---------------

    def _read_state(self, conn) -> Dict[str, Any]:
        version = db.current_version(conn)
        state: Dict[str, Any] = {
            "ok": version == db.SCHEMA_VERSION,
            "schema_version": version,
            "expected": db.SCHEMA_VERSION,
            "db_path": str(self.db_path),
            "events_24h": 0,
            "pending_decisions": 0,
            "balance_cents": 0,
        }
        if not state["ok"]:
            # Do not query tables that may not exist yet; the caller raises.
            return state
        state["events_24h"] = conn.execute(
            "SELECT COUNT(*) AS c FROM events"
            " WHERE timestamp >= datetime('now', '-1 day')"
        ).fetchone()["c"]
        state["pending_decisions"] = conn.execute(
            "SELECT COUNT(*) AS c FROM decisions WHERE approved = 0"
        ).fetchone()["c"]
        state["balance_cents"] = get_balance_cents(conn)
        return state

    def process_intelligence_cycle(
        self,
        signals: Optional[List[Dict[str, Any]]] = None,
        live: bool = False,
        record_paper: Optional[bool] = None,
        paper_horizon_hours: float = 24.0,
    ) -> Dict[str, Any]:
        """Score signals and persist the cycle.

        Pass ``signals`` explicitly, or ``live=True`` to fetch real prices
        first (never both). With neither, the cycle still runs on the real
        DB aggregates and records that no signals were supplied. It never
        invents signals, and nothing it persists is executable.

        ``record_paper`` defaults to ``live``: a live scan also records a
        paper prediction per coin (price + score, judged after
        ``paper_horizon_hours``). Supplied signals without a price/change
        cannot be paper-tracked and are skipped for that purpose only.
        """
        if live and signals is not None:
            raise ValueError("pass either signals or live=True, not both")
        if record_paper is None:
            record_paper = live
        if paper_horizon_hours < 0:
            raise ValueError("paper_horizon_hours must be >= 0")
        if live:
            signals = self.scan_market_signals()
        if signals is None:
            signals = []
        if not isinstance(signals, list):
            raise TypeError("signals must be a list of dicts")

        # Validate every signal before writing anything.
        decisions = [self.compute_decision_score(sig) for sig in signals]

        conn = db.get_connection(self.db_path)
        try:
            state = self._read_state(conn)
            if not state["ok"]:
                raise RuntimeError(f"schema mismatch: {state}")

            cur = conn.execute(
                "INSERT INTO agent_runs (agent_name, status) VALUES (?, 'running')",
                (self.name,),
            )
            run_id = cur.lastrowid

            persisted = []
            paper_recorded = 0
            for decision in decisions:
                rationale = json.dumps(decision)
                cur = conn.execute(
                    "INSERT INTO decisions (agent_name, action, rationale,"
                    " approved, executed) VALUES (?, ?, ?, 0, 0)",
                    (self.name, decision["action"], rationale),
                )
                decision_id = cur.lastrowid
                persisted.append({**decision, "id": decision_id})
                if record_paper and all(
                    k in decision
                    for k in ("coin_id", "price_usd", "change_24h_pct")
                ):
                    paper_tracker.record_prediction(
                        conn,
                        coin_id=decision["coin_id"],
                        scanned_at=decision.get("fetched_at") or decision["timestamp"],
                        price_usd=decision["price_usd"],
                        change_24h_pct=decision["change_24h_pct"],
                        composite_score=decision["composite_score"],
                        raw_alpha=decision["raw_alpha"],
                        volatility=decision["risk_score"],
                        horizon_hours=paper_horizon_hours,
                        decision_id=decision_id,
                    )
                    paper_recorded += 1
            paper_summary = paper_tracker.paper_summary(conn) if record_paper else None

            summary_text = (
                f"scored {len(persisted)} signal(s), "
                f"0 executable (all HOLD pending review)"
            )
            conn.execute(
                "UPDATE agent_runs SET finished_at = datetime('now'),"
                " status = 'done', summary = ? WHERE id = ?",
                (summary_text, run_id),
            )
            db.insert_event(
                conn,
                "intelligence_cycle",
                agent_name=self.name,
                description=summary_text,
                data=json.dumps(
                    {
                        "run_id": run_id,
                        "signals_scanned": len(persisted),
                        "live_scan": live,
                        "paper_predictions_recorded": paper_recorded,
                    }
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "agent": self.name,
            "ok": True,
            "run_id": run_id,
            "state": state,
            "live_scan": live,
            "total_signals_scanned": len(persisted),
            "executable_decisions": 0,
            "paper_predictions_recorded": paper_recorded,
            "paper_summary": paper_summary,
            "decisions": persisted,
            "completed_at": _utc_now(),
        }


if __name__ == "__main__":
    intel = IntelligenceModule()
    # Explicit entry point only: create/upgrade the schema, like the
    # app lifespan does. The class itself never auto-initializes, so a
    # schema mismatch still fails cleanly when called programmatically.
    # --live fetches real CoinGecko prices; without it, no scan happens.
    # --evaluate-paper judges due predictions; --paper-summary only reports.
    db.init_db(intel.db_path)
    if "--evaluate-paper" in sys.argv:
        result = intel.evaluate_paper_predictions()
        print("--- Paper Evaluation ---")
        print(json.dumps(result, indent=2, default=str))
    elif "--paper-summary" in sys.argv:
        print("--- Paper Summary ---")
        print(json.dumps(intel.paper_summary(), indent=2))
    else:
        cycle = intel.process_intelligence_cycle(live="--live" in sys.argv)
        print("--- Intelligence Module Cycle ---")
        print(json.dumps(cycle, indent=2))
