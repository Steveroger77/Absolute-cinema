"""SQLAlchemy DeclarativeBase definition."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared ORM base class for all database models."""
