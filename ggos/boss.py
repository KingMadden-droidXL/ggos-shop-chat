"""BossAgent — one constructor signature, used the same way everywhere.

run_full_cycle() performs four real steps against the local database:
  1. verify_state   — DB reachable, schema version current
  2. generate_plan  — built from real counts (recent events, pending decisions)
  3. execute_plan   — writes a real agent_runs row plus one event per step
  4. summarize      — returns a real summary dict

Anything not yet real is marked STUB in its docstring and raises
NotImplementedError. There is no simulated intelligence in this module:
the old "market signals" returned random numbers and the old content
transformer returned canned copy — both are removed, not repaired.
"""
import logging
from pathlib import Path

from . import config, database as db

logger = logging.getLogger("ggos.boss")


class BossAgent:
    def __init__(self, name="GANGSTER_GOD", db_path=None):
        self.name = name
        self.db_path = Path(db_path) if db_path else config.DB_PATH

    # -- real cycle steps -------------------------------------------------

    def verify_state(self):
        """Real check: can we open the DB, and is the schema version current?"""
        conn = db.get_connection(self.db_path)
        try:
            version = db.current_version(conn)
            ok = version == db.SCHEMA_VERSION
            return {
                "ok": ok,
                "schema_version": version,
                "expected": db.SCHEMA_VERSION,
                "db_path": str(self.db_path),
            }
        finally:
            conn.close()

    def generate_plan(self):
        """Real plan derived from real data: pending decisions + recent volume."""
        conn = db.get_connection(self.db_path)
        try:
            day_events = conn.execute(
                "SELECT COUNT(*) AS c FROM events"
                " WHERE timestamp >= datetime('now', '-1 day')"
            ).fetchone()["c"]
            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM decisions WHERE approved = 0"
            ).fetchone()["c"]
            plan = []
            if pending:
                plan.append(f"review {pending} unapproved decision(s)")
            plan.append(f"ledger check: {day_events} event(s) in last 24h")
            return {
                "pending_decisions": pending,
                "events_24h": day_events,
                "plan": plan,
            }
        finally:
            conn.close()

    def execute_plan(self, plan):
        """Real execution: persist the cycle as an agent_runs row + events."""
        conn = db.get_connection(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO agent_runs (agent_name, status) VALUES (?, 'running')",
                (self.name,),
            )
            run_id = cur.lastrowid
            for step in plan["plan"]:
                db.insert_event(
                    conn, "cycle_step", agent_name=self.name, description=step
                )
            conn.execute(
                "UPDATE agent_runs SET finished_at = datetime('now'),"
                " status = 'done', summary = ? WHERE id = ?",
                (f"executed {len(plan['plan'])} step(s)", run_id),
            )
            conn.commit()
            return {"run_id": run_id, "steps_executed": len(plan["plan"])}
        finally:
            conn.close()

    def run_full_cycle(self):
        logger.info("[%s] cycle start (db=%s)", self.name, self.db_path)
        state = self.verify_state()
        if not state["ok"]:
            raise RuntimeError(f"schema mismatch: {state}")
        plan = self.generate_plan()
        result = self.execute_plan(plan)
        summary = {"agent": self.name, "ok": True, "state": state,
                   "plan": plan["plan"], **result}
        logger.info("[%s] cycle complete: %s", self.name, summary)
        return summary

    # -- explicit stubs (not implemented, not faked) ----------------------

    def scan_market_signals(self):
        """STUB — not implemented. The previous version returned random numbers
        labeled as market data. Real market intelligence does not exist yet."""
        raise NotImplementedError("scan_market_signals is a stub")

    def transform_content(self, text):
        """STUB — not implemented. The previous version returned canned copy
        regardless of input. No model call happens here."""
        raise NotImplementedError("transform_content is a stub")
