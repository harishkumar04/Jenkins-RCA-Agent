from sqlalchemy import Column, Integer, String
from database import Base

class Incident(Base):

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)

    build_number = Column(String, nullable=True)

    logs = Column(String)

    analysis = Column(String)
