from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.engine import create_database_engine

engine = create_database_engine(
    settings.database_url,
    app_env=settings.app_env,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
