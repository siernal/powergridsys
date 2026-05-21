from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from core.config import get_settings

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
    registers every ORM class on Base.metadata."""
    import models  # noqa: F401  -- side-effect: register models
    Base.metadata.create_all(bind=engine)
