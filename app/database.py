from datetime import datetime

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Sem Alembic neste projeto: Base.metadata.create_all cria tabelas novas mas
# não altera tabelas existentes. Colunas novas em tabelas já existentes
# precisam desse ajuste leve e idempotente, rodado uma vez no startup.
_LIGHTWEIGHT_COLUMN_MIGRATIONS = {
    "monitored_ips": [("check_interval_minutes", "INTEGER")],
    "users": [("notify_email", "TEXT"), ("pushover_user_key", "TEXT"), ("language", "TEXT")],
}


def run_lightweight_migrations(bind_engine=engine):
    inspector = inspect(bind_engine)
    existing_tables = set(inspector.get_table_names())
    with bind_engine.begin() as conn:
        for table, columns in _LIGHTWEIGHT_COLUMN_MIGRATIONS.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_type in columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
        if "listings" in existing_tables:
            _ensure_open_listing_uniqueness(conn)


def _ensure_open_listing_uniqueness(conn):
    """Enforce "one open listing per (target, blacklist)" at the DB level, so
    two concurrent checks can't create duplicate listings/notifications.

    Partial unique indexes work on both SQLite (>=3.8) and Postgres. Any
    pre-existing duplicates must be collapsed first, otherwise CREATE UNIQUE
    INDEX fails: keep the oldest open listing per group (lowest id) and close
    the rest (removed_at=now, status=removed). Idempotent.
    """
    now_str = datetime.utcnow().isoformat(sep=" ")
    for target_col in ("ip_id", "domain_id"):
        conn.execute(
            text(
                f"""
                UPDATE listings
                SET removed_at = :now, status = 'removed'
                WHERE removed_at IS NULL
                  AND {target_col} IS NOT NULL
                  AND id NOT IN (
                    SELECT MIN(id) FROM listings
                    WHERE removed_at IS NULL AND {target_col} IS NOT NULL
                    GROUP BY {target_col}, blacklist_id
                  )
                """
            ),
            {"now": now_str},
        )
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_listing_ip "
        "ON listings (ip_id, blacklist_id) WHERE removed_at IS NULL"
    ))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_listing_domain "
        "ON listings (domain_id, blacklist_id) WHERE removed_at IS NULL"
    ))
