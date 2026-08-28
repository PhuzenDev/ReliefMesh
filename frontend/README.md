# ReliefMesh frontend

Commander console for the ReliefMesh agent pipeline. Talks to the real
FastAPI backend in `backend/app/main.py` — no mock data.

## Run it

```bash
# from backend/, with the API running on :8000
uvicorn app.main:app --reload

# from frontend/
npm install
npm run dev
```

The dev server proxies `/health`, `/reports`, `/cycle`, `/missions`,
`/offline`, `/geo` and the `/ws/missions` socket to `http://localhost:8000`
(see `vite.config.js`). To point at a different backend, copy
`.env.example` to `.env` and set `VITE_API_BASE`.

## Structure

- `src/api/client.js` — one function per backend route
- `src/api/useMissionsSocket.js` — subscribes to `/ws/missions`, falls
  back to polling `GET /missions` if the socket can't connect
- `src/offline/offlineQueue.js` — queues submitted reports in
  `localStorage` while offline, flushes to `POST /offline/reports` on
  reconnect
- `src/components/MapView` — plots `GET /geo/state` (hazard zones,
  shelters, road status) over the `data/road_graph.json` fixture
  geometry, since the API doesn't currently return road coordinates
- `src/components/IncidentFeed` — report intake form (`POST /reports`).
  There's no `GET /reports`, so this is submission-only; run a cycle to
  see what a submitted report produces
- `src/components/MissionQueue` — mission cards from `GET /missions`,
  styled as triage tags by `priority_score`
- `src/components/CommanderPanel` — cycle controls (`POST /cycle/run`,
  `/cycle/replan`) and the approve/modify/reject decision flow
  (`POST /missions/{id}/decision`)

## Known gap

`GET /missions` returns `{ proposal, check }` only — no joined
`EvidenceCluster`, so mission cards can't show `need_type` or
`people_affected_estimate` today. If the backend adds a `/clusters` (or
joins cluster data onto mission cards), wire it into `TriageCard.jsx`.
