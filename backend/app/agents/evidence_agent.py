"""
Evidence Agent
==============
Turns a stream of raw, noisy RawReports into a smaller set of
EvidenceClusters — one per real-world incident — with a reliability
score and provenance trail. Contradictory reports (different need_type
or wildly different headcounts for the same physical event) are kept,
not discarded, and flagged so the planner never treats an uncertain
report as ground truth.

Clustering approach (deliberately simple + explainable for the demo,
swap the core loop for DBSCAN/HDBSCAN later without touching the
interface):
  1. Two reports can belong to the same cluster only if they are within
     DISTANCE_THRESHOLD_KM of each other AND within TIME_WINDOW_MIN of
     each other.
  2. Within that spatial/temporal window, reports are merged via a
     union-find so overlapping pairs chain into one cluster.
  3. Reliability = weighted blend of source trust + corroboration count.
  4. Confidence = how tight the cluster is (fewer distinct need_types /
     lower variance in people_affected = higher confidence).

Before clustering, an optional Groq-backed step (`_enrich_with_llm`)
reads free-text reports (SMS/call transcripts land in `RawReport.text`
with need_type=UNKNOWN) and infers a structured need_type / headcount
so they aren't dropped into the lowest-priority bucket just because
nobody typed a category. This only ever *fills gaps* — a report that
already has a structured need_type from its source is never overridden
by the LLM, and if Groq isn't configured or a call fails the report is
left as UNKNOWN and flows through the existing deterministic path
unchanged.
"""

import asyncio
import math
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from app.agents.base_agent import BaseAgent
from app.models.schemas import EvidenceCluster, NeedType, RawReport, SourceType

_VALID_NEED_TYPES = {n.value for n in NeedType}

DISTANCE_THRESHOLD_KM = 0.6
TIME_WINDOW_MIN = 45

# Base trust per channel — field teams and calibrated sensors are more
# trustworthy than an unverified SMS, but corroboration can still lift
# an SMS cluster's score.
SOURCE_TRUST: Dict[SourceType, float] = {
    SourceType.FIELD_TEAM: 0.9,
    SourceType.SENSOR: 0.85,
    SourceType.CALL: 0.65,
    SourceType.SMS: 0.55,
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


class EvidenceAgent(BaseAgent):
    name = "evidence_agent"

    async def run(self, reports: List[RawReport]) -> List[EvidenceCluster]:
        if not reports:
            return []

        reports = await self._enrich_with_llm(reports)

        uf = _UnionFind(len(reports))
        for i in range(len(reports)):
            for j in range(i + 1, len(reports)):
                if self._same_incident_candidate(reports[i], reports[j]):
                    uf.union(i, j)

        groups: Dict[int, List[int]] = {}
        for idx in range(len(reports)):
            root = uf.find(idx)
            groups.setdefault(root, []).append(idx)

        clusters = [
            self._build_cluster([reports[i] for i in member_idxs])
            for member_idxs in groups.values()
        ]

        for c in clusters:
            self._log_decision(
                "evidence_cluster_formed",
                cluster_id=str(c.cluster_id),
                members=len(c.member_report_ids),
                reliability=round(c.reliability_score, 2),
                confidence=round(c.confidence, 2),
                contradictory=c.contradictory,
            )
        return clusters

    # -- LLM enrichment (Groq) ------------------------------------------

    async def _enrich_with_llm(self, reports: List[RawReport]) -> List[RawReport]:
        """Fill in need_type/people_affected for UNKNOWN reports that have
        free text, by asking Groq to read the text. Runs all candidates
        concurrently since each call is independent and Groq is fast."""
        if not self.llm.is_configured:
            return reports

        targets = [r for r in reports if r.need_type == NeedType.UNKNOWN and r.text]
        if not targets:
            return reports

        inferred_results = await asyncio.gather(*(self._classify_report_text(r) for r in targets))

        for report, inferred in zip(targets, inferred_results):
            if not inferred:
                continue

            need = inferred.get("need_type")
            if isinstance(need, str) and need in _VALID_NEED_TYPES:
                report.need_type = NeedType(need)

            people = inferred.get("people_affected_estimate")
            if report.people_affected is None and isinstance(people, int) and people >= 0:
                report.people_affected = people

            self._log_decision(
                "llm_report_enriched",
                report_id=str(report.report_id),
                inferred_need_type=report.need_type.value,
                inferred_people_affected=report.people_affected,
            )

        return reports

    async def _classify_report_text(self, report: RawReport) -> Optional[Dict]:
        system_prompt = (
            "You triage raw emergency reports for a disaster-response system. "
            "Given a short free-text report, extract the most likely need type "
            "and an approximate headcount. Be conservative: if the text doesn't "
            "clearly support a category or number, say so. "
            f"Respond ONLY with a JSON object with exactly these keys: "
            f'"need_type" (one of {sorted(_VALID_NEED_TYPES)}), '
            '"people_affected_estimate" (integer or null), '
            '"confidence" (0-1 float). No other text.'
        )
        user_prompt = f"Report text: {report.text}"
        return await self._think_json(system_prompt, user_prompt, temperature=0.0, max_tokens=200)

    # -- internals ----------------------------------------------------

    def _same_incident_candidate(self, a: RawReport, b: RawReport) -> bool:
        dist_ok = _haversine_km(a.lat, a.lon, b.lat, b.lon) <= DISTANCE_THRESHOLD_KM
        time_diff_min = abs((a.received_at - b.received_at).total_seconds()) / 60
        time_ok = time_diff_min <= TIME_WINDOW_MIN
        return dist_ok and time_ok

    def _build_cluster(self, members: List[RawReport]) -> EvidenceCluster:
        lat = sum(m.lat for m in members) / len(members)
        lon = sum(m.lon for m in members) / len(members)

        need_types = {m.need_type for m in members if m.need_type != NeedType.UNKNOWN}
        contradictory = len(need_types) > 1
        dominant_need = self._majority_need_type(members)

        people_estimates = [m.people_affected for m in members if m.people_affected is not None]
        people_estimate = max(people_estimates) if people_estimates else None
        if people_estimates and (max(people_estimates) - min(people_estimates)) > max(people_estimates) * 0.5:
            contradictory = True

        reliability = self._score_reliability(members)
        confidence = self._score_confidence(members, contradictory)

        notes = None
        if contradictory:
            notes = (
                f"{len(need_types)} distinct need_type(s) and/or divergent headcounts "
                f"across {len(members)} reports — treat as unresolved until re-confirmed."
            )

        return EvidenceCluster(
            member_report_ids=[m.report_id for m in members],
            lat=lat,
            lon=lon,
            need_type=dominant_need,
            people_affected_estimate=people_estimate,
            reliability_score=reliability,
            confidence=confidence,
            contradictory=contradictory,
            contradiction_notes=notes,
            first_seen=min(m.received_at for m in members),
            last_seen=max(m.received_at for m in members),
        )

    def _majority_need_type(self, members: List[RawReport]) -> NeedType:
        counts: Dict[NeedType, int] = {}
        for m in members:
            counts[m.need_type] = counts.get(m.need_type, 0) + 1
        counts.pop(NeedType.UNKNOWN, None)
        if not counts:
            return NeedType.UNKNOWN
        return max(counts, key=counts.get)

    def _score_reliability(self, members: List[RawReport]) -> float:
        trust_scores = [
            m.source_reliability_hint if m.source_reliability_hint is not None else SOURCE_TRUST[m.source]
            for m in members
        ]
        base = sum(trust_scores) / len(trust_scores)
        # Corroboration bonus: independent reports agreeing raises confidence
        # in the underlying fact, capped so it never claims certainty.
        corroboration_bonus = min(0.25, 0.06 * (len(members) - 1))
        return round(min(1.0, base + corroboration_bonus), 3)

    def _score_confidence(self, members: List[RawReport], contradictory: bool) -> float:
        confidence = 0.5 + 0.08 * min(len(members), 5)
        if contradictory:
            confidence *= 0.6
        return round(min(1.0, confidence), 3)