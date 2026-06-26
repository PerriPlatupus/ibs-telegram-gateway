from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from .database import Base

class PdnPolicy(Base):
    __tablename__ = "pdn_policies"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String, unique=True, nullable=False)  
    file_path = Column(String, nullable=False)              
    text_hash = Column(String(64), nullable=False)    
    created_at = Column(DateTime, default=datetime.utcnow)