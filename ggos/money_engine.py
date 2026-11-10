"""Synchronous money ledger.

Hard rules (unchanged from the original money engine):
- This module is sync-only. No asyncio, no threads, no network calls.
- Every insert goes through transaction_exists(source, external_id) first.
- The ledger records money movement in the local DB only. Anything that
  touches the outside world lives in ggos.notifier behind its approval gate.
"""
import json

from . import database as db  # noqa: F401  (re-exported for convenience)


def transaction_exists(conn, source, external_id):
    row = conn.execute(
        "SELECT 1 FROM money WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    return row is not None


def record_transaction(conn, *, source, external_id, amount_cents, currency="USD",
                       direction, description=None, metadata=None):
    """Record one ledger entry. Idempotent on (source, external_id).

    Returns {"inserted": bool, "id": int}. A duplicate returns inserted=False
    with the existing row id — it never double-counts.
    """
    if direction not in ("in", "out"):
        raise ValueError("direction must be 'in' or 'out'")
    if not source or not external_id:
        raise ValueError("source and external_id are required for dedup")
    if transaction_exists(conn, source, external_id):
        row = conn.execute(
            "SELECT id FROM money WHERE source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()
        return {"inserted": False, "id": row["id"]}
    cur = conn.execute(
        "INSERT INTO money (source, external_id, amount_cents, currency,"
        " direction, description, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            source,
            external_id,
            int(amount_cents),
            currency,
            direction,
            description,
            json.dumps(metadata or {}),
        ),
    )
    conn.commit()
    return {"inserted": True, "id": cur.lastrowid}


def get_balance_cents(conn, currency="USD"):
    rows = conn.execute(
        "SELECT direction, amount_cents FROM money WHERE currency = ?", (currency,)
    ).fetchall()
    return sum(
        r["amount_cents"] if r["direction"] == "in" else -r["amount_cents"]
        for r in rows
    )


def list_transactions(conn, limit=100):
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM money ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    ]
