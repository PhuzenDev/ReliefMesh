"""
ReliefMesh API
==============
FastAPI entrypoint. Wires the in-memory agent pipeline
(app.agents.orchestrator.Orchestrator) to HTTP + WebSocket routes, and
persists pipeline output through app.db.repository as it's produced.

Route groups:
  - /reports          ingest new field reports (pools them; doesn't replan)
  - /cycle            run a full pipeline pass / trigger a replan
  - /missions         read current mission cards; commander decisions
  - /offline          two distinct offline paths — see their docstrings
  - /geo              live road/hazard state + read/write endpoints
  - /ws/missions      WebSocket broadcast of commander-view updates

Fixture data (crews, inventories, road graph, shelters) loads from
data/*.json at startup. Swap load_fixtures() for a real onboarding
flow once crews/supplies are managed in the DB instead of JSON files.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import Orchestrator
from app.db import repository
from app.db.audit import install_audit_handler
from app.db.database import create_all_dev_only, get_session
from app.models.schemas import (
    CommanderDecision,
    Crew,
    MissionProposal,
    RawReport,
    SupplyInventory,
)

logger = logging.getLogger("reliefmesh.api")

# backend/app/main.py -> parents[0]=app, [1]=backend, [2]=project root
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

orchestrator = Orchestrator()


def _load_json(path: Path):
    """Returns parsed JSON, or None if the fixture is missing/empty —
    same no-op-on-missing-data pattern as GeoAgent.load_from_files, so a
    partial data/ directory doesn't crash startup."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    return json.loads(path.read_text())


def load_fixtures() -> None:
    """Populates crews/inventories on the orchestrator and road/shelter
    state on its geo agent from data/*.json."""
    orchestrator.geo_agent.load_from_files(
        DATA_DIR / "road_graph.json", DATA_DIR / "shelters.json"
    )

    crews_raw = _load_json(DATA_DIR / "crews.json") or []
    orchestrator.register_crews([Crew(**c) for c in crews_raw])

    inventories_raw = _load_json(DATA_DIR / "inventories.json") or []
    orchestrator.register_inventories([SupplyInventory(**i) for i in inventories_raw])

    logger.info(
        "fixtures_loaded crews=%d inventories=%d roads=%d shelters=%d",
        len(orchestrator._crews),
        len(orchestrator._inventories),
        len(orchestrator.geo_agent.state.road_status),
        len(orchestrator.geo_agent.state.shelters),
    )


class ConnectionManager:
    """Tracks live WebSocket clients and pushes commander-view updates to
    all of them whenever a pipeline event changes mission state."""

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, cards: List[dict]) -> None:
        payload = jsonable_encoder({"type": "missions_update", "cards": cards})
        stale: List[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    install_audit_handler()
    if os.getenv("DEV_AUTO_CREATE_TABLES", "false").lower() == "true":
        # Dev/local convenience only — see database.create_all_dev_only's
        # docstring. Never enable this once Alembic owns the demo DB.
        await create_all_dev_only()
    load_fixtures()
    yield


app = FastAPI(title="ReliefMesh API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@app.post("/reports")
async def ingest_reports(
    reports: List[RawReport], session: AsyncSession = Depends(get_session)
) -> dict:
    """Adds reports to the pool. Does NOT replan by itself — call
    POST /cycle/run (or batch several of these first) to act on them."""
    if not reports:
        raise HTTPException(status_code=400, detail="reports list is empty")
    await repository.save_reports(session, reports)
    await orchestrator.ingest_reports(reports)
    return {"ingested": len(reports), "pool_size": len(orchestrator._reports)}


# ---------------------------------------------------------------------------
# Pipeline cycles
# ---------------------------------------------------------------------------

@app.post("/cycle/run")
async def run_cycle(session: AsyncSession = Depends(get_session)) -> List[dict]:
    """Full pass: re-cluster evidence, replan, re-check constraints."""
    cards = await orchestrator.run_cycle()
    await repository.save_evidence_clusters(session, orchestrator._clusters)
    await repository.save_mission_proposals(session, list(orchestrator._proposals.values()))
    await repository.save_constraint_results(session, list(orchestrator._checks.values()))
    await manager.broadcast(cards)
    return cards


@app.post("/cycle/replan")
async def replan(
    reason: str = "manual_replan", session: AsyncSession = Depends(get_session)
) -> List[dict]:
    """Re-run planning + constraint checks against current geo/crew/supply
    state without re-clustering evidence (e.g. a road closed or a crew
    dropped out). Use /cycle/run instead when new evidence is the trigger."""
    cards = await orchestrator.trigger_replan(reason)
    await repository.save_mission_proposals(session, list(orchestrator._proposals.values()))
    await repository.save_constraint_results(session, list(orchestrator._checks.values()))
    await manager.broadcast(cards)
    return cards


# ---------------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------------

@app.get("/missions")
async def current_missions() -> List[dict]:
    """Current commander-facing state without forcing a replan."""
    return orchestrator.commander_view()


@app.post("/missions/{mission_id}/decision")
async def commander_decision(
    mission_id: UUID,
    decision: CommanderDecision,
    session: AsyncSession = Depends(get_session),
) -> MissionProposal:
    if decision.mission_id != mission_id:
        raise HTTPException(status_code=400, detail="mission_id in path and body must match")

    proposal = await orchestrator.handle_commander_decision(decision)
    if proposal is None:
        raise HTTPException(status_code=404, detail="unknown mission_id")

    await repository.save_commander_decision(session, decision)
    await manager.broadcast(orchestrator.commander_view())
    return proposal


# ---------------------------------------------------------------------------
# Offline reconciliation — two distinct paths, see db/models.py's Event
# docstring for why they're separate.
# ---------------------------------------------------------------------------

@app.post("/offline/reports")
async def reconcile_offline_reports(
    reports: List[RawReport], session: AsyncSession = Depends(get_session)
) -> List[dict]:
    """A field team's queued RawReports (each already carrying its
    original received_at) — applied and replanned once for the batch."""
    if not reports:
        raise HTTPException(status_code=400, detail="reports list is empty")
    await repository.save_reports(session, reports)
    cards = await orchestrator.reconcile_offline_batch(reports)
    await repository.save_evidence_clusters(session, orchestrator._clusters)
    await repository.save_mission_proposals(session, list(orchestrator._proposals.values()))
    await repository.save_constraint_results(session, list(orchestrator._checks.values()))
    await manager.broadcast(cards)
    return cards


@app.post("/offline/events")
async def reconcile_offline_events(
    events: List[dict], session: AsyncSession = Depends(get_session)
) -> dict:
    """Idempotent replay of arbitrary field-client events keyed by
    client_event_id. Each dict needs: client_event_id, event_type,
    entity_type, entity_id, payload, actor, occurred_at."""
    if not events:
        raise HTTPException(status_code=400, detail="events list is empty")
    return await repository.record_offline_sync_batch(session, events)


# ---------------------------------------------------------------------------
# Geo
# ---------------------------------------------------------------------------

@app.get("/geo/state")
async def geo_state() -> dict:
    return orchestrator.geo_agent.state.model_dump()


@app.post("/geo/roads/{road_id}/block")
async def block_road(road_id: str, reason: str = "reported blocked") -> dict:
    orchestrator.geo_agent.block_road(road_id, reason)
    return {"road_id": road_id, "status": "blocked"}


@app.post("/geo/roads/{road_id}/degrade")
async def degrade_road(road_id: str, reason: str = "reported degraded") -> dict:
    orchestrator.geo_agent.degrade_road(road_id, reason)
    return {"road_id": road_id, "status": "degraded"}


@app.post("/geo/roads/{road_id}/reopen")
async def reopen_road(road_id: str) -> dict:
    orchestrator.geo_agent.reopen_road(road_id)
    return {"road_id": road_id, "status": "open"}


# ---------------------------------------------------------------------------
# Live updates
# ---------------------------------------------------------------------------

@app.websocket("/ws/missions")
async def missions_ws(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        await ws.send_json(
            jsonable_encoder({"type": "missions_snapshot", "cards": orchestrator.commander_view()})
        )
        while True:
            # Clients don't need to send anything — this just keeps the
            # socket open and detects disconnects via the exception below.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
