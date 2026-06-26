import hashlib
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database.database import engine, Base, SessionLocal
from database.employee import Employee
from database.pdn_policy import PdnPolicy
from typing import Optional

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Secure RF Data Core")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class AuthRequest(BaseModel):
    telegram_id: int

class RegisterRequest(BaseModel):
    telegram_id: int
    full_name: str
    birth_date: str
    is_consented: bool = True
    policy_id: Optional[int] = 1

class SyncRequest(BaseModel):
    file_hash: str

@app.post("/api/v1/policy/sync")
def sync_policy(data: SyncRequest, db: Session = Depends(get_db)):
    last_policy = db.query(PdnPolicy).order_by(PdnPolicy.id.desc()).first()
    if not last_policy or last_policy.text_hash != data.file_hash:
        new_version = f"v{(last_policy.id + 1) if last_policy else 1}"
        new_policy = PdnPolicy(
            version=new_version,
            file_path="remote_storage/policy_signed.pdf",
            text_hash=data.file_hash
        )
        db.add(new_policy)
        db.commit()
        return {"status": "ok", "message": f"Policy updated to {new_version}"}
    return {"status": "ok", "message": "Already up to date"}

@app.post("/api/v1/employee/register")
def register_employee(data: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(Employee).filter(Employee.telegram_id == data.telegram_id).first():
        return {"status": "error", "message": "User exists"}
    new_emp = Employee(
        telegram_id=data.telegram_id,
        full_name=data.full_name,
        birth_date=data.birth_date,
        is_pdn_consented=data.is_consented,
        pdn_consent_date=datetime.utcnow() if data.is_consented else None,
        policy_id=data.policy_id
    )
    db.add(new_emp)
    db.commit()
    return {"status": "ok"}

@app.post("/api/v1/employee/check")
def check_employee(req: AuthRequest, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.telegram_id == req.telegram_id).first()
    if not emp:
        return {"allowed": False, "reason": "not_in_whitelist"}
    if not emp.is_verified:
        return {"allowed": False, "reason": "pending_admin_approval"}
    policy = db.query(PdnPolicy).order_by(PdnPolicy.id.desc()).first()
    return {
        "allowed": True,
        "full_name": emp.full_name,
        "is_consented": emp.is_pdn_consented,
        "policy_id": policy.id if policy else None
    }

@app.post("/api/v1/employee/verify")
def verify_employee(data: dict, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.telegram_id == data["telegram_id"]).first()
    if emp:
        emp.is_verified = 1
        emp.verified_by = data["admin_name"]
        db.commit()
        return {"status": "ok"}
    return {"status": "error"}

@app.get("/api/v1/employee/birthday_today")
def get_birthdays_today(db: Session = Depends(get_db)):
    today = datetime.now().strftime("%m-%d")
    birthdays = db.query(Employee).filter(Employee.birth_date.like(f"%{today}%")).all()
    return [{"full_name": e.full_name} for e in birthdays]