from sqlalchemy import Column, DateTime, Integer, String
from datetime import datetime, timezone
from database import Base

class Incident(Base):

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    build_number = Column(String, nullable=True)

    build_url = Column(String, nullable=True)

    category = Column(String, nullable=True)

    severity = Column(String, nullable=True)

    failure_type = Column(String, nullable=True)

    root_cause = Column(String, nullable=True)

    fingerprint = Column(String, nullable=True, index=True)

    recurrence_count = Column(Integer, default=1)

    recurring = Column(String, default="No")

    recurrence_memory = Column(String, nullable=True)

    resolution_playbook = Column(String, nullable=True)

    code_context = Column(String, nullable=True)

    logs = Column(String)

    analysis = Column(String)
