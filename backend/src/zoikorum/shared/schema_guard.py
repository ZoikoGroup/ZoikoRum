"""Refuse to serve or consume events against an incomplete application schema."""
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text

from zoikorum.shared.db import Base, get_engine


def expected_heads() -> set[str]:
    migrations = Path(__file__).resolve().parents[3] / "alembic"
    return set(ScriptDirectory(str(migrations)).get_heads())


def missing_columns(actual: set[tuple[str, str, str]]) -> list[str]:
    return sorted(f"{table.schema}.{table.name}.{column.name}"
                  for table in Base.metadata.tables.values() for column in table.columns
                  if (table.schema, table.name, column.name) not in actual)


async def ensure_schema_current() -> None:
    """Read-only checks; migrations remain an explicit deployment operation."""
    try:
        async with get_engine().connect() as connection:
            exists = await connection.scalar(text("SELECT to_regclass('platform.alembic_version')"))
            current = set((await connection.execute(text("SELECT version_num FROM platform.alembic_version"))).scalars()) if exists else set()
            wanted = expected_heads()
            if current != wanted:
                raise RuntimeError("Database migrations are not current. From backend/, run python -m alembic upgrade head before starting the API or worker.")
            rows = (await connection.execute(text("SELECT table_schema, table_name, column_name FROM information_schema.columns"))).all()
            missing = missing_columns({tuple(row) for row in rows})
            if missing:
                raise RuntimeError("Database schema is incomplete despite its migration marker: " + ", ".join(missing[:10]) + ". Run alembic check and repair the schema before starting the API or worker.")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Database startup validation failed. Check database connectivity and run alembic upgrade head from backend/.") from exc
