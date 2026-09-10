from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PREDICTION_DIR = DATA_DIR / "predictions"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PREDICTION_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}, future=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def _default_literal(column) -> str | None:
    """Return a SQL DEFAULT literal for a column, or ``None`` when unavailable."""
    if column.server_default is not None:
        arg = getattr(column.server_default, "arg", None)
        if isinstance(arg, str):
            return arg
    default = getattr(column, "default", None)
    arg = getattr(default, "arg", None)
    if isinstance(arg, str):
        return f"'{arg}'"
    if isinstance(arg, (int, float)):
        return str(arg)
    return None


def ensure_schema() -> None:
    """Create the persisted schema and migrate existing tables in place.

    The SQLite database lives in a plain file at ``DATA_DIR/app.db``, so its
    state persists between application restarts. ``create_all`` only creates
    tables that are missing; for tables that already exist this helper adds any
    newly introduced mapped columns via ``ALTER TABLE ... ADD COLUMN`` so that
    schema evolution never requires dropping the existing ``app.db`` file.
    """
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            column_type = column.type.compile(dialect=engine.dialect)
            if column.nullable:
                nullable = "NULL"
            else:
                default_literal = _default_literal(column)
                nullable = f"NOT NULL DEFAULT {default_literal}" if default_literal else "NULL"
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type} {nullable}'
                )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
