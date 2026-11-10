"""FastAPI surface. Trigger endpoints require a bearer token.

No default secrets: if GGOS_API_TOKEN is unset, the protected endpoints
answer 503 instead of running. CORS is only enabled for explicitly listed
origins — never a wildcard, never with credentials.
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import config, database as db, shop_chat, versions
from .boss import BossAgent
from .money_engine import get_balance_cents, list_transactions, record_transaction

logger = logging.getLogger("ggos.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    version = db.init_db(config.DB_PATH)
    logger.info("DB ready at %s (schema v%s)", config.DB_PATH, version)
    yield


app = FastAPI(title="GGOS Core", lifespan=lifespan)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


def require_token(authorization: str = Header(default="")):
    if not config.API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="API token not configured (GGOS_API_TOKEN)."
            " Trigger endpoints are disabled.",
        )
    if authorization != f"Bearer {config.API_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid token")
    return True


@app.get("/health")
def health():
    return {
        "ok": True,
        "app_version": versions.APP_VERSION,
        "schema_version": db.SCHEMA_VERSION,
    }


@app.get("/v1/version")
def version():
    """Handshake endpoint. No token: any caller checks compatibility here
    before calling a trigger endpoint. The envelope is the same one a
    426 rejection carries, so a client can compare without a second call."""
    return versions.version_envelope()


async def _declared_client_version(request: Request):
    """client_version from a trigger body, or None when undeclared.

    Undeclared callers still run — enforcement starts when a caller
    declares a version, so existing callers keep working unchanged."""
    try:
        body = await request.json()
    except Exception:
        return None
    if isinstance(body, dict):
        v = body.get("client_version")
        return v if isinstance(v, str) else None
    return None


@app.post("/shop/chat")
def shop_chat_endpoint(payload: dict, request: Request):
    """Public shop-assistant chat. No token, no secrets, no money moves.

    Answers only from the live-store knowledge file + the verified FAQ
    in ggos/shop_chat.py. Rate-limited per caller; anything unknown hands
    off to Gavin instead of inventing an answer. CORS must list the store
    origin in GGOS_CORS_ORIGINS — never a wildcard.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    caller = forwarded.split(",")[0].strip() if forwarded else ""
    if not caller and request.client is not None:
        caller = request.client.host
    if not shop_chat.check_rate_limit(caller or "unknown"):
        raise HTTPException(
            status_code=429, detail="Slow down — one message at a time."
        )
    message = payload.get("message", "")
    if not isinstance(message, str):
        raise HTTPException(status_code=400, detail="message must be a string")
    return shop_chat.answer(message)


@app.post("/swarm/trigger")
async def trigger_cycle(request: Request, _: bool = Depends(require_token)):
    declared = await _declared_client_version(request)
    problem = versions.client_too_old(declared)
    if problem:
        raise HTTPException(
            status_code=426,
            detail={
                "error": "client_too_old",
                "detail": problem,
                **versions.version_envelope(),
            },
        )
    return BossAgent(db_path=config.DB_PATH).run_full_cycle()


@app.post("/godmode/sweep")
def godmode_sweep_endpoint(_: bool = Depends(require_token)):
    """Run the read-only Shopify godmode sweep and return the report.

    This is what the unlocked gateway page calls. Read-only: the change
    package in the report is always approved=False, applied=False.
    When the Shopify token is not in the server env, the body says
    status="token_not_set" and reports no numbers.
    """
    from api.godmode import run_godmode_report

    return run_godmode_report()


@app.get("/events")
def events(limit: int = 50, _: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.recent_events(conn, limit=limit)
    finally:
        conn.close()


@app.get("/agent-runs")
def agent_runs(
    agent_name: Optional[str] = None,
    limit: int = 100,
    _: bool = Depends(require_token),
):
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.get_agent_runs(conn, agent_name=agent_name, limit=limit)
    finally:
        conn.close()


@app.post("/money/record")
def money_record(payload: dict, _: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        return record_transaction(conn, **payload)
    finally:
        conn.close()


@app.get("/money/balance")
def money_balance(_: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        return {"balance_cents": get_balance_cents(conn)}
    finally:
        conn.close()


@app.get("/money/transactions")
def money_transactions(limit: int = 100, _: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        return list_transactions(conn, limit=limit)
    finally:
        conn.close()


# -- operations queue --------------------------------------------------------


@app.post("/tasks")
def tasks_create(payload: dict, _: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.create_task(
            conn,
            module=payload.get("module", ""),
            payload=payload.get("payload"),
            status=payload.get("status", "pending"),
        )
    finally:
        conn.close()


@app.get("/tasks")
def tasks_list(
    status: Optional[str] = None,
    limit: int = 100,
    _: bool = Depends(require_token),
):
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.list_tasks(conn, status=status, limit=limit)
    finally:
        conn.close()


@app.get("/tasks/{task_id}")
def tasks_get(task_id: int, _: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        task = db.get_task(conn, task_id)
    finally:
        conn.close()
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@app.patch("/tasks/{task_id}")
def tasks_update(task_id: int, payload: dict, _: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        task = db.update_task_status(conn, task_id, payload.get("status", ""))
    finally:
        conn.close()
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


# -- standard operating procedures -------------------------------------------


@app.post("/sops")
def sops_create(payload: dict, _: bool = Depends(require_token)):
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.create_sop(
            conn,
            title=payload.get("title", ""),
            trigger_event=payload.get("trigger_event", ""),
            steps=payload.get("steps", []),
        )
    finally:
        conn.close()


@app.get("/sops")
def sops_list(
    trigger_event: Optional[str] = None,
    limit: int = 100,
    _: bool = Depends(require_token),
):
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.list_sops(conn, trigger_event=trigger_event, limit=limit)
    finally:
        conn.close()


# -- prompt pipeline runs ------------------------------------------------------


@app.post("/prompt-runs")
def prompt_runs_create(payload: dict, _: bool = Depends(require_token)):
    """Record a real pipeline run. The API generates nothing — the caller
    supplies the input and the actual output that was produced."""
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.save_prompt_run(
            conn,
            pipeline_type=payload.get("pipeline_type", ""),
            input_raw=payload.get("input_raw", ""),
            outputs=payload.get("outputs", {}),
        )
    finally:
        conn.close()


@app.get("/prompt-runs")
def prompt_runs_list(
    pipeline_type: Optional[str] = None,
    limit: int = 100,
    _: bool = Depends(require_token),
):
    conn = db.get_connection(config.DB_PATH)
    try:
        return db.list_prompt_runs(
            conn, pipeline_type=pipeline_type, limit=limit
        )
    finally:
        conn.close()
