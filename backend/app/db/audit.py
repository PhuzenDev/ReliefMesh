"""
Audit logging handler.

Every agent's `self._log_decision(message, **context)` call (see
base_agent.py) goes through Python's stdlib `logging` module on the
"reliefmesh.agents" logger tree. This module attaches a Handler to
that tree so every decision is persisted automatically — no agent
file needs to import the DB layer or know it's being audited.

Why a SYNC engine here specifically, when the rest of the app is
async (see database.py): logging.Handler.emit() is called inline,
synchronously, from wherever logger.info(...) was invoked — there's
no `await` point available to hand off to an async session cleanly
without real complexity (a background asyncio task + queue, which is
more moving parts than a hackathon needs). Since psycopg2-binary is
already a dependency (for Alembic), it's a two-line sync engine and a
plain INSERT. This is the ONE place in the backend that talks to
Postgres synchronously — everywhere else, use database.py's async
session.

If the DB is unreachable, emit() must never raise (a logging handler
raising can crash the caller) — failures are printed to stderr and
swallowed.
"""
import json
import logging
import os
import sys
import uuid
from datetime import datetime

from sqlalchemy import create_engine, text

# Reuse the same DATABASE_URL as the async engine, but with a sync driver.
_ASYNC_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://reliefmesh:reliefmesh@localhost:5432/reliefmesh",
)
_SYNC_URL = _ASYNC_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

_sync_engine = create_engine(_SYNC_URL, echo=False, pool_pre_ping=True)

_INSERT_SQL = text(
    """
    INSERT INTO events
        (client_event_id, source, agent, event_type, entity_type, entity_id,
         context, level, occurred_at, recorded_at)
    VALUES
        (:client_event_id, :source, :agent, :event_type, :entity_type, :entity_id,
         :context, :level, :occurred_at, :recorded_at)
    """
)


class AuditLogHandler(logging.Handler):
    """Persists every LogRecord from the 'reliefmesh.agents' tree as an Event row."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            extra = record.__dict__
            agent = extra.get("agent")
            # Everything passed as **context to _log_decision ends up as
            # extra LogRecord attributes. Standard LogRecord attributes are
            # filtered out so `context` only holds what the agent actually
            # reported (cluster_id, mission_id, priority, etc.).
            standard_keys = logging.LogRecord(
                "", 0, "", 0, "", (), None
            ).__dict__.keys() | {"message", "asctime", "agent"}
            context = {k: v for k, v in extra.items() if k not in standard_keys}

            entity_id = None
            entity_type = None
            for candidate in ("mission_id", "cluster_id", "report_id", "road_id"):
                if candidate in context:
                    entity_id = str(context[candidate])
                    entity_type = candidate.replace("_id", "")
                    break

            with _sync_engine.begin() as conn:
                conn.execute(
                    _INSERT_SQL,
                    {
                        "client_event_id": None,
                        "source": "agent_log",
                        "agent": agent,
                        "event_type": record.getMessage(),
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "context": json.dumps(context, default=str),
                        "level": record.levelname,
                        "occurred_at": datetime.utcfromtimestamp(record.created),
                        "recorded_at": datetime.utcnow(),
                    },
                )
        except Exception as exc:  # noqa: BLE001 — a logging handler must never raise
            print(f"[AuditLogHandler] failed to persist audit event: {exc}", file=sys.stderr)


def install_audit_handler(level: int = logging.INFO) -> None:
    """
    Call once at app startup (see main.py). Idempotent — safe to call
    more than once (e.g. under a test runner that imports main twice)
    without double-attaching the handler.
    """
    logger = logging.getLogger("reliefmesh.agents")
    logger.setLevel(level)
    already_installed = any(isinstance(h, AuditLogHandler) for h in logger.handlers)
    if not already_installed:
        logger.addHandler(AuditLogHandler())
