from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database.database import Base

class Employee(Base):
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True)
    full_name = Column(String)
    birth_date = Column(String)
    is_verified = Column(Integer, default=0)
    verified_by = Column(String, nullable=True)
    is_pdn_consented = Column(Boolean, default=False)
    pdn_consent_date = Column(DateTime, nullable=True)
    policy_id = Column(Integer, ForeignKey('pdn_policies.id'), nullable=True)
    
    policy = relationship("PdnPolicy")