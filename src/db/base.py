from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    Import this in every model module. Import it in alembic/env.py
    so Alembic can discover metadata for autogenerate.
    """
