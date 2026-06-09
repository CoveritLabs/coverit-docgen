from sqlalchemy import Column, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class LabeledStateORM(Base):
    """SQLAlchemy ORM model for storing labeled states in PostgreSQL."""

    __tablename__ = "labeled_states"

    state_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=True)
    description = Column(Text, nullable=True)


class LabeledElementORM(Base):
    """SQLAlchemy ORM model for storing labeled transitions/elements in PostgreSQL."""

    __tablename__ = "labeled_elements"

    element_id = Column(String, primary_key=True, index=True)
    html_snippet = Column(Text, nullable=False)
    name = Column(String, nullable=True)
    action = Column(String, nullable=True)
