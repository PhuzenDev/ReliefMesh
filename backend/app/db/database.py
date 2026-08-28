"""
Async DB engine + session — used everywhere EXCEPT the audit logging
handler (see audit.py for why that one path is deliberately sync).

Reads DATABASE_URL from the environment so local dev / CI / the demo
box can point at different Postgres instances without code changes.
Expected shape:
    postgresql+asyncpg://user:password@host:5432/reliefmesh
"""
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://reliefmesh:reliefmesh@localhost:5432/reliefmesh",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`."""
    async with AsyncSessionLocal() as session:
        yield session


async def create_all_dev_only() -> None:
    """
    Convenience for local dev/tests ONLY — creates tables directly from
    ORM metadata, bypassing Alembic. Do not call this once the demo DB
    is under Alembic's management (migrations/) or the two will drift
    out of sync. Guarded behind an explicit call, never run on import.
    """
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
