"""timezone-aware datetimes

Revision ID: 0002_timezone_aware_datetimes
Revises: 0001_initial
Create Date: 2026-08-28

0001_initial created every timestamp column as plain DateTime, i.e.
Postgres TIMESTAMP WITHOUT TIME ZONE. Every datetime the app actually
generates (app/models/schemas.py::_utcnow) is tz-aware UTC, so asyncpg
rejected inserts with:
    can't subtract offset-naive and offset-aware datetimes

Converts each column to TIMESTAMP WITH TIME ZONE. `USING <col> AT TIME
ZONE 'UTC'` tells Postgres to interpret any existing naive values as
already being UTC (true here — _utcnow() has always produced UTC),
rather than reinterpreting them in the server's local zone.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_timezone_aware_datetimes"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ("reports", "received_at"),
    ("evidence_clusters", "first_seen"),
    ("evidence_clusters", "last_seen"),
    ("mission_proposals", "created_at"),
    ("constraint_check_results", "checked_at"),
    ("commander_decisions", "decided_at"),
    ("events", "occurred_at"),
    ("events", "recorded_at"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
