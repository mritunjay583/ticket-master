"""SQLAlchemy ORM models (persistence detail behind the repository ports).

Importing the models here ensures they are all registered on ``Base.metadata`` whenever the package
is imported — which Alembic's autogenerate and ``create_all`` rely on to see every table.
"""

from app.models.agent import Agent
from app.models.base import Base
from app.models.processing_result import ProcessingResult
from app.models.ticket import Ticket
from app.models.ticket_event import TicketEvent

__all__ = ["Agent", "Base", "ProcessingResult", "Ticket", "TicketEvent"]
