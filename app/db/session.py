from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
engine = create_engine(settings.db_url, echo=False, connect_args=connect_args)


def _ensure_importjob_progress_columns() -> None:
    if not settings.db_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        table_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='importjob'"
        ).first()
        if not table_exists:
            return

        columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info('importjob')").fetchall()
        }

        if "stage" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE importjob ADD COLUMN stage TEXT NOT NULL DEFAULT 'queued'"
            )
        if "progress_pct" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE importjob ADD COLUMN progress_pct INTEGER NOT NULL DEFAULT 0"
            )
        if "stage_message" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE importjob ADD COLUMN stage_message TEXT"
            )


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_importjob_progress_columns()


def get_session():
    with Session(engine) as session:
        yield session
