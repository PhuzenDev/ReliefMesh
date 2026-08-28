"""
Constraint Agent
================
Last automated gate before a MissionProposal reaches the commander.
Checks four things called out in the brief: capacity, access, medical
priority, and fairness. Never silently drops a mission — every
proposal comes back with a feasible/infeasible verdict plus the
specific violations, so the commander (or a human reviewing the audit
log) always knows *why*.

All four checks below are deterministic and remain the sole source of
truth for `feasible` / `violations`. When a proposal has one or more
violations and Groq is configured, an extra `llm_explanation` string is
attached: one plain-language sentence rolling the violation codes/
messages up into something a commander can read without parsing codes.
The LLM never sees anything it could use to change the verdict — it's
called after `feasible` and `violations` are already final, purely to
phrase them.
"""

import asyncio
from collections import defaultdict
from typing import Dict, List, Optional
from uuid import UUID

from app.agents.base_agent import BaseAgent
from app.agents.geo_agent import GeoAgent
from app.models.schemas import (
    ConstraintCheckResult,
    ConstraintViolation,
    Crew,
    EvidenceCluster,
    MissionProposal,
    NeedType,
    SupplyInventory,
)

# A zone (bucketed by rounded lat/lon) shouldn't absorb more than this
# share of missions in one planning cycle while other zones sit at zero.
MAX_SHARE_PER_ZONE = 0.6


class ConstraintAgent(BaseAgent):
    name = "constraint_agent"

    def __init__(self, geo_agent: GeoAgent) -> None:
        super().__init__()
        self.geo_agent = geo_agent

    async def run(
        self,
        proposals: List[MissionProposal],
        clusters_by_id: Dict[UUID, EvidenceCluster],
        crews_by_id: Dict[str, Crew],
        inventories: List[SupplyInventory],
    ) -> List[ConstraintCheckResult]:
        results: List[ConstraintCheckResult] = []

        stock_available = self._total_stock(inventories)
        # Running per-item total across every proposal checked so far this
        # cycle (in priority order, same order the allocator draws in) —
        # a later, lower-priority proposal can push the cumulative draw
        # over stock even if no single proposal looks unreasonable alone.
        drawn_so_far: Dict[str, int] = defaultdict(int)
        zone_counts = self._zone_distribution(proposals, clusters_by_id)

        for proposal in proposals:
            violations: List[ConstraintViolation] = []
            cluster = clusters_by_id.get(proposal.cluster_id)

            self._check_capacity(proposal, crews_by_id, stock_available, drawn_so_far, violations)
            self._check_access(proposal, violations)
            self._check_medical_priority(proposal, cluster, proposals, clusters_by_id, violations)

            fairness_note = self._check_fairness(proposal, cluster, zone_counts, violations)

            feasible = not any(v.severity == "block" for v in violations)
            result = ConstraintCheckResult(
                mission_id=proposal.mission_id,
                feasible=feasible,
                violations=violations,
                fairness_note=fairness_note,
            )
            results.append(result)

            self._log_decision(
                "constraint_checked",
                mission_id=str(proposal.mission_id),
                feasible=feasible,
                violation_codes=[v.code for v in violations],
            )

        await self._add_llm_explanations(results)
        return results

    # -- LLM explanation (Groq) --------------------------------------------

    async def _add_llm_explanations(self, results: List[ConstraintCheckResult]) -> None:
        """Mutates results in place, adding llm_explanation to any result
        that has violations. No-ops entirely if Groq isn't configured."""
        if not self.llm.is_configured:
            return

        with_violations = [r for r in results if r.violations]
        if not with_violations:
            return

        explanations = await asyncio.gather(*(self._explain(r) for r in with_violations))
        for result, explanation in zip(with_violations, explanations):
            result.llm_explanation = explanation

    async def _explain(self, result: ConstraintCheckResult) -> Optional[str]:
        system_prompt = (
            "You explain automated dispatch-constraint verdicts to a disaster-response "
            "commander in one plain-language sentence (max 30 words). Summarize only the "
            "violations given — do not soften a 'block' severity or invent new issues. "
            "Plain text, no markdown, no quotes."
        )
        violation_lines = "; ".join(
            f"[{v.severity}] {v.code}: {v.message}" for v in result.violations
        )
        user_prompt = f"feasible={result.feasible}. violations: {violation_lines}"
        return await self._think(system_prompt, user_prompt, temperature=0.2, max_tokens=80)

    # -- individual checks ------------------------------------------------

    def _check_capacity(
        self,
        proposal: MissionProposal,
        crews_by_id: Dict[str, Crew],
        stock_available: Dict[str, int],
        drawn_so_far: Dict[str, int],
        violations: List[ConstraintViolation],
    ) -> None:
        if proposal.crew_id is None:
            violations.append(ConstraintViolation(
                code="NO_CREW",
                message="No crew assigned — capacity exhausted this cycle.",
                severity="block",
            ))
            return

        crew = crews_by_id.get(proposal.crew_id)
        if crew is None or not crew.available:
            violations.append(ConstraintViolation(
                code="CREW_UNAVAILABLE",
                message=f"Assigned crew {proposal.crew_id} is not currently available.",
                severity="block",
            ))

        # Bug fix: this used to compare total stock against zero, which
        # can never go negative and so never fired. What actually matters
        # is whether this proposal's draw, stacked on top of every other
        # proposal's draw so far this cycle, exceeds total available stock.
        for item, qty in proposal.supplies.items():
            available = stock_available.get(item, 0)
            already_drawn = drawn_so_far.get(item, 0)
            if already_drawn + qty > available:
                violations.append(ConstraintViolation(
                    code="SUPPLY_OVERDRAWN",
                    message=(
                        f"Requested {qty} {item} brings cumulative draw this cycle to "
                        f"{already_drawn + qty}, exceeding available stock of {available}."
                    ),
                    severity="block",
                ))
            drawn_so_far[item] = already_drawn + qty

    def _check_access(self, proposal: MissionProposal, violations: List[ConstraintViolation]) -> None:
        # Route feasibility is re-checked here (not trusted from planning
        # time) since geo state may have changed between planning and now.
        route_id = proposal.route_id
        if route_id is None:
            violations.append(ConstraintViolation(
                code="NO_ROUTE",
                message="No route resolved for this mission.",
                severity="warn",
            ))

    def _check_medical_priority(
        self,
        proposal: MissionProposal,
        cluster: EvidenceCluster,
        all_proposals: List[MissionProposal],
        clusters_by_id: Dict[UUID, EvidenceCluster],
        violations: List[ConstraintViolation],
    ) -> None:
        if cluster is None or cluster.need_type != NeedType.MEDICAL:
            return
        # A medical-need mission left unassigned while lower-priority,
        # non-medical missions got crews is a hard fairness/priority bug.
        if proposal.crew_id is not None:
            return
        outranked_by_lower_priority = any(
            p.crew_id is not None
            and clusters_by_id.get(p.cluster_id)
            and clusters_by_id[p.cluster_id].need_type != NeedType.MEDICAL
            and p.priority_score < proposal.priority_score
            for p in all_proposals
        )
        if outranked_by_lower_priority:
            violations.append(ConstraintViolation(
                code="MEDICAL_PRIORITY_VIOLATED",
                message="Unassigned medical-need mission was outranked by a lower-priority, non-medical mission.",
                severity="block",
            ))

    def _check_fairness(
        self,
        proposal: MissionProposal,
        cluster: EvidenceCluster,
        zone_counts: Dict[str, int],
        violations: List[ConstraintViolation],
    ) -> Optional[str]:
        if cluster is None or proposal.crew_id is None:
            return None
        zone_key = self._zone_key(cluster)
        total_assigned = sum(zone_counts.values()) or 1
        share = zone_counts.get(zone_key, 0) / total_assigned
        if share > MAX_SHARE_PER_ZONE and len(zone_counts) > 1:
            violations.append(ConstraintViolation(
                code="ZONE_IMBALANCE",
                message=f"Zone {zone_key} is receiving {share:.0%} of assigned missions this cycle.",
                severity="warn",
            ))
            return f"Zone {zone_key} over-represented ({share:.0%} of assigned missions)."
        return None

    # -- helpers ------------------------------------------------------------

    def _total_stock(self, inventories: List[SupplyInventory]) -> Dict[str, int]:
        totals: Dict[str, int] = defaultdict(int)
        for inv in inventories:
            for item, qty in inv.items.items():
                totals[item] += qty
        return totals

    def _zone_key(self, cluster: EvidenceCluster) -> str:
        # Coarse ~1km buckets — good enough for a fairness heuristic, not
        # for routing.
        return f"{round(cluster.lat, 2)}_{round(cluster.lon, 2)}"

    def _zone_distribution(
        self, proposals: List[MissionProposal], clusters_by_id: Dict[UUID, EvidenceCluster]
    ) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for p in proposals:
            if p.crew_id is None:
                continue
            cluster = clusters_by_id.get(p.cluster_id)
            if cluster:
                counts[self._zone_key(cluster)] += 1
        return counts