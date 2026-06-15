import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Некоторые провайдеры выдают connection-string со схемой postgres://,
# которую SQLAlchemy 2.0 не принимает. Приводим к postgresql://.
db_url = settings.database_url
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Importing the models package
    registers every ORM class on Base.metadata.

    Дополнительно прогоняет лёгкие авто-миграции: добавляет недостающие
    колонки на уже существующих таблицах. Полноценные миграции —
    через Alembic, но для учебного MVP этого хватает.
    """
    import models  # noqa: F401  -- side-effect: register models
    Base.metadata.create_all(bind=engine)
    _auto_migrate()


def _auto_migrate():
    """Добавить недостающие колонки на существующих таблицах.

    Список (table, column, sql_type) добавляется сюда при каждом изменении
    модели. Идемпотентно: если колонка уже есть — пропускаем.
    """
    pending = [
        ("assets", "image_url", "VARCHAR(500)"),
    ]
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, sql_type in pending:
            if table not in existing_tables:
                # таблица только что создана — колонка уже включена в DDL
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column in cols:
                continue
            try:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}'))
                logger.info(f"Auto-migration: added column {table}.{column}")
            except Exception as e:
                logger.warning(f"Auto-migration failed for {table}.{column}: {e}")
