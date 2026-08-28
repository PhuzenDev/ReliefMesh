"""add llm_explanation to constraint_check_results

Revision ID: 0002_add_llm_explanation
Revises: 0001_initial
Create Date: 2026-08-28

Backs the Groq-generated plain-language explanation added to
ConstraintCheckResult (see app/models/schemas.py and
app/agents/constraint_agent.py). Nullable + no default needed on
existing rows since it's populated going forward, not backfilled.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_llm_explanation"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "constraint_check_results",
        sa.Column("llm_explanation", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("constraint_check_results", "llm_explanation")
