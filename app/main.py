import os
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from typing import List, Optional
import uvicorn
from datetime import datetime, date, timedelta
import re

from app.database import get_db, engine, Base
from app.models.models import Acquisto, Vendita, Prodotto
from app.routers import acquisti
from app.routes.api_routes import api_router, debug_router

# Crea tutte le tabelle
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Gestionale Materiali",
    description="Sistema per tracking acquisti e vendite",
    version="1.0.0"
)

# Mount static files (solo se la cartella esiste)
static_dir = "app/static"
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(acquisti.router, prefix="/api/acquisti", tags=["acquisti"])
app.include_router(api_router, prefix="/api", tags=["api"])
app.include_router(debug_router, prefix="/debug", tags=["debug"])

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

@app.get("/da-gestire", response_class=HTMLResponse)
async def da_gestire(request: Request, db: Session = Depends(get_db)):
    """Pagina Da Gestire - elementi che richiedono attenzione"""
    
    # Prodotti senza seriali (TUTTI, non solo quelli non venduti)
    prodotti_senza_seriali = db.query(Prodotto).filter(
        or_(
            Prodotto.seriale.is_(None),
            Prodotto.seriale == "",
            Prodotto.seriale == "???",
            Prodotto.seriale == "N/A"
        )
    ).options(joinedload(Prodotto.acquisto)).all()
    
    # Filtra solo quelli non venduti per la visualizzazione
    prodotti_senza_seriali_non_venduti = [p for p in prodotti_senza_seriali if not p.venduto]
    
    # Acquisti non ancora arrivati
    acquisti_non_arrivati = db.query(Acquisto).filter(
        Acquisto.data_consegna.is_(None)
    ).options(joinedload(Acquisto.prodotti)).all()
    
    return templates.TemplateResponse("da_gestire.html", {
        "request": request,
        "prodotti_senza_seriali": prodotti_senza_seriali_non_venduti,
        "acquisti_non_arrivati": acquisti_non_arrivati,
        "now": datetime.now()
    })

@app.post("/da-gestire/segna-tutti-arrivati")
async def segna_tutti_arrivati(db: Session = Depends(get_db)):
    """Segna tutti gli acquisti non arrivati come arrivati oggi"""
    
    acquisti_non_arrivati = db.query(Acquisto).filter(
        Acquisto.data_consegna.is_(None)
    ).all()
    
    count = 0
    for acquisto in acquisti_non_arrivati:
        acquisto.data_consegna = date.today()
        count += 1
    
    db.commit()
    
    return {"message": f"Segnati {count} acquisti come arrivati oggi"}

@app.get("/da-gestire/inserisci-seriali-multipli", response_class=HTMLResponse)
async def inserisci_seriali_multipli_form(request: Request, db: Session = Depends(get_db)):
    """Form per inserimento seriali in blocco"""
    
    # Ottieni tutti i prodotti senza seriali (non venduti)
    prodotti_senza_seriali = db.query(Prodotto).filter(
        Prodotto.seriale.is_(None),
        ~Prodotto.vendite.any()  # Non venduti
    ).options(joinedload(Prodotto.acquisto)).all()
    
    # Raggruppa per acquisto
    prodotti_raggruppati = {}
    for prodotto in prodotti_senza_seriali:
        acquisto_id = prodotto.acquisto.id
        if acquisto_id not in prodotti_raggruppati:
            prodotti_raggruppati[acquisto_id] = {
                'acquisto': prodotto.acquisto,
                'prodotti': []
            }
        prodotti_raggruppati[acquisto_id]['prodotti'].append(prodotto)
    
    # Ordina per priorità (acquisti arrivati da più tempo prima)
    prodotti_raggruppati = dict(sorted(
        prodotti_raggruppati.items(),
        key=lambda x: x[1]['acquisto'].data_consegna or date.min,
        reverse=False
    ))
    
    total_prodotti = len(prodotti_senza_seriali)
    
    return templates.TemplateResponse("inserisci_seriali_multipli.html", {
        "request": request,
        "prodotti_raggruppati": prodotti_raggruppati,
        "total_prodotti": total_prodotti,
        "now": datetime.now()
    })

@app.post("/da-gestire/salva-seriali-multipli")
async def salva_seriali_multipli(request: Request, db: Session = Depends(get_db)):
    """Salva i seriali inseriti in blocco"""
    
    form_data = await request.form()
    
    # Raccogli i dati dei seriali
    seriali_data = {}
    for key, value in form_data.items():
        if key.startswith('prodotti[') and value.strip():
            match = re.match(r'prodotti\[(\d+)\]\[(\w+)\]', key)
            if match:
                index = int(match.group(1))
                field = match.group(2)
                
                if index not in seriali_data:
                    seriali_data[index] = {}
                seriali_data[index][field] = value.strip()
    
    # Aggiorna i seriali
    seriali_inseriti = 0
    seriali_duplicati = 0
    errori = []
    
    for index, dati in seriali_data.items():
        prodotto_id = dati.get('id')
        nuovo_seriale = dati.get('seriale', '').strip()
        
        if not prodotto_id or not nuovo_seriale:
            continue
            
        try:
            # Verifica che il seriale non esista già 
            if db.query(Prodotto).filter(Prodotto.seriale == nuovo_seriale).first():
                errori.append(f"Seriale {nuovo_seriale} già esistente nel database")
                seriali_duplicati += 1
                continue
            
            # Aggiorna il prodotto
            prodotto = db.query(Prodotto).filter(Prodotto.id == int(prodotto_id)).first()
            if prodotto and not prodotto.seriale:  # Solo se non ha già un seriale
                prodotto.seriale = nuovo_seriale
                seriali_inseriti += 1
                
        except Exception as e:
            errori.append(f"Errore prodotto ID {prodotto_id}: {str(e)}")
    
    try:
        db.commit()
        
        # Redirect con messaggio di successo
        if seriali_inseriti > 0:
            return RedirectResponse(
                url=f"/da-gestire?seriali_inserted={seriali_inseriti}", 
                status_code=303
            )
        else:
            return RedirectResponse(
                url=f"/da-gestire?errori={len(errori)}", 
                status_code=303
            )
            
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore nel salvataggio: {str(e)}")

@app.post("/da-gestire/inserisci-seriali-multipli", response_class=RedirectResponse)
async def redirect_to_seriali_multipli():
    """Redirect POST to GET per il form seriali multipli"""
    return RedirectResponse(url="/da-gestire/inserisci-seriali-multipli", status_code=303)

@app.get("/problemi", response_class=HTMLResponse)
async def problemi(request: Request, db: Session = Depends(get_db)):
    """Pagina Problemi - vendite lente e margini critici"""
    
    now = datetime.now()
    
    # Vendite lente: prodotti in stock da più di 30 giorni
    vendite_lente = []
    
    # Query per prodotti non venduti con acquisti arrivati
    prodotti_in_stock = db.query(Prodotto).filter(
        ~Prodotto.vendite.any(),  # Non venduti
        Prodotto.acquisto.has(Acquisto.data_consegna.isnot(None))  # Acquisto arrivato
    ).options(joinedload(Prodotto.acquisto)).all()
    
    for prodotto in prodotti_in_stock:
        giorni_stock = (now.date() - prodotto.acquisto.data_consegna).days
        if giorni_stock > 30:
            # Calcola costo unitario
            costo_unitario = prodotto.acquisto.costo_totale / prodotto.acquisto.numero_prodotti
            
            vendite_lente.append({
                'prodotto': prodotto,
                'acquisto': prodotto.acquisto,
                'giorni_stock': giorni_stock,
                'costo_unitario': costo_unitario
            })
    
    # Margini critici: acquisti con marginalità < 25% (solo vendite complete o parziali)
    margini_critici = []
    
    # Query per acquisti con almeno una vendita
    acquisti_con_vendite = db.query(Acquisto).filter(
        Acquisto.prodotti.any(Prodotto.vendite.any())
    ).options(
        joinedload(Acquisto.prodotti).joinedload(Prodotto.vendite)
    ).all()
    
    for acquisto in acquisti_con_vendite:
        # Filtra solo prodotti business (non fotorip)
        prodotti_business = [p for p in acquisto.prodotti 
                           if not any(v.canale_vendita == "RIPARAZIONI" for v in p.vendite)]
        
        if not prodotti_business:
            continue
            
        prodotti_totali = len(prodotti_business)
        prodotti_venduti = len([p for p in prodotti_business if p.vendite])
        
        # Calcola ricavi (solo da prodotti business)
        ricavi_business = sum(
            sum(v.ricavo_netto for v in p.vendite if v.canale_vendita != "RIPARAZIONI") 
            for p in prodotti_business if p.vendite
        )
        
        # Calcola investimento proporzionale (solo parte business)
        costo_per_prodotto = acquisto.costo_totale / len(acquisto.prodotti)
        investimento_business = costo_per_prodotto * prodotti_totali
        
        margine = ricavi_business - investimento_business
        margine_percentuale = (margine / investimento_business * 100) if investimento_business > 0 else 0
        
        if margine_percentuale < 25:
            margini_critici.append({
                'acquisto': acquisto,
                'prodotti_totali': prodotti_totali,
                'prodotti_venduti': prodotti_venduti,
                'vendita_completa': prodotti_venduti == prodotti_totali,
                'investimento': investimento_business,
                'ricavi': ricavi_business,
                'margine': margine,
                'margine_percentuale': margine_percentuale
            })
    
    # Ordina per gravità 
    vendite_lente.sort(key=lambda x: x['giorni_stock'], reverse=True)
    margini_critici.sort(key=lambda x: x['margine_percentuale'])
    
    problemi_count = len(vendite_lente) + len(margini_critici)
    
    return templates.TemplateResponse("problemi.html", {
        "request": request,
        "vendite_lente": vendite_lente,
        "margini_critici": margini_critici,
        "problemi_count": problemi_count
    })

@app.get("/health")
async def health_check():
    """Health check per Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)