from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.database import get_db
from app.models.models import Acquisto, Vendita

router = APIRouter()

@router.get("/")
def get_acquisti(db: Session = Depends(get_db)):
    """Ottieni tutti gli acquisti"""
    acquisti = db.query(Acquisto).order_by(Acquisto.created_at.desc()).all()
    return acquisti

@router.get("/{acquisto_id}")
def get_acquisto(acquisto_id: int, db: Session = Depends(get_db)):
    """Ottieni un acquisto specifico"""
    acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
    if acquisto is None:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    return acquisto