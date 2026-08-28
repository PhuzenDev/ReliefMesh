"""
SQLAlchemy ORM tables — the persistence layer.

Deliberately separate from app/models/schemas.py: that file is the
in-process pipeline contract agents pass typed pydantic objects
through; these are DB rows. Keeping them apart means the agent team
can reshape schemas.py without touching migrations, and vice versa.
Translation between the two lives in repository.py.

Design choice worth knowing about: `Event` is the append-only audit
log AND the offline-sync mechanism. Every agent decision (via the
logging handler in audit.py) and every field-client sync batch lands
here, distinguished by `source`. `client_event_id` is the idempotency
key that makes offline sync safe to replay.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text,
    BigInteger,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# Every datetime the app generates (see app/models/schemas.py::_utcnow) is
# tz-aware UTC. These columns used to be plain DateTime (i.e. Postgres
# TIMESTAMP WITHOUT TIME ZONE), which made asyncpg reject any tz-aware
# value on insert. Use this everywhere instead of bare DateTime — see
# migrations/versions/0002_timezone_aware_datetimes.py for the matching
# column-type migration.
TZDateTime = DateTime(timezone=True)


# ---------------------------------------------------------------------------
# Pipeline entity snapshots (mirror app/models/schemas.py)
# ---------------------------------------------------------------------------

class ReportRow(Base):
    __tablename__ = "reports"

    report_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)
    source_reliability_hint = Column(Float, nullable=True)
    received_at = Column(TZDateTime, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    text = Column(Text, nullable=True)
    need_type = Column(String, nullable=False, default="unknown")
    people_affected = Column(Integer, nullable=True)
    raw_payload = Column(JSONB, nullable=False, default=dict)

    # Set once the evidence agent assigns this report to a cluster.
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("evidence_clusters.cluster_id"), nullable=True)


class EvidenceClusterRow(Base):
    __tablename__ = "evidence_clusters"

    cluster_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    member_report_ids = Column(JSONB, nullable=False, default=list)   # list[str(uuid)]
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    need_type = Column(String, nullable=False)
    people_affected_estimate = Column(Integer, nullable=True)
    reliability_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    contradictory = Column(Boolean, nullable=False, default=False)
    contradiction_notes = Column(Text, nullable=True)
    first_seen = Column(TZDateTime, nullable=False)
    last_seen = Column(TZDateTime, nullable=False)

    # NOT currently populated — app/models/schemas.py's EvidenceCluster has
    # no vulnerable_population / location_precision fields yet, so the
    # repository layer never sets these. Added now so no migration is
    # needed once the agent side adds that logic; defaults keep every
    # existing row valid in the meantime. See conversation notes re:
    # the brief's "don't expose exact vulnerable-population locations"
    # requirement — flagged to the agents side, not yet wired end-to-end.
    vulnerable_population = Column(Boolean, nullable=False, default=False)
    location_precision = Column(String, nullable=False, default="approximate")


class MissionProposalRow(Base):
    __tablename__ = "mission_proposals"

    mission_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("evidence_clusters.cluster_id"), nullable=False)

    # Not part of MissionProposal in schemas.py — reserved so replanning
    # history can be reconstructed by chaining mission_ids without a
    # migration later. NULL until the orchestrator starts passing it
    # (e.g. when a replan produces a new MissionProposal for a cluster
    # that already had one).
    supersedes_mission_id = Column(UUID(as_uuid=True), ForeignKey("mission_proposals.mission_id"), nullable=True)

    crew_id = Column(String, nullable=True)
    route_id = Column(String, nullable=True)
    supplies = Column(JSONB, nullable=False, default=dict)
    priority_score = Column(Float, nullable=False)
    eta_minutes = Column(Float, nullable=True)
    assumptions = Column(JSONB, nullable=False, default=list)
    status = Column(String, nullable=False, default="proposed")

    created_at = Column(TZDateTime, nullable=False, default=_utcnow)


class ConstraintCheckResultRow(Base):
    __tablename__ = "constraint_check_results"

    # Own PK (not mission_id) since a mission can be re-checked across
    # replanning cycles — we want every check kept, not just the latest.
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mission_id = Column(UUID(as_uuid=True), ForeignKey("mission_proposals.mission_id"), nullable=False)
    feasible = Column(Boolean, nullable=False)
    violations = Column(JSONB, nullable=False, default=list)   # [{code, message, severity}, ...]
    fairness_note = Column(Text, nullable=True)
<<<<<<< HEAD
    # Groq-generated plain-language rollup of `violations`, when present —
    # see app/agents/constraint_agent.py and models/schemas.py's matching
    # field. NULL whenever Groq wasn't configured or there were no
    # violations to explain.
    llm_explanation = Column(Text, nullable=True)
    checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
=======
    checked_at = Column(TZDateTime, nullable=False, default=_utcnow)
>>>>>>> ef1caa9 (frontend)


class CommanderDecisionRow(Base):
    __tablename__ = "commander_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mission_id = Column(UUID(as_uuid=True), ForeignKey("mission_proposals.mission_id"), nullable=False)
    decision = Column(String, nullable=False)          # approved | modified | rejected
    modifications = Column(JSONB, nullable=True)
    decided_by = Column(String, nullable=False)
    decided_at = Column(TZDateTime, nullable=False, default=_utcnow)


# ---------------------------------------------------------------------------
# Append-only audit log + offline-sync mechanism
# ---------------------------------------------------------------------------

class Event(Base):
    """
    Two writers, one table:
      - `source="agent_log"`: written synchronously by audit.AuditLogHandler
        every time any agent calls self._log_decision(...). client_event_id
        is NULL for these (server-generated, never replayed).
      - `source="client_offline_sync"`: written when a field client's
        queued actions are POSTed back after reconnecting. client_event_id
        is the client-generated idempotency key — same id posted twice is
        a no-op, which is what makes offline reconciliation safe.

    `id` is a plain autoincrement bigint used as the authoritative server
    ordering (important: NOT the same as `occurred_at`, which may be well
    in the past for a synced offline event).
    """
    __tablename__ = "events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    client_event_id = Column(String, nullable=True, unique=True, index=True)

    source = Column(String, nullable=False)        # "agent_log" | "client_offline_sync" | "api"
    agent = Column(String, nullable=True)           # e.g. "evidence_agent", "commander:<id>"
    event_type = Column(String, nullable=False)     # the _log_decision message, e.g. "mission_proposed"
    entity_type = Column(String, nullable=True)      # "report" | "cluster" | "mission" | ...
    entity_id = Column(String, nullable=True)

    context = Column(JSONB, nullable=False, default=dict)   # remaining _log_decision kwargs / sync payload
    level = Column(String, nullable=True)            # log level name, agent_log rows only

    occurred_at = Column(TZDateTime, nullable=False, default=_utcnow)
    recorded_at = Column(TZDateTime, nullable=False, default=_utcnow)
