"""Use Supabase Auth UUIDs for application ownership and enable RLS.

Revision ID: 7d4e9a1c6b20
Revises: 2f7a4c6d8e91
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "7d4e9a1c6b20"
down_revision: str | Sequence[str] | None = "2f7a4c6d8e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNED_TABLES = (
    "accounts",
    "activity_events",
    "budgets",
    "categories",
    "import_jobs",
    "imports",
    "learned_rules",
    "transactions",
    "uploaded_files",
    "wealth_checkpoints",
    "wealth_projection_settings",
)
INDIRECT_OWNED_TABLES = ("agent_runs", "import_events")


def _drop_user_foreign_keys() -> None:
    inspector = inspect(op.get_bind())
    for table_name in OWNED_TABLES:
        for foreign_key in inspector.get_foreign_keys(table_name):
            if foreign_key["constrained_columns"] == ["user_id"]:
                op.drop_constraint(foreign_key["name"], table_name, type_="foreignkey")


def _create_user_foreign_keys() -> None:
    for table_name in OWNED_TABLES:
        op.create_foreign_key(
            f"fk_{table_name}_user_id_users",
            table_name,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Supabase Auth identity migration requires PostgreSQL")

    op.execute(
        """
        CREATE TEMPORARY TABLE user_id_migration_map (
            old_id varchar(32) PRIMARY KEY,
            new_id uuid NOT NULL UNIQUE
        ) ON COMMIT DROP
        """
    )
    op.execute(
        """
        INSERT INTO user_id_migration_map (old_id, new_id)
        SELECT application_user.id, auth_user.id
        FROM public.users AS application_user
        JOIN auth.users AS auth_user
          ON lower(auth_user.email) = lower(application_user.email)
        """
    )

    application_user_count = bind.execute(sa.text("SELECT count(*) FROM public.users")).scalar_one()
    mapped_user_count = bind.execute(sa.text("SELECT count(*) FROM user_id_migration_map")).scalar_one()
    if application_user_count == 0 or mapped_user_count != application_user_count:
        raise RuntimeError(
            "Every public.users row must have exactly one matching auth.users email before migration"
        )

    _drop_user_foreign_keys()

    for table_name in OWNED_TABLES:
        op.alter_column(
            table_name,
            "user_id",
            existing_type=sa.String(length=32),
            type_=sa.String(length=36),
            existing_nullable=table_name == "categories",
        )
        op.execute(
            sa.text(
                f"""
                UPDATE public.{table_name} AS owned_row
                SET user_id = identity_map.new_id::text
                FROM user_id_migration_map AS identity_map
                WHERE owned_row.user_id = identity_map.old_id
                """
            )
        )

    op.alter_column(
        "users",
        "id",
        existing_type=sa.String(length=32),
        type_=sa.String(length=36),
        existing_nullable=False,
    )
    op.execute(
        """
        UPDATE public.users AS application_user
        SET id = identity_map.new_id::text
        FROM user_id_migration_map AS identity_map
        WHERE application_user.id = identity_map.old_id
        """
    )

    for table_name in OWNED_TABLES:
        op.alter_column(
            table_name,
            "user_id",
            existing_type=sa.String(length=36),
            type_=sa.UUID(),
            existing_nullable=table_name == "categories",
            postgresql_using="user_id::uuid",
        )

    op.alter_column(
        "users",
        "id",
        existing_type=sa.String(length=36),
        type_=sa.UUID(),
        existing_nullable=False,
        postgresql_using="id::uuid",
    )
    op.create_foreign_key(
        "fk_users_id_auth_users",
        "users",
        "users",
        ["id"],
        ["id"],
        source_schema="public",
        referent_schema="auth",
        ondelete="CASCADE",
    )
    _create_user_foreign_keys()

    op.execute("ALTER TABLE public.users ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY users_own_row ON public.users
        FOR SELECT TO authenticated
        USING (auth.uid() = id)
        """
    )

    for table_name in OWNED_TABLES:
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")

    for table_name in tuple(table for table in OWNED_TABLES if table != "categories"):
        op.execute(
            f"""
            CREATE POLICY {table_name}_own_rows ON public.{table_name}
            FOR SELECT TO authenticated
            USING (auth.uid() = user_id)
            """
        )

    op.execute(
        """
        CREATE POLICY categories_visible_rows ON public.categories
        FOR SELECT TO authenticated
        USING ((user_id IS NULL AND is_system) OR auth.uid() = user_id)
        """
    )
    for table_name in INDIRECT_OWNED_TABLES:
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table_name}_own_rows ON public.{table_name}
            FOR SELECT TO authenticated
            USING (
                EXISTS (
                    SELECT 1
                    FROM public.imports
                    WHERE imports.id = {table_name}.import_id
                      AND imports.user_id = auth.uid()
                )
            )
            """
        )

    protected_tables = ("users", *OWNED_TABLES, *INDIRECT_OWNED_TABLES)
    for table_name in protected_tables:
        op.execute(
            f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM anon, authenticated"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Supabase Auth identity migration requires PostgreSQL")

    op.execute("DROP POLICY IF EXISTS users_own_row ON public.users")
    op.execute("ALTER TABLE public.users DISABLE ROW LEVEL SECURITY")
    for table_name in OWNED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table_name}_own_rows ON public.{table_name}")
        op.execute(f"ALTER TABLE public.{table_name} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS categories_visible_rows ON public.categories")
    for table_name in INDIRECT_OWNED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table_name}_own_rows ON public.{table_name}")
        op.execute(f"ALTER TABLE public.{table_name} DISABLE ROW LEVEL SECURITY")

    protected_tables = ("users", *OWNED_TABLES, *INDIRECT_OWNED_TABLES)
    for table_name in protected_tables:
        op.execute(
            f"GRANT ALL PRIVILEGES ON TABLE public.{table_name} TO anon, authenticated"
        )

    _drop_user_foreign_keys()
    op.drop_constraint("fk_users_id_auth_users", "users", schema="public", type_="foreignkey")

    for table_name in OWNED_TABLES:
        op.alter_column(
            table_name,
            "user_id",
            existing_type=sa.UUID(),
            type_=sa.String(length=36),
            existing_nullable=table_name == "categories",
            postgresql_using="user_id::text",
        )
    op.alter_column(
        "users",
        "id",
        existing_type=sa.UUID(),
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="id::text",
    )
    _create_user_foreign_keys()
