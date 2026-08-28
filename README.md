# ReliefMesh

ReliefMesh — Emergency Response & Evidence Fusion System

## Postgres backend

The persistence layer (`backend/app/db/`) was already fully built out —
SQLAlchemy async models, an Alembic migration, and a repository layer
wired into every route in `main.py`. What was missing was something to
actually run it against. `docker-compose.yml` fixes that.

Setup:
1. `docker compose up -d` — starts Postgres on `localhost:5432` (user/pass/db
   all `reliefmesh`, matching the default `DATABASE_URL` baked into the
   code) plus [Adminer](http://localhost:8081) for browsing tables without
   installing `psql`.
2. `cd backend && alembic upgrade head` — creates the schema.
3. `uvicorn app.main:app --reload` — run the API. Every `/reports`,
   `/cycle/run`, `/cycle/replan`, `/missions/{id}/decision`, and
   `/offline/*` call now persists to Postgres as it happens.

To point at a different Postgres instance instead, set `DATABASE_URL` in
`backend/.env` (see `backend/.env.example`) — it's read by
`app/db/database.py`, `app/db/audit.py`, and `migrations/env.py`.

Tables: `reports`, `evidence_clusters`, `mission_proposals`,
`constraint_check_results`, `commander_decisions`, and the append-only
`events` audit/offline-sync log (see `app/db/models.py` for the full
column-by-column rationale).

Note: crews, supply inventories, the road graph, and shelters are still
loaded from `data/*.json` into in-memory state at startup (not
Postgres-backed yet) — see `main.py::load_fixtures`.

## Sample datasets

All in `data/`:

| file | what it's for |
|---|---|
| `crews.json` | 3 crews with skills/location, loaded at startup |
| `inventories.json` | 2 supply depots, loaded at startup |
| `road_graph.json` | nodes/edges for the road network |
| `shelters.json` | 3 shelters with capacity/occupancy |
| `synthetic_reports.json` | 10 raw incident reports ("wave 1") — medical, rescue, evacuation, food/water, and one deliberately uncategorized report to exercise the Groq free-text enrichment in `EvidenceAgent` |
| `synthetic_reports_batch2.json` | a "wave 2" of reports (new incidents + one corroborating an existing cluster + two more uncategorized ones) for exercising replanning |
| `offline_events_sample.json` | sample payload for `POST /offline/events` — replace the placeholder `entity_id`s with a real `mission_id` from `GET /missions` first |

Two ways to use them:

- **Through the API (recommended — exercises the full pipeline + Postgres writes):**
  `backend/scripts/demo_walkthrough.sh` runs the whole thing end to end —
  posts wave 1, runs a cycle, posts wave 2, blocks a road, re-runs the
  cycle, and prints the results. Needs `curl` and `jq`, and the API +
  Postgres already running:
  ```
  cd backend
  ./scripts/demo_walkthrough.sh
  ```
- **Straight into Postgres (bypasses the API/agents, for checking the DB layer itself):**
  ```
  cd backend
  python scripts/load_sample_reports.py                              # wave 1
  python scripts/load_sample_reports.py ../data/synthetic_reports_batch2.json  # wave 2
  ```

## LLM reasoning (Groq)

Agents can use Groq to add narrative/soft-signal reasoning on top of
their deterministic logic — see `backend/app/llm/groq_client.py` and
`backend/app/agents/base_agent.py::_think` / `_think_json`. This is
strictly additive: every agent still works, and every test still
passes, with `GROQ_API_KEY` unset — the LLM calls simply no-op.

Where it's used:
- **Evidence agent** — reads free-text reports that arrived without a
  structured `need_type` and infers one, instead of leaving them at
  the lowest-priority "unknown" bucket.
- **Planning agent** — appends a one-sentence natural-language
  rationale to each assigned mission's `assumptions`.
- **Constraint agent** — appends a plain-language `llm_explanation` to
  any mission that failed one or more constraint checks.

Setup:
1. `cp backend/.env.example backend/.env`
2. Get a free key at https://console.groq.com/keys and set
   `GROQ_API_KEY=...` in `backend/.env`.
3. Run the API/tests from the `backend/` directory (or anywhere on the
   same filesystem) as usual — `python-dotenv` loads that file
   automatically.