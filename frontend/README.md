# ReliefMesh Commander Console (frontend)

A plain HTML/CSS/JS ops console — no framework, no build step — that talks
directly to the FastAPI backend in `../backend`. It's built to be usable
in the field: it queues field reports locally when the backend is
unreachable and syncs them through `POST /offline/reports` once it's back.

## Run it

1. Start the backend first (from the project root):
   ```bash
   cd backend
   uvicorn app.main:app --reload --port 8000
   ```
2. Serve this folder as static files (don't just double-click `index.html` —
   some browsers block `fetch`/WebSocket from `file://` origins):
   ```bash
   cd frontend
   npm run start            # http://localhost:5173, via `npx serve`
   # or, if you don't have Node:
   npm run start:python     # same thing via python3 -m http.server
   ```
3. Open the printed URL. Click the **⚙ API** button in the top bar if your
   backend isn't at `http://localhost:8000` (e.g. a LAN IP in the field) —
   it's saved in the browser via `localStorage`.

## What it does

- **Mission board** — reads `GET /missions` on load, then stays live via
  `WS /ws/missions`. Approve / Modify / Reject call
  `POST /missions/{id}/decision`.
- **New field report** — `POST /reports`. If the request fails (backend
  unreachable), the report is saved to an on-device offline queue instead
  of being lost.
- **Offline queue** — queued reports sync in one batch via
  `POST /offline/reports` when you hit "sync now".
- **Roads** — `GET /geo/state`, with block / degrade / reopen buttons
  hitting `POST /geo/roads/{id}/...`.
- **Run cycle / Replan** — `POST /cycle/run` and `POST /cycle/replan`.

## Notes

- If you serve the frontend from a different origin than the backend,
  make sure `CORS_ORIGINS` on the backend includes it (defaults to `*`).
- The offline queue lives in `localStorage` under
  `reliefmesh_offline_queue` — it's per-browser, not synced across devices
  until you hit "sync now".
