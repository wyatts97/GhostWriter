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

    Uses a separate thread for ``alembic.command.upgrade()`` because it calls
    ``asyncio.run()`` inside ``env.py``, which collides with FastAPI's running
    event loop.
    """
    import asyncio

    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    async with engine.begin() as conn:

        def _check_and_stamp(sync_conn):
            """Check tracking; create_all + stamp if fresh, otherwise do nothing
            here (upgrade runs in a separate thread below)."""
            mc = MigrationContext.configure(sync_conn)
            current_rev = mc.get_current_revision()

            if current_rev is None:
                # No alembic tracking yet — run create_all for baseline, then stamp
                Base.metadata.create_all(sync_conn)
                alembic_cfg = AlembicConfig("alembic.ini")
                script = ScriptDirectory.from_config(alembic_cfg)
                mc.stamp(script.get_current_head())

        await conn.run_sync(_check_and_stamp)

    # Run pending migrations in a *separate thread* so that env.py can safely
    # call asyncio.run() without conflicting with the already-running loop.
    def _run_upgrade() -> None:
        from alembic.config import Config as AlembicConfig
        from alembic.command import upgrade

        cfg = AlembicConfig("alembic.ini")
        upgrade(cfg, "head")

    await asyncio.to_thread(_run_upgrade)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for dependency injection."""
    async with async_session_factory() as session:
        yield session
