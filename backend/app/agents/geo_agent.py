"""
Geo Agent
=========
Owns the live spatial picture: which roads are open/degraded/blocked,
where hazard zones are, and shelter capacity/occupancy. Other agents
never touch GeoState directly — they call this agent so every mutation
is logged and every read gets a consistent risk score.

Expects `data/road_graph.json` and `data/shelters.json` shaped roughly like:
  road_graph.json: {"nodes": {...}, "edges": [{"id","from","to","km"}]}
  shelters.json:   [{"shelter_id","lat","lon","capacity"}]

If those files aren't wired up yet, `load_from_files` just no-ops and
you can build state incrementally with `block_road` / `add_hazard_zone`
for local testing.
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Optional

from app.agents.base_agent import BaseAgent
from app.models.schemas import GeoState, HazardZone, RoadStatus, Shelter


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class GeoAgent(BaseAgent):
    name = "geo_agent"

    def __init__(self) -> None:
        super().__init__()
        self.state = GeoState()
        self._road_edges: List[dict] = []  # raw edges from road_graph.json, used for route checks

    async def run(self) -> GeoState:
        """Agents that just need a read of current state call run()."""
        return self.state

    # -- loading --------------------------------------------------------

    def load_from_files(self, road_graph_path: Path, shelters_path: Path) -> None:
        if road_graph_path.exists():
            graph = json.loads(road_graph_path.read_text())
            self._road_edges = graph.get("edges", [])
            for edge in self._road_edges:
                self.state.road_status[edge["id"]] = RoadStatus.OPEN

        if shelters_path.exists():
            shelters = json.loads(shelters_path.read_text())
            for s in shelters:
                self.state.shelters[s["shelter_id"]] = Shelter(
                    shelter_id=s["shelter_id"],
                    lat=s["lat"],
                    lon=s["lon"],
                    capacity=s["capacity"],
                    occupied=s.get("occupied", 0),
                )
        self._log_decision("geo_state_loaded", roads=len(self.state.road_status), shelters=len(self.state.shelters))

    # -- mutations (each one is a candidate replan trigger) --------------

    def block_road(self, road_id: str, reason: str = "reported blocked") -> None:
        self.state.road_status[road_id] = RoadStatus.BLOCKED
        self._log_decision("road_blocked", road_id=road_id, reason=reason)

    def degrade_road(self, road_id: str, reason: str = "reported degraded") -> None:
        self.state.road_status[road_id] = RoadStatus.DEGRADED
        self._log_decision("road_degraded", road_id=road_id, reason=reason)

    def reopen_road(self, road_id: str) -> None:
        self.state.road_status[road_id] = RoadStatus.OPEN
        self._log_decision("road_reopened", road_id=road_id)

    def add_hazard_zone(self, lat: float, lon: float, radius_km: float, risk: float) -> None:
        self.state.hazard_zones.append(HazardZone(lat=lat, lon=lon, radius_km=radius_km, risk=risk))
        self._log_decision("hazard_zone_added", lat=lat, lon=lon, radius_km=radius_km, risk=risk)

    def update_shelter_occupancy(self, shelter_id: str, occupied: int) -> None:
        if shelter_id in self.state.shelters:
            self.state.shelters[shelter_id].occupied = occupied

    # -- queries -----------------------------------------------------------

    def risk_score(self, lat: float, lon: float) -> float:
        """0 (safe) - 1 (severe) based on proximity to hazard zones."""
        max_risk = 0.0
        for zone in self.state.hazard_zones:
            dist = _haversine_km(lat, lon, zone.lat, zone.lon)
            if dist <= zone.radius_km:
                # linear falloff from zone center to edge
                falloff = 1 - (dist / zone.radius_km) if zone.radius_km > 0 else 1
                max_risk = max(max_risk, zone.risk * falloff)
        return round(max_risk, 3)

    def route_feasible(self, route_road_ids: List[str]) -> bool:
        """A route is only feasible if every edge on it is open or degraded."""
        return all(self.state.road_status.get(rid, RoadStatus.OPEN) != RoadStatus.BLOCKED for rid in route_road_ids)

    def nearest_shelter(self, lat: float, lon: float, min_free_capacity: int = 1) -> Optional[Shelter]:
        candidates = [
            s for s in self.state.shelters.values()
            if (s.capacity - s.occupied) >= min_free_capacity
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda s: _haversine_km(lat, lon, s.lat, s.lon))

    def find_route(self, from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> Optional[dict]:
        """
        Placeholder for a real shortest-path search over the road graph
        (swap for networkx/Dijkstra once road_graph.json has real
        connectivity). Returns a naive straight-line stand-in route so
        planning/constraint agents have something to check against.
        """
        km = _haversine_km(from_lat, from_lon, to_lat, to_lon)
        return {
            "route_id": f"direct-{round(from_lat,3)}-{round(to_lat,3)}",
            "road_ids": [],  # no real edges resolved yet — treat as always feasible
            "distance_km": round(km, 2),
            "estimated_minutes": round((km / 30) * 60, 1),  # 30 km/h assumed relief-vehicle speed
        }