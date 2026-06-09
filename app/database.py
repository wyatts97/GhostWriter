from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Ensure the database directory exists (handles missing volume dirs on fresh clones)
_db_path = Path(settings.database_url.replace("sqlite+aiosqlite:///", ""))
_db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url, echo=False, connect_args={"check_same_thread": False})

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Run Alembic migrations on startup. Falls back to create_all if not yet migrated.

    Uses a separate thread for ``alembic.command.upgrade()`` / ``stamp()`` because
    they call ``asyncio.run()`` inside ``env.py``, which collides with FastAPI's
    already-running event loop.
    """
    import asyncio

    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext

    async with engine.begin() as conn:

        def _check_and_baseline(sync_conn):
            """Check alembic tracking; if absent, create all tables (inline,
            safe) so the threaded stamp call below has a consistent schema."""
            mc = MigrationContext.configure(sync_conn)
            rev = mc.get_current_revision()
            if rev is None:
                Base.metadata.create_all(sync_conn)
            return rev

        current_rev = await conn.run_sync(_check_and_baseline)

    cfg = AlembicConfig("alembic.ini")

    if current_rev is None:
        # Fresh database — stamp with head revision so alembic knows where we
        # are.  Runs in a thread because env.py → asyncio.run().
        from alembic.command import stamp

        await asyncio.to_thread(stamp, cfg, "head")
    else:
        # Run pending migrations in a separate thread.
        from alembic.command import upgrade

        await asyncio.to_thread(upgrade, cfg, "head")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for dependency injection."""
    async with async_session_factory() as session:
        yield session
