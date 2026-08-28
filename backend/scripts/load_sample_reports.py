"""
Loads data/*.json report fixtures straight into Postgres through
app.db.repository — no running API needed. Useful for sanity-checking
the DB layer itself (tables exist, JSONB columns round-trip, etc.)
independent of the agent pipeline.

This only writes to the `reports` table. It does NOT run the agent
pipeline (evidence clustering / planning / constraint checks), so no
evidence_clusters/mission_proposals/constraint_check_results rows are
created here — those only exist once something calls
Orchestrator.run_cycle(), which normally happens via POST /cycle/run.
See scripts/demo_walkthrough.sh for the full pipeline-through-Postgres
path via the running API instead.

Usage (from backend/, with Postgres up and `alembic upgrade head` run):
    python scripts/load_sample_reports.py
    python scripts/load_sample_reports.py ../data/synthetic_reports_batch2.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # -> backend/

from app.db.database import AsyncSessionLocal
from app.db.repository import save_reports
from app.models.schemas import RawReport

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "data" / "synthetic_reports.json"


async def main(fixture_path: Path) -> None:
    if not fixture_path.exists():
        print(f"No such file: {fixture_path}", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(fixture_path.read_text())
    reports = [RawReport(**r) for r in raw]
    print(f"Parsed {len(reports)} report(s) from {fixture_path.name}")

    async with AsyncSessionLocal() as session:
        try:
            await save_reports(session, reports)
        except Exception as exc:
            print(
                f"Failed writing to Postgres: {exc}\n"
                "Is Postgres running (`docker compose up -d`) and migrated "
                "(`alembic upgrade head`)?",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"Inserted {len(reports)} report(s) into the `reports` table.")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FIXTURE
    asyncio.run(main(path))
