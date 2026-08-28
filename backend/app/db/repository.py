"""
Repository layer: translates between app/models/schemas.py's pydantic
pipeline objects (what agents pass around) and app/db/models.py's ORM
rows (what's persisted). The API layer and orchestrator should import
from here rather than touching ORM models directly.

Note: agent-decision audit events are written separately and
automatically by audit.AuditLogHandler — nothing here needs to write
to `events` for that. The functions in this file that DO write to
`events` (record_offline_sync_batch) are for the other writer:
field-client offline sync.
"""
from typing import Iterable, List, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CommanderDecisionRow, ConstraintCheckResultRow, Event, EvidenceClusterRow,
    MissionProposalRow, ReportRow,
)
from app.models.schemas import (
    CommanderDecision, ConstraintCheckResult, EvidenceCluster, MissionProposal,
    RawReport,
)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

async def save_report(session: AsyncSession, report: RawReport) -> None:
    row = ReportRow(
        report_id=report.report_id,
        source=report.source.value,
        source_reliability_hint=report.source_reliability_hint,
        received_at=report.received_at,
        lat=report.lat,
        lon=report.lon,
        text=report.text,
        need_type=report.need_type.value,
        people_affected=report.people_affected,
        raw_payload=report.raw_payload,
    )
    session.add(row)
    await session.commit()


async def save_reports(session: AsyncSession, reports: Iterable[RawReport]) -> None:
    for r in reports:
        session.add(ReportRow(
            report_id=r.report_id, source=r.source.value,
            source_reliability_hint=r.source_reliability_hint, received_at=r.received_at,
            lat=r.lat, lon=r.lon, text=r.text, need_type=r.need_type.value,
            people_affected=r.people_affected, raw_payload=r.raw_payload,
        ))
    await session.commit()


# ---------------------------------------------------------------------------
# Evidence clusters
# ---------------------------------------------------------------------------

async def save_evidence_clusters(session: AsyncSession, clusters: Sequence[EvidenceCluster]) -> None:
    """Persists each cluster AND back-fills cluster_id on its member reports,
    in one transaction, so a report and its cluster never disagree."""
    for cluster in clusters:
        session.add(EvidenceClusterRow(
            cluster_id=cluster.cluster_id,
            member_report_ids=[str(rid) for rid in cluster.member_report_ids],
            lat=cluster.lat,
            lon=cluster.lon,
            need_type=cluster.need_type.value,
            people_affected_estimate=cluster.people_affected_estimate,
            reliability_score=cluster.reliability_score,
            confidence=cluster.confidence,
            contradictory=cluster.contradictory,
            contradiction_notes=cluster.contradiction_notes,
            first_seen=cluster.first_seen,
            last_seen=cluster.last_seen,
        ))
        for report_id in cluster.member_report_ids:
            result = await session.execute(select(ReportRow).where(ReportRow.report_id == report_id))
            report_row = result.scalar_one_or_none()
            if report_row is not None:
                report_row.cluster_id = cluster.cluster_id
    await session.commit()


# ---------------------------------------------------------------------------
# Mission proposals
# ---------------------------------------------------------------------------

async def save_mission_proposals(
    session: AsyncSession,
    proposals: Sequence[MissionProposal],
    supersedes: dict[UUID, UUID] | None = None,
) -> None:
    """
    `supersedes` is an optional {new_mission_id: old_mission_id} map for
    replanning — pass it once the orchestrator tracks "this proposal
    replaces that one" (see MissionProposalRow.supersedes_mission_id).
    Omit it and every proposal is just persisted standalone, which is
    fine for the first planning cycle.
    """
    supersedes = supersedes or {}
    for p in proposals:
        session.add(MissionProposalRow(
            mission_id=p.mission_id,
            cluster_id=p.cluster_id,
            supersedes_mission_id=supersedes.get(p.mission_id),
            crew_id=p.crew_id,
            route_id=p.route_id,
            supplies=p.supplies,
            priority_score=p.priority_score,
            eta_minutes=p.eta_minutes,
            assumptions=p.assumptions,
            status=p.status.value,
        ))
    await session.commit()


async def update_mission_status(session: AsyncSession, mission_id: UUID, status: str) -> None:
    result = await session.execute(select(MissionProposalRow).where(MissionProposalRow.mission_id == mission_id))
    row = result.scalar_one_or_none()
    if row is not None:
        row.status = status
        await session.commit()


# ---------------------------------------------------------------------------
# Constraint checks
# ---------------------------------------------------------------------------

async def save_constraint_results(session: AsyncSession, results: Sequence[ConstraintCheckResult]) -> None:
    for r in results:
        session.add(ConstraintCheckResultRow(
            mission_id=r.mission_id,
            feasible=r.feasible,
            violations=[v.model_dump() for v in r.violations],
            fairness_note=r.fairness_note,
            llm_explanation=r.llm_explanation,
        ))
    await session.commit()


# ---------------------------------------------------------------------------
# Commander decisions
# ---------------------------------------------------------------------------

async def save_commander_decision(session: AsyncSession, decision: CommanderDecision) -> None:
    session.add(CommanderDecisionRow(
        mission_id=decision.mission_id,
        decision=decision.decision.value,
        modifications=decision.modifications,
        decided_by=decision.decided_by,
        decided_at=decision.decided_at,
    ))
    # A commander decision also settles the mission's status — keep them
    # in the same transaction so a reader never sees one updated without
    # the other.
    result = await session.execute(select(MissionProposalRow).where(MissionProposalRow.mission_id == decision.mission_id))
    mission_row = result.scalar_one_or_none()
    if mission_row is not None:
        mission_row.status = decision.decision.value
    await session.commit()


# ---------------------------------------------------------------------------
# Offline sync — the OTHER writer to `events` (see audit.py docstring)
# ---------------------------------------------------------------------------

async def record_offline_sync_batch(session: AsyncSession, events: Sequence[dict]) -> dict:
    """
    Applies a batch of field-client events idempotently.
    Each event dict must have: client_event_id, event_type, entity_type,
    entity_id, payload, actor, occurred_at (see api_schemas.OfflineEventIn
    from the earlier DB-layer draft, or the equivalent shape your API
    routes define).

    Returns {"accepted": [...], "duplicates": [...]} — never raises for
    a duplicate, since resending an already-applied event must be a
    safe no-op (that's what makes offline queues reconcilable).
    """
    accepted: List[str] = []
    duplicates: List[str] = []

    for ev in events:
        existing = await session.execute(
            select(Event).where(Event.client_event_id == ev["client_event_id"])
        )
        if existing.scalar_one_or_none() is not None:
            duplicates.append(ev["client_event_id"])
            continue

        session.add(Event(
            client_event_id=ev["client_event_id"],
            source="client_offline_sync",
            agent=ev.get("actor"),
            event_type=ev["event_type"],
            entity_type=ev.get("entity_type"),
            entity_id=str(ev.get("entity_id")) if ev.get("entity_id") is not None else None,
            context=ev.get("payload", {}),
            level=None,
            occurred_at=ev["occurred_at"],
        ))
        accepted.append(ev["client_event_id"])

    await session.commit()
    return {"accepted": accepted, "duplicates": duplicates}
