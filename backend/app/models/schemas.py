"""
Shared data models for the ReliefMesh agent pipeline.

Every agent imports from here so the orchestrator can pass typed objects
between stages instead of every agent inventing its own shape. Kept
dependency-light (pydantic only) so this module works standalone even
before the DB/API layers exist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Set
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    CALL = "call"
    SMS = "sms"
    FIELD_TEAM = "field_team"
    SENSOR = "sensor"


class NeedType(str, Enum):
    MEDICAL = "medical"
    RESCUE = "rescue"
    FOOD_WATER = "food_water"
    SHELTER = "shelter"
    EVACUATION = "evacuation"
    UNKNOWN = "unknown"


class RoadStatus(str, Enum):
    OPEN = "open"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class MissionStatus(str, Enum):
    PROPOSED = "proposed"
    CHECKED = "checked"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Stage 1: raw input -> evidence agent
# ---------------------------------------------------------------------------

class RawReport(BaseModel):
    """A single unprocessed report as it arrives from any channel."""
    report_id: UUID = Field(default_factory=uuid4)
    source: SourceType
    source_reliability_hint: Optional[float] = None  # calibration / field-team trust, 0-1
    received_at: datetime = Field(default_factory=_utcnow)
    lat: float
    lon: float
    text: Optional[str] = None
    need_type: NeedType = NeedType.UNKNOWN
    people_affected: Optional[int] = None
    raw_payload: Dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 2: evidence agent output
# ---------------------------------------------------------------------------

class EvidenceCluster(BaseModel):
    """Deduplicated, reliability-scored view of one real-world incident."""
    cluster_id: UUID = Field(default_factory=uuid4)
    member_report_ids: List[UUID]
    lat: float
    lon: float
    need_type: NeedType
    people_affected_estimate: Optional[int] = None
    reliability_score: float          # 0-1: source trust + corroboration
    confidence: float                 # 0-1: how sure this is ONE real incident
    contradictory: bool = False
    contradiction_notes: Optional[str] = None
    first_seen: datetime
    last_seen: datetime


# ---------------------------------------------------------------------------
# Stage 3: geo agent state
# ---------------------------------------------------------------------------

class HazardZone(BaseModel):
    lat: float
    lon: float
    radius_km: float
    risk: float  # 0-1


class Shelter(BaseModel):
    shelter_id: str
    lat: float
    lon: float
    capacity: int
    occupied: int = 0


class GeoState(BaseModel):
    """Live snapshot of the road / shelter / hazard picture."""
    road_status: Dict[str, RoadStatus] = Field(default_factory=dict)   # road_id -> status
    hazard_zones: List[HazardZone] = Field(default_factory=list)
    shelters: Dict[str, Shelter] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 4: planning agent output
# ---------------------------------------------------------------------------

class Crew(BaseModel):
    crew_id: str
    lat: float
    lon: float
    skills: Set[str] = Field(default_factory=set)
    available: bool = True


class SupplyInventory(BaseModel):
    location_id: str
    items: Dict[str, int] = Field(default_factory=dict)  # item_name -> qty


class MissionProposal(BaseModel):
    mission_id: UUID = Field(default_factory=uuid4)
    cluster_id: UUID
    crew_id: Optional[str] = None
    route_id: Optional[str] = None
    supplies: Dict[str, int] = Field(default_factory=dict)
    priority_score: float
    eta_minutes: Optional[float] = None
    assumptions: List[str] = Field(default_factory=list)
    status: MissionStatus = MissionStatus.PROPOSED


# ---------------------------------------------------------------------------
# Stage 5: constraint agent output
# ---------------------------------------------------------------------------

class ConstraintViolation(BaseModel):
    code: str
    message: str
    severity: str  # "block" | "warn"


class ConstraintCheckResult(BaseModel):
    mission_id: UUID
    feasible: bool
    violations: List[ConstraintViolation] = Field(default_factory=list)
    fairness_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 6: commander action (human-in-the-loop)
# ---------------------------------------------------------------------------

class CommanderDecision(BaseModel):
    mission_id: UUID
    decision: MissionStatus  # APPROVED | MODIFIED | REJECTED
    modifications: Optional[Dict] = None
    decided_by: str
    decided_at: datetime = Field(default_factory=_utcnow)