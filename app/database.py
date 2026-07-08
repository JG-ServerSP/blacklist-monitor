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
