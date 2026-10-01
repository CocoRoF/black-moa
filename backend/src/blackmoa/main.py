"""black-moa backend — FastAPI app. BLAS thread pins MUST precede any numpy import (plan/27 함정 2)."""
from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")
os.environ.setdefault("GENY_CLI_PREWARM", "0")

import asyncio  # noqa: E402
import contextlib  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from blackmoa.api import (  # noqa: E402
    admin,
    admin_connections,
    admin_downloads,
    admin_holidays,
    agents,
    auth,
    blog,
    calendar,
    chat,
    community,
    companies,
    company_verify,
    credits,
    downloads,
    drive,
    files,
    health,
    inbox,
    integrations,
    internal_mcp,
    knowledge,
    mail,
    misc,
    network,
    notifications,
    public,
    relationship,
    relay,
    room_grants,
    rooms,
    schedule,
    studio,
    uploads,
    users,
)
from blackmoa.config import get_settings  # noqa: E402
from blackmoa.core.auth_middleware import AuthGateMiddleware  # noqa: E402
from blackmoa.core.errors import BlackMoaError  # noqa: E402
from blackmoa.core.logging import get_logger, setup_logging  # noqa: E402
from blackmoa.core.security import validate_security_settings  # noqa: E402
from blackmoa.core.traffic import TrafficMiddleware  # noqa: E402
from blackmoa.core.watchdog import install_loop_watchdog  # noqa: E402
from blackmoa.db.session import session_scope  # noqa: E402
from blackmoa.memory.synapse import index_cache  # noqa: E402
from blackmoa.pipeline.runtime import runtimes  # noqa: E402
from blackmoa.services import accounts as A  # noqa: E402
from blackmoa.services import catalog as CAT  # noqa: E402
from blackmoa.services import credits as CR  # noqa: E402
from blackmoa.services import plans as P  # noqa: E402
from blackmoa.services.keycheck import verify_encryption_keys  # noqa: E402

log = get_logger("blackmoa.main")


async def _housekeeping() -> None:
    s = get_settings()
    while True:
        await asyncio.sleep(60)
        with contextlib.suppress(Exception):
            n = await runtimes.evict_idle(s.runtime_idle_minutes * 60)
            m = await index_cache.evict_idle(s.runtime_idle_minutes * 60 * 2)
            if n or m:
                log.info("evicted", runtimes=n, indexes=m)


async def _flush_traffic() -> None:
    """Write the request record, off every request's own path.

    Its own loop rather than a step in housekeeping: on a minute's cadence a restart threw
    away up to a minute of measurements, and the dashboard was a minute stale exactly when
    someone was watching it because something was wrong. A failure to store measurements
    must never be a failure to serve, so every round is suppressed.
    """
    while True:
        await asyncio.sleep(10)
        with contextlib.suppress(Exception):
            from blackmoa.db.session import session_scope as _scope
            from blackmoa.services import traffic as TR
            async with _scope() as db:
                if await TR.flush(db, limit=2000):
                    await db.commit()
        # …and what only this process can see, on the same cadence and for the same reason:
        # the console has to be able to add the worker in rather than showing whichever
        # process happened to answer (plan/32 §6).
        with contextlib.suppress(Exception):
            from blackmoa.db.session import session_scope as _scope2
            from blackmoa.services import procstats as PS
            async with _scope2() as db:
                await PS.publish(db, "api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    validate_security_settings()
    for p in (s.vault_root, s.upload_root, s.cache_root, s.data_dir / "cli-cwd"):
        with contextlib.suppress(Exception):
            p.mkdir(parents=True, exist_ok=True)
    # Before anything can call the API: the pinned engine sends sampling parameters the
    # installed SDK no longer takes, and every direct-API turn dies in the client.
    from blackmoa.providers.llm.anthropic_compat import install as install_anthropic_compat
    install_anthropic_compat()
    install_loop_watchdog()
    if s.fake_llm:
        from blackmoa.providers.llm.fake import register_fake

        register_fake()
    try:
        # Fail closed before serving: a signing-key rotation that orphaned the
        # derived Fernet key must not surface later as opaque 500s. A DB blip is
        # not that condition, so only the key verdict aborts startup.
        async with session_scope() as db:
            await verify_encryption_keys(db)
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001
        log.warning("could not verify encryption keys at startup")
    with contextlib.suppress(Exception):
        async with session_scope() as db:
            # After alembic, so a table added by a migration is readable the same minute.
            from blackmoa.services.dbview import ensure_role
            await ensure_role(db)
    # A ceiling on the role itself, as a backstop under the per-process pools (plan/32 §3).
    # The pools add up to well under this; the point is that adding a process by mistake
    # cannot exhaust the server and lock everyone out, including the console. Applied here
    # rather than by hand, so a rebuilt volume does not silently lose it.
    with contextlib.suppress(Exception):
        from sqlalchemy import text as _text
        async with session_scope() as db:
            user = (await db.execute(_text("SELECT current_user"))).scalar_one()
            await db.execute(_text(f'ALTER ROLE "{user}" CONNECTION LIMIT 100'))
    with contextlib.suppress(Exception):
        async with session_scope() as db:
            await P.ensure_default_plans(db)
            if not await CAT.list_models(db):
                await CAT.seed(db)
            from blackmoa.services import community as COMM
            await COMM.seed_boards(db)
            await COMM.migrate_board_icons(db)
            seeded = await A.ensure_default_admin(db)
            if seeded is not None:
                log.warning("seeded the default administrator - change its password in /app/settings",
                            email=seeded.email)
    try:
        async with session_scope() as db:
            recovered = await CR.recover_orphaned_turns(db)
            if recovered:
                log.warning("recovered orphaned turns after restart", count=recovered)
    except Exception:  # noqa: BLE001
        # Never silent: a failed sweep leaves credit holds stranded until the
        # worker's periodic reaper catches them.
        log.exception("startup turn/reservation recovery failed")
    hk = asyncio.create_task(_housekeeping(), name="housekeeping")
    tf = asyncio.create_task(_flush_traffic(), name="traffic-flush")
    log.info("blackmoa backend up", public_url=s.public_url)
    # The LISTEN connection belongs to the running loop, so it starts here rather than at
    # app construction time.
    with contextlib.suppress(Exception):
        from blackmoa.db.session import session_scope as _scope
        from blackmoa.services import claude_pool as _CP
        async with _scope() as _db:
            await _CP.adopt_legacy(_db)
    from blackmoa.core import bus
    from blackmoa.core.database import manager as dbm
    # The pool gets a supervisor: on a quiet service an outage is otherwise discovered by
    # the first user after it, rather than by us.
    dbm.start()
    bus.start()
    try:
        yield
    finally:
        hk.cancel()
        tf.cancel()
        # One last round, so the window an operator is looking at does not end early.
        with contextlib.suppress(Exception):
            from blackmoa.services import traffic as TR
            async with session_scope() as db:
                if await TR.flush(db, limit=5000):
                    await db.commit()
        with contextlib.suppress(Exception):
            await runtimes.close_all()
        await bus.stop()
        with contextlib.suppress(Exception):
            await dbm.stop()
    log.info("blackmoa backend down")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="black-moa API", version="0.1.0", lifespan=lifespan, docs_url="/docs" if s.debug else None, redoc_url=None,
                  openapi_url="/openapi.json" if s.debug else None)
    # Outermost, so it measures the whole request including the gate and every handler.
    app.add_middleware(TrafficMiddleware)
    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=[s.public_url, "http://localhost:3000"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Turn-Id", "X-RateLimit-Remaining"])

    @app.exception_handler(BlackMoaError)
    async def _blackmoa_error(request: Request, exc: BlackMoaError):
        headers = {}
        if exc.status == 429 and isinstance(exc.detail, dict) and exc.detail.get("retry_after"):
            headers["Retry-After"] = str(exc.detail["retry_after"])
        return JSONResponse(status_code=exc.status, content=exc.to_dict(), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "invalid request",
                                                                "detail": exc.errors()[:10]}})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled", path=request.url.path)
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "internal error"}})

    for r in (health, auth, calendar, users, agents, chat, public, knowledge, network, integrations, inbox, credits, notifications,
              uploads, files, drive, internal_mcp, misc, blog, companies, company_verify, community, relationship, studio, relay, rooms, room_grants, schedule, mail, admin,
              admin_connections, admin_holidays, admin_downloads, downloads):
        app.include_router(r.router)
    app.include_router(relay.internal)
    app.include_router(blog.feed_router)
    static_dir = s.data_dir / "public"
    with contextlib.suppress(Exception):
        static_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()
