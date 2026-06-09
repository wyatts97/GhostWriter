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
    """Run Alembic migrations on startup. Falls back to create_all if not yet migrated."""
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext

    # Check if alembic_revision table exists: if not, do a baseline stamp then upgrade
    async with engine.begin() as conn:

        def _check_and_migrate(sync_conn):
            mc = MigrationContext.configure(sync_conn)
            current_rev = mc.get_current_revision()

            if current_rev is None:
                # No alembic tracking yet — run create_all for baseline, then stamp
                Base.metadata.create_all(sync_conn)
                alembic_cfg = AlembicConfig("alembic.ini")
                script = ScriptDirectory.from_config(alembic_cfg)
                # Stamp with the head revision so future migrations know where we are
                from alembic.command import stamp
                stamp(alembic_cfg, revision="head")
                return

            # Already tracked — run pending migrations
            alembic_cfg = AlembicConfig("alembic.ini")
            from alembic.command import upgrade
            upgrade(alembic_cfg, "head")

        await conn.run_sync(_check_and_migrate)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for dependency injection."""
    async with async_session_factory() as session:
        yield session
