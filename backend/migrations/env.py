"""
Alembic environment. Migrations run with the SYNC psycopg2 driver even
though the app uses asyncpg at runtime — this is normal and recommended
practice (Alembic's autogenerate/execution machinery is sync-first);
it has no bearing on which driver the running app uses.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `app.db.models` importable when Alembic is invoked from backend/.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_ASYNC_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://reliefmesh:reliefmesh@localhost:5432/reliefmesh",
)
_SYNC_URL = _ASYNC_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
config.set_main_option("sqlalchemy.url", _SYNC_URL)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
