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
from app.models.models import Acquisto, Vendita, Prodotto
from app.routers import acquisti

# Ricrea le tabelle (elimina e ricrea tutto)
Base.metadata.drop_all(bind=engine)
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
    total_prodotti = db.query(Prodotto).count()
    prodotti_venduti = db.query(Prodotto).filter(Prodotto.vendite.any()).count()
    prodotti_in_stock = total_prodotti - prodotti_venduti
    
    # Calcoli finanziari
    acquisti = db.query(Acquisto).all()
    investimento_totale = sum(a.costo_totale for a in acquisti)
    
    vendite_totali = db.query(Vendita).all()
    ricavi_totali = sum(v.ricavo_netto for v in vendite_totali)
    
    # Margine totale
    margine_totale = ricavi_totali - investimento_totale
    
    # Ultimi acquisti
    ultimi_acquisti = db.query(Acquisto).order_by(Acquisto.created_at.desc()).limit(10).all()
    
    # Ultime vendite
    ultime_vendite = db.query(Vendita).order_by(Vendita.created_at.desc()).limit(10).all()
    
    stats = {
        "total_acquisti": total_acquisti,
        "total_prodotti": total_prodotti,
        "acquisti_venduti": prodotti_venduti,
        "acquisti_in_stock": prodotti_in_stock,
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
async def crea_acquisto(request: Request, db: Session = Depends(get_db)):
    """Crea nuovo acquisto con multiprodotti"""
    
    form_data = await request.form()
    
    # Dati generali acquisto
    id_acquisto_univoco = form_data.get("id_acquisto_univoco", "").strip()
    dove_acquistato = form_data.get("dove_acquistato", "").strip()
    venditore = form_data.get("venditore", "").strip()
    costo_acquisto = float(form_data.get("costo_acquisto", 0))
    costi_accessori = float(form_data.get("costi_accessori", 0))
    data_pagamento = form_data.get("data_pagamento", "").strip()
    data_consegna = form_data.get("data_consegna", "").strip()
    note = form_data.get("note", "").strip()
    
    # Verifica duplicati
    if db.query(Acquisto).filter(Acquisto.id_acquisto_univoco == id_acquisto_univoco).first():
        raise HTTPException(status_code=400, detail="ID acquisto già esistente")
    
    # Converti date
    data_pag = None
    data_cons = None
    
    if data_pagamento:
        try:
            data_pag = datetime.strptime(data_pagamento, "%Y-%m-%d").date()
        except:
            pass
            
    if data_consegna:
        try:
            data_cons = datetime.strptime(data_consegna, "%Y-%m-%d").date()
        except:
            pass
    
    # Crea l'acquisto
    nuovo_acquisto = Acquisto(
        id_acquisto_univoco=id_acquisto_univoco,
        dove_acquistato=dove_acquistato,
        venditore=venditore,
        costo_acquisto=costo_acquisto,
        costi_accessori=costi_accessori,
        data_pagamento=data_pag,
        data_consegna=data_cons,
        note=note if note else None
    )
    
    db.add(nuovo_acquisto)
    db.flush()  # Per ottenere l'ID
    
    # Estrai i dati dei prodotti
    prodotti_data = {}
    for key, value in form_data.items():
        if key.startswith('prodotti[') and value.strip():
            # Es: prodotti[0][seriale] -> index=0, field=seriale
            import re
            match = re.match(r'prodotti\[(\d+)\]\[(\w+)\]', key)
            if match:
                index = int(match.group(1))
                field = match.group(2)
                
                if index not in prodotti_data:
                    prodotti_data[index] = {}
                prodotti_data[index][field] = value.strip()
    
    # Crea i prodotti
    for index, prodotto_info in prodotti_data.items():
        seriale = prodotto_info.get('seriale', '').strip()
        descrizione = prodotto_info.get('descrizione', '').strip()
        note_prodotto = prodotto_info.get('note', '').strip()
        
        if not seriale or not descrizione:
            continue
            
        # Verifica seriale univoco
        if db.query(Prodotto).filter(Prodotto.seriale == seriale).first():
            raise HTTPException(status_code=400, detail=f"Seriale {seriale} già esistente")
        
        nuovo_prodotto = Prodotto(
            acquisto_id=nuovo_acquisto.id,
            seriale=seriale,
            prodotto_descrizione=descrizione,
            note_prodotto=note_prodotto if note_prodotto else None
        )
        
        db.add(nuovo_prodotto)
    
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

@app.get("/api/acquisti/{acquisto_id}")
async def get_acquisto_dettaglio(acquisto_id: int, db: Session = Depends(get_db)):
    """API per ottenere dettagli completi di un acquisto"""
    acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    return {
        "id": acquisto.id,
        "id_acquisto_univoco": acquisto.id_acquisto_univoco,
        "dove_acquistato": acquisto.dove_acquistato,
        "venditore": acquisto.venditore,
        "costo_acquisto": float(acquisto.costo_acquisto),
        "costi_accessori": float(acquisto.costi_accessori or 0),
        "costo_totale": acquisto.costo_totale,
        "data_pagamento": acquisto.data_pagamento.strftime('%d/%m/%Y') if acquisto.data_pagamento else None,
        "data_consegna": acquisto.data_consegna.strftime('%d/%m/%Y') if acquisto.data_consegna else None,
        "note": acquisto.note,
        "created_at": acquisto.created_at.strftime('%d/%m/%Y %H:%M'),
        "prodotti": [
            {
                "id": p.id,
                "seriale": p.seriale,
                "prodotto_descrizione": p.prodotto_descrizione,
                "note_prodotto": p.note_prodotto,
                "venduto": p.venduto,
                "ricavo_vendita": p.ricavo_vendita
            }
            for p in acquisto.prodotti
        ]
    }

@app.post("/acquisti/{acquisto_id}/segna-arrivato")
async def segna_acquisto_arrivato(acquisto_id: int, db: Session = Depends(get_db)):
    """Segna un acquisto come arrivato (imposta data consegna a oggi)"""
    acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    acquisto.data_consegna = date.today()
    db.commit()
    
    return {"message": "Acquisto segnato come arrivato"}

@app.delete("/acquisti/{acquisto_id}")
async def elimina_acquisto(acquisto_id: int, db: Session = Depends(get_db)):
    """Elimina un acquisto e tutti i suoi prodotti"""
    acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    # Verifica che nessun prodotto sia già stato venduto
    prodotti_venduti = [p for p in acquisto.prodotti if p.venduto]
    if prodotti_venduti:
        raise HTTPException(
            status_code=400, 
            detail=f"Impossibile eliminare: {len(prodotti_venduti)} prodotti già venduti"
        )
    
    # Elimina prima i prodotti, poi l'acquisto
    for prodotto in acquisto.prodotti:
        db.delete(prodotto)
    db.delete(acquisto)
    db.commit()
    
    return {"message": "Acquisto eliminato con successo"}

@app.get("/acquisti/{acquisto_id}/modifica", response_class=HTMLResponse)
async def modifica_acquisto_form(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Form per modificare un acquisto"""
    acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    return templates.TemplateResponse("modifica_acquisto.html", {
        "request": request,
        "acquisto": acquisto
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)