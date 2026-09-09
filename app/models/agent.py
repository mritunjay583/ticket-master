"""Agent ORM model — support staff who can be assigned tickets."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enum_types import department_enum
from app.schemas.enums import Department


class Agent(Base, TimestampMixin):
    """A support agent. Optional per the brief, but makes assignment/routing realistic."""

    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    department: Mapped[Department] = mapped_column(department_enum, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Agent id={self.id} email={self.email!r} dept={self.department}>"
