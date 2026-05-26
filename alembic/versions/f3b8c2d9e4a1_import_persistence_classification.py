"""import persistence classification

Revision ID: f3b8c2d9e4a1
Revises: c2c1a7f5b9e8
Create Date: 2026-05-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8c2d9e4a1"
down_revision: Union[str, Sequence[str], None] = "c2c1a7f5b9e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.add_column(
            sa.Column("statement_kind", sa.String(length=40), nullable=False, server_default="unknown")
        )
        batch_op.add_column(sa.Column("statement_kind_confidence", sa.Numeric(5, 4), nullable=True))
        batch_op.add_column(sa.Column("statement_kind_reason", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("statement_period_start", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("statement_period_end", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("institution_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("account_hint", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "statement_kind_source",
                sa.String(length=40),
                nullable=False,
                server_default="system",
            )
        )
        batch_op.create_check_constraint(
            "ck_import_jobs_statement_kind",
            "statement_kind in ('checking_account', 'credit_card', 'unknown')",
        )
        batch_op.create_check_constraint(
            "ck_import_jobs_statement_kind_source",
            "statement_kind_source in ('agent', 'user', 'system')",
        )
        batch_op.create_check_constraint(
            "ck_import_jobs_statement_kind_confidence_range",
            "statement_kind_confidence is null or "
            "(statement_kind_confidence >= 0 and statement_kind_confidence <= 1)",
        )

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("import_job_id", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("statement_kind", sa.String(length=40), nullable=False, server_default="unknown")
        )
        batch_op.add_column(
            sa.Column(
                "transaction_nature",
                sa.String(length=40),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(
            sa.Column("report_bucket", sa.String(length=40), nullable=False, server_default="unknown")
        )
        batch_op.add_column(
            sa.Column(
                "classification_source",
                sa.String(length=40),
                nullable=False,
                server_default="system",
            )
        )
        batch_op.add_column(sa.Column("classification_confidence", sa.Numeric(5, 4), nullable=True))
        batch_op.add_column(sa.Column("classification_reason", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("running_balance", sa.Numeric(14, 2), nullable=True))
        batch_op.create_foreign_key(
            "fk_transactions_import_job_id_import_jobs",
            "import_jobs",
            ["import_job_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_transactions_statement_kind",
            "statement_kind in ('checking_account', 'credit_card', 'unknown')",
        )
        batch_op.create_check_constraint(
            "ck_transactions_transaction_nature",
            "transaction_nature in ('income', 'expense', 'transfer', 'refund', "
            "'card_payment', 'unknown')",
        )
        batch_op.create_check_constraint(
            "ck_transactions_report_bucket",
            "report_bucket in ('income', 'debt_installment', 'fixed_cost', "
            "'living_cost', 'excluded', 'unknown')",
        )
        batch_op.create_check_constraint(
            "ck_transactions_classification_source",
            "classification_source in ('agent', 'user', 'system')",
        )
        batch_op.create_check_constraint(
            "ck_transactions_classification_confidence_range",
            "classification_confidence is null or "
            "(classification_confidence >= 0 and classification_confidence <= 1)",
        )
        batch_op.create_index("ix_transactions_import_job_id", ["import_job_id"])
        batch_op.create_index(
            "ix_transactions_report_readiness",
            ["user_id", "is_draft", "reverted_at", "posted_at", "report_bucket"],
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_index("ix_transactions_report_readiness")
        batch_op.drop_index("ix_transactions_import_job_id")
        batch_op.drop_constraint("ck_transactions_classification_confidence_range", type_="check")
        batch_op.drop_constraint("ck_transactions_classification_source", type_="check")
        batch_op.drop_constraint("ck_transactions_report_bucket", type_="check")
        batch_op.drop_constraint("ck_transactions_transaction_nature", type_="check")
        batch_op.drop_constraint("ck_transactions_statement_kind", type_="check")
        batch_op.drop_constraint("fk_transactions_import_job_id_import_jobs", type_="foreignkey")
        batch_op.drop_column("running_balance")
        batch_op.drop_column("classification_reason")
        batch_op.drop_column("classification_confidence")
        batch_op.drop_column("classification_source")
        batch_op.drop_column("report_bucket")
        batch_op.drop_column("transaction_nature")
        batch_op.drop_column("statement_kind")
        batch_op.drop_column("import_job_id")

    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.drop_constraint("ck_import_jobs_statement_kind_confidence_range", type_="check")
        batch_op.drop_constraint("ck_import_jobs_statement_kind_source", type_="check")
        batch_op.drop_constraint("ck_import_jobs_statement_kind", type_="check")
        batch_op.drop_column("statement_kind_source")
        batch_op.drop_column("account_hint")
        batch_op.drop_column("institution_name")
        batch_op.drop_column("statement_period_end")
        batch_op.drop_column("statement_period_start")
        batch_op.drop_column("statement_kind_reason")
        batch_op.drop_column("statement_kind_confidence")
        batch_op.drop_column("statement_kind")
