"""wealth checkpoints and projection settings

Revision ID: 2f7a4c6d8e91
Revises: f3b8c2d9e4a1
Create Date: 2026-05-28 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2f7a4c6d8e91"
down_revision: Union[str, Sequence[str], None] = "f3b8c2d9e4a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wealth_checkpoints",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("checkpoint_date", sa.Date(), nullable=False),
        sa.Column("wealth_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "checkpoint_date",
            "currency",
            name="uq_wealth_checkpoints_user_date_currency",
        ),
    )
    op.create_index(
        "ix_wealth_checkpoints_user_date",
        "wealth_checkpoints",
        ["user_id", "checkpoint_date"],
    )

    op.create_table(
        "wealth_projection_settings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("average_annual_return_multiplier", sa.Numeric(10, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("wealth_projection_settings")
    op.drop_index("ix_wealth_checkpoints_user_date", table_name="wealth_checkpoints")
    op.drop_table("wealth_checkpoints")
