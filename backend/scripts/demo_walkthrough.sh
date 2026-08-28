#!/usr/bin/env bash
# End-to-end walkthrough against a RUNNING API (`uvicorn app.main:app`)
# backed by a RUNNING Postgres (`docker compose up -d`, migrated with
# `alembic upgrade head`). Exercises the full pipeline through the DB:
# reports -> evidence clusters -> mission proposals -> constraint checks,
# all persisted via app/db/repository.py as they're produced.
#
# Usage: ./scripts/demo_walkthrough.sh [base_url]
# Defaults to http://localhost:8000

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../data" && pwd)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 1; }; }
need curl
need jq

echo "== health check =="
curl -sf "$BASE_URL/health" | jq .

echo
echo "== wave 1: posting data/synthetic_reports.json =="
curl -sf -X POST "$BASE_URL/reports" \
  -H "Content-Type: application/json" \
  -d @"$DATA_DIR/synthetic_reports.json" | jq .

echo
echo "== running a full pipeline cycle (persists clusters/proposals/checks to Postgres) =="
CYCLE1=$(curl -sf -X POST "$BASE_URL/cycle/run")
echo "$CYCLE1" | jq '[.[] | {mission_id: .proposal.mission_id, need: .proposal.assumptions, feasible: .check.feasible, priority: .proposal.priority_score}]'

echo
echo "== wave 2: posting data/synthetic_reports_batch2.json (new incidents + corroboration) =="
curl -sf -X POST "$BASE_URL/reports" \
  -H "Content-Type: application/json" \
  -d @"$DATA_DIR/synthetic_reports_batch2.json" | jq .

echo
echo "== blocking road R6 (logged to Postgres via the audit trail; see NOTE below) =="
curl -sf -X POST "$BASE_URL/geo/roads/R6/block?reason=demo_debris" | jq .
# NOTE: GeoAgent.find_route() is currently a straight-line stand-in that
# doesn't resolve real road_graph.json edges yet (see its docstring), so
# this won't change any mission's feasibility in this build — but the
# road_blocked event IS persisted to the `events` table by the audit
# handler, which you can see in Adminer. Wiring find_route() to actual
# edges is a good next step once you want blocked roads to affect
# constraint checks.

echo
echo "== re-running the cycle (re-clusters wave 1+2, replans, re-checks; all persisted) =="
CYCLE2=$(curl -sf -X POST "$BASE_URL/cycle/run")
echo "$CYCLE2" | jq '[.[] | {mission_id: .proposal.mission_id, feasible: .check.feasible, violations: (.check.violations // []), llm_explanation: .check.llm_explanation}]'

echo
echo "== current commander view (GET, no replan) =="
curl -sf "$BASE_URL/missions" | jq 'length'

echo
echo "Done. Open http://localhost:8081 (Adminer) to inspect the Postgres tables directly:"
echo "  System=PostgreSQL, Server=postgres, Username=reliefmesh, Password=reliefmesh, Database=reliefmesh"
