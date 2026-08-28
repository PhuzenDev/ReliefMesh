"""
Allocation interface used by PlanningAgent.

`greedy_allocate` is a working baseline: sort clusters by priority,
walk down the list, assign the nearest available crew + whatever
supplies are on hand. It's deliberately simple so the demo has a
correct, explainable baseline on day one.

`cp_sat_allocate` is the intended real allocator — a constrained
optimization pass over (crew x cluster x supply) assignments using
OR-Tools CP-SAT, maximizing coverage of high-priority/medical clusters
subject to crew capacity, supply stock, and route feasibility. Left as
a documented skeleton so you can build it out without touching
PlanningAgent's call site — swap ALLOCATOR below once it's ready.
"""

import math
from typing import Dict, List, Optional
from uuid import UUID

from app.models.schemas import Crew, EvidenceCluster, SupplyInventory


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def greedy_allocate(
    prioritized_clusters: List[EvidenceCluster],
    crews: List[Crew],
    inventories: List[SupplyInventory],
    supply_needs_by_need_type: Dict[str, Dict[str, int]],
) -> Dict[UUID, dict]:
    """
    Returns cluster_id -> {"crew_id", "supplies", "distance_km"} for
    every cluster that could be assigned a crew. Clusters that run out
    of available crews are simply absent from the result — the
    orchestrator/constraint agent decide what happens to the backlog.
    """
    assignments: Dict[UUID, dict] = {}
    available_crews = {c.crew_id: c for c in crews if c.available}
    stock = {inv.location_id: dict(inv.items) for inv in inventories}

    for cluster in prioritized_clusters:
        if not available_crews:
            break

        nearest_id = min(
            available_crews,
            key=lambda cid: _distance_km(
                cluster.lat, cluster.lon, available_crews[cid].lat, available_crews[cid].lon
            ),
        )
        crew = available_crews.pop(nearest_id)

        needed = supply_needs_by_need_type.get(cluster.need_type.value, {})
        drawn: Dict[str, int] = {}
        for location_id, items in stock.items():
            for item, qty in needed.items():
                have = items.get(item, 0)
                take = min(have, qty - drawn.get(item, 0))
                if take > 0:
                    items[item] -= take
                    drawn[item] = drawn.get(item, 0) + take

        assignments[cluster.cluster_id] = {
            "crew_id": crew.crew_id,
            "supplies": drawn,
            "distance_km": round(_distance_km(cluster.lat, cluster.lon, crew.lat, crew.lon), 2),
        }

    return assignments


def cp_sat_allocate(*args, **kwargs) -> Dict[UUID, dict]:
    """
    TODO: OR-Tools CP-SAT model.
    Decision vars: x[crew][cluster] in {0,1}.
    Objective: maximize sum(priority_score[cluster] * x[crew][cluster]).
    Constraints:
      - each crew assigned to at most one cluster per planning cycle
      - each cluster assigned at most one crew
      - sum of supplies drawn per item <= available stock
      - x[crew][cluster] == 0 if route_feasible(...) is False
      - medical-need clusters get a minimum-service constraint before
        lower-priority need types are served (fairness/priority rule)
    Left unimplemented on purpose — greedy_allocate is the current
    ALLOCATOR so the rest of the pipeline runs end-to-end today.
    """
    raise NotImplementedError("Swap ALLOCATOR to this once the CP-SAT model is built.")


# Single switch point: change this once cp_sat_allocate is ready.
ALLOCATOR = greedy_allocate