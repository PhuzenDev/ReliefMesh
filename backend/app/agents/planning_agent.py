"""
Planning Agent
==============
Consumes EvidenceClusters + current GeoState + available Crews/Supplies
and produces MissionProposals. Priority ranking happens here (life-safety
and vulnerable-population needs first); the actual crew/supply assignment
is delegated to `optimizer.allocator` so the assignment algorithm can be
swapped (greedy -> CP-SAT) without touching this agent.

Every proposal carries `assumptions` — plain-language notes on what the
plan is trusting (e.g. "assumed route X open", "assumed cluster
reliability sufficient") so the constraint agent and commander both see
*why* a mission was proposed, not just *what*.
"""

from typing import Dict, List
from uuid import UUID

from app.agents.base_agent import BaseAgent
from app.agents.geo_agent import GeoAgent
from app.models.schemas import Crew, EvidenceCluster, MissionProposal, NeedType, SupplyInventory
from app.optimizer.allocator import ALLOCATOR

# Higher weight = served first when reliability/confidence are equal.
NEED_TYPE_WEIGHT: Dict[NeedType, float] = {
    NeedType.MEDICAL: 1.0,
    NeedType.RESCUE: 0.9,
    NeedType.EVACUATION: 0.8,
    NeedType.SHELTER: 0.55,
    NeedType.FOOD_WATER: 0.4,
    NeedType.UNKNOWN: 0.2,
}

# Rough per-incident supply draw by need type — replace with real
# logistics figures once data/inventories.json has real SKUs.
DEFAULT_SUPPLY_NEEDS: Dict[str, Dict[str, int]] = {
    NeedType.MEDICAL.value: {"medkits": 2, "water_liters": 10},
    NeedType.RESCUE.value: {"ropes": 1, "water_liters": 10},
    NeedType.SHELTER.value: {"tents": 1, "blankets": 4},
    NeedType.FOOD_WATER.value: {"food_kits": 3, "water_liters": 20},
    NeedType.EVACUATION.value: {"water_liters": 10},
}


class PlanningAgent(BaseAgent):
    name = "planning_agent"

    def __init__(self, geo_agent: GeoAgent) -> None:
        super().__init__()
        self.geo_agent = geo_agent

    async def run(
        self,
        clusters: List[EvidenceCluster],
        crews: List[Crew],
        inventories: List[SupplyInventory],
    ) -> List[MissionProposal]:
        prioritized = self._prioritize(clusters)

        assignments = ALLOCATOR(prioritized, crews, inventories, DEFAULT_SUPPLY_NEEDS)

        proposals: List[MissionProposal] = []
        for cluster in prioritized:
            assignment = assignments.get(cluster.cluster_id)
            if assignment is None:
                # No crew/supply available this cycle — still worth surfacing
                # as an unassigned proposal so the commander sees the backlog.
                proposals.append(self._unassigned_proposal(cluster))
                continue

            crew = next(c for c in crews if c.crew_id == assignment["crew_id"])
            route = self.geo_agent.find_route(cluster.lat, cluster.lon, crew.lat, crew.lon)

            assumptions = [
                f"Assumed cluster reliability {cluster.reliability_score:.2f} sufficient to dispatch.",
                f"Assumed route feasible at plan time (checked again by constraint agent).",
            ]
            if cluster.contradictory:
                assumptions.append("Cluster has contradictory reports — dispatch is provisional.")

            proposal = MissionProposal(
                cluster_id=cluster.cluster_id,
                crew_id=crew.crew_id,
                route_id=route["route_id"] if route else None,
                supplies=assignment["supplies"],
                priority_score=self._priority_score(cluster),
                eta_minutes=route["estimated_minutes"] if route else None,
                assumptions=assumptions,
            )
            proposals.append(proposal)

            self._log_decision(
                "mission_proposed",
                mission_id=str(proposal.mission_id),
                cluster_id=str(cluster.cluster_id),
                crew_id=crew.crew_id,
                priority=round(proposal.priority_score, 3),
            )

        return proposals

    # -- internals ------------------------------------------------------

    def _prioritize(self, clusters: List[EvidenceCluster]) -> List[EvidenceCluster]:
        return sorted(clusters, key=self._priority_score, reverse=True)

    def _priority_score(self, cluster: EvidenceCluster) -> float:
        need_weight = NEED_TYPE_WEIGHT.get(cluster.need_type, 0.2)
        scale = cluster.people_affected_estimate or 1
        # sqrt dampens runaway priority for very large headcounts while
        # still favoring bigger incidents; reliability/confidence discount
        # uncertain reports so they don't outrank well-verified smaller ones.
        return round(need_weight * (scale ** 0.5) * cluster.reliability_score * cluster.confidence, 4)

    def _unassigned_proposal(self, cluster: EvidenceCluster) -> MissionProposal:
        return MissionProposal(
            cluster_id=cluster.cluster_id,
            crew_id=None,
            route_id=None,
            supplies={},
            priority_score=self._priority_score(cluster),
            eta_minutes=None,
            assumptions=["No crew or supplies available this planning cycle — queued, not dropped."],
        )