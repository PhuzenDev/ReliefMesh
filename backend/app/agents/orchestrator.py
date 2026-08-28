"""
Orchestrator
============
The only class the API layer talks to. Wires evidence -> geo -> planning
-> constraint into one pipeline, holds the in-memory pipeline state
between cycles, and exposes the four things the demo script needs:

  1. run_cycle()            — full pass: reports -> checked mission proposals
  2. ingest_reports()       — add new/duplicate/contradicting reports, doesn't replan by itself
  3. handle_commander_decision() — approve/modify/reject a mission
  4. trigger_replan()       — road closes, crew drops out, or new evidence arrives
  5. reconcile_offline_batch() — apply a batch of field reports queued while offline,
                                  then replan once, not once-per-report

State lives in memory here on purpose — the DB/audit-store layer
(app/db/) should subscribe to the same `reliefmesh.agents` logger tree
this module and every agent write to, rather than this class knowing
about persistence directly.
"""

import logging
from typing import Dict, List, Optional
from uuid import UUID

from app.agents.constraint_agent import ConstraintAgent
from app.agents.evidence_agent import EvidenceAgent
from app.agents.geo_agent import GeoAgent
from app.agents.planning_agent import PlanningAgent
from app.models.schemas import (
    CommanderDecision,
    ConstraintCheckResult,
    Crew,
    EvidenceCluster,
    MissionProposal,
    MissionStatus,
    RawReport,
    SupplyInventory,
)

logger = logging.getLogger("reliefmesh.orchestrator")


class Orchestrator:
    def __init__(self) -> None:
        self.evidence_agent = EvidenceAgent()
        self.geo_agent = GeoAgent()
        self.planning_agent = PlanningAgent(self.geo_agent)
        self.constraint_agent = ConstraintAgent(self.geo_agent)

        # rolling pipeline state
        self._reports: List[RawReport] = []
        self._clusters: List[EvidenceCluster] = []
        self._proposals: Dict[UUID, MissionProposal] = {}
        self._checks: Dict[UUID, ConstraintCheckResult] = {}
        self._crews: List[Crew] = []
        self._inventories: List[SupplyInventory] = []

    # -- setup -----------------------------------------------------------

    def register_crews(self, crews: List[Crew]) -> None:
        self._crews = crews

    def register_inventories(self, inventories: List[SupplyInventory]) -> None:
        self._inventories = inventories

    # -- main pipeline -----------------------------------------------------

    async def ingest_reports(self, reports: List[RawReport]) -> None:
        """Add reports to the pool without running a full cycle — lets the
        API batch several arrivals before paying for a replan."""
        self._reports.extend(reports)
        logger.info("reports_ingested", extra={"count": len(reports), "pool_size": len(self._reports)})

    async def run_cycle(self) -> List[dict]:
        """
        Full pipeline pass. Returns commander-facing mission cards:
        proposal + its constraint verdict, sorted by priority.
        """
        self._clusters = await self.evidence_agent.run(self._reports)
        clusters_by_id = {c.cluster_id: c for c in self._clusters}

        proposals = await self.planning_agent.run(self._clusters, self._crews, self._inventories)
        self._proposals = {p.mission_id: p for p in proposals}

        crews_by_id = {c.crew_id: c for c in self._crews}
        checks = await self.constraint_agent.run(proposals, clusters_by_id, crews_by_id, self._inventories)
        self._checks = {c.mission_id: c for c in checks}

        return self._commander_view()

    async def trigger_replan(self, reason: str) -> List[dict]:
        """
        Re-run planning + constraint checks against current geo/crew/supply
        state without re-clustering evidence (evidence doesn't change just
        because a road closed). Use ingest_reports + run_cycle instead when
        new evidence is the trigger.
        """
        logger.info("replan_triggered", extra={"reason": reason})
        proposals = await self.planning_agent.run(self._clusters, self._crews, self._inventories)
        self._proposals = {p.mission_id: p for p in proposals}

        clusters_by_id = {c.cluster_id: c for c in self._clusters}
        crews_by_id = {c.crew_id: c for c in self._crews}
        checks = await self.constraint_agent.run(proposals, clusters_by_id, crews_by_id, self._inventories)
        self._checks = {c.mission_id: c for c in checks}

        return self._commander_view()

    # -- human-in-the-loop --------------------------------------------------

    async def handle_commander_decision(self, decision: CommanderDecision) -> Optional[MissionProposal]:
        proposal = self._proposals.get(decision.mission_id)
        if proposal is None:
            logger.warning("decision_for_unknown_mission", extra={"mission_id": str(decision.mission_id)})
            return None

        proposal.status = decision.decision
        if decision.decision == MissionStatus.MODIFIED and decision.modifications:
            for field, value in decision.modifications.items():
                if hasattr(proposal, field):
                    setattr(proposal, field, value)

        logger.info(
            "commander_decision_applied",
            extra={
                "mission_id": str(proposal.mission_id),
                "decision": decision.decision.value,
                "decided_by": decision.decided_by,
            },
        )

        # Approving a mission consumes a crew — mark unavailable so the
        # next planning cycle doesn't double-book it.
        if decision.decision == MissionStatus.APPROVED and proposal.crew_id:
            for crew in self._crews:
                if crew.crew_id == proposal.crew_id:
                    crew.available = False

        return proposal

    # -- offline reconciliation ----------------------------------------------

    async def reconcile_offline_batch(self, queued_reports: List[RawReport]) -> List[dict]:
        """
        Apply a batch of reports a field team queued while disconnected,
        preserving their original received_at timestamps (already set on
        each RawReport client-side) so evidence clustering and history
        stay accurate, then replan once for the whole batch.
        """
        logger.info("offline_batch_reconciling", extra={"count": len(queued_reports)})
        await self.ingest_reports(queued_reports)
        return await self.run_cycle()

    # -- view helpers -----------------------------------------------------

    def commander_view(self) -> List[dict]:
        """Public read of the current commander-facing state without
        forcing a replan — for GET-style API/WS reads between cycles."""
        return self._commander_view()

    def _commander_view(self) -> List[dict]:
        cards = []
        for mission_id, proposal in self._proposals.items():
            check = self._checks.get(mission_id)
            cards.append({
                "proposal": proposal,
                "check": check,
            })
        cards.sort(key=lambda c: c["proposal"].priority_score, reverse=True)
        return cards