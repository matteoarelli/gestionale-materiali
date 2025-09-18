import os
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import uvicorn
from datetime import datetime, date

from app.database import get_db, engine, Base
from app.models.models import Acquisto, Vendita
from app.routers import acquisti

# Crea le tabelle
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Gestionale Materiali",
    description="Sistema per tracking acquisti e vendite",
    version="1.0.0"
)

# Mount static files (solo se la cartella esiste)
import os
static_dir = "app/static"
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(acquisti.router, prefix="/api/acquisti", tags=["acquisti"])

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard principale"""
    
    # Statistiche generali
    total_acquisti = db.query(Acquisto).count()
    acquisti_venduti = db.query(Acquisto).filter(Acquisto.vendite.any()).count()
    acquisti_in_stock = total_acquisti - acquisti_venduti
    
    # Calcoli finanziari
    total_investito = db.query(Acquisto).all()
    investimento_totale = sum(a.costo_totale for a in total_investito)
    
    vendite_totali = db.query(Vendita).all()
    ricavi_totali = sum(v.ricavo_netto for v in vendite_totali)
    
    margine_totale = ricavi_totali - sum(a.costo_totale for a in total_investito if a.venduto)
    
    # Ultimi acquisti
    ultimi_acquisti = db.query(Acquisto).order_by(Acquisto.created_at.desc()).limit(10).all()
    
    # Ultime vendite
    ultime_vendite = db.query(Vendita).order_by(Vendita.created_at.desc()).limit(10).all()
    
    stats = {
        "total_acquisti": total_acquisti,
        "acquisti_venduti": acquisti_venduti,
        "acquisti_in_stock": acquisti_in_stock,
        "investimento_totale": round(investimento_totale, 2),
        "ricavi_totali": round(ricavi_totali, 2),
        "margine_totale": round(margine_totale, 2),
        "roi_percentuale": round((margine_totale / investimento_totale * 100) if investimento_totale > 0 else 0, 2)
    }
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "ultimi_acquisti": ultimi_acquisti,
        "ultime_vendite": ultime_vendite
    })

@app.get("/acquisti", response_class=HTMLResponse)
async def lista_acquisti(request: Request, db: Session = Depends(get_db)):
    """Pagina lista acquisti"""
    acquisti = db.query(Acquisto).order_by(Acquisto.created_at.desc()).all()
    return templates.TemplateResponse("acquisti.html", {
        "request": request,
        "acquisti": acquisti
    })

@app.get("/acquisti/nuovo", response_class=HTMLResponse)
async def nuovo_acquisto_form(request: Request):
    """Form per nuovo acquisto"""
    return templates.TemplateResponse("nuovo_acquisto.html", {
        "request": request
    })

@app.post("/acquisti/nuovo")
async def crea_acquisto(
    request: Request,
    id_acquisto_univoco: str = Form(...),
    dove_acquistato: str = Form(...),
    venditore: str = Form(...),
    prodotto_descrizione: str = Form(...),
    seriale: str = Form(...),
    costo_acquisto: float = Form(...),
    costi_accessori: float = Form(0.0),
    data_pagamento: Optional[str] = Form(None),
    data_consegna: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Crea nuovo acquisto"""
    
    # Verifica duplicati
    if db.query(Acquisto).filter(Acquisto.id_acquisto_univoco == id_acquisto_univoco).first():
        raise HTTPException(status_code=400, detail="ID acquisto già esistente")
    
    if db.query(Acquisto).filter(Acquisto.seriale == seriale).first():
        raise HTTPException(status_code=400, detail="Seriale già esistente")
    
    # Converti date
    data_pag = None
    data_cons = None
    
    if data_pagamento:
        data_pag = datetime.strptime(data_pagamento, "%Y-%m-%d").date()
    if data_consegna:
        data_cons = datetime.strptime(data_consegna, "%Y-%m-%d").date()
    
    nuovo_acquisto = Acquisto(
        id_acquisto_univoco=id_acquisto_univoco,
        dove_acquistato=dove_acquistato,
        venditore=venditore,
        prodotto_descrizione=prodotto_descrizione,
        seriale=seriale,
        costo_acquisto=costo_acquisto,
        costi_accessori=costi_accessori,
        data_pagamento=data_pag,
        data_consegna=data_cons
    )
    
    db.add(nuovo_acquisto)
    db.commit()
    
    return RedirectResponse(url="/acquisti", status_code=303)

@app.get("/vendite", response_class=HTMLResponse)
async def lista_vendite(request: Request, db: Session = Depends(get_db)):
    """Pagina lista vendite"""
    vendite = db.query(Vendita).order_by(Vendita.created_at.desc()).all()
    return templates.TemplateResponse("vendite.html", {
        "request": request,
        "vendite": vendite
    })

@app.get("/health")
async def health_check():
    """Health check per Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)