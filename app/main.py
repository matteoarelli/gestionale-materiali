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

from app.database import get_db, engine, Base
from app.models.models import Acquisto, Vendita, Prodotto
from app.routers import acquisti

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
        
        if not descrizione:  # Solo descrizione è obbligatoria
            continue
            
        # Verifica seriale univoco (solo se fornito)
        if seriale and db.query(Prodotto).filter(Prodotto.seriale == seriale).first():
            raise HTTPException(status_code=400, detail=f"Seriale {seriale} già esistente")
        
        nuovo_prodotto = Prodotto(
            acquisto_id=nuovo_acquisto.id,
            seriale=seriale if seriale else None,
            prodotto_descrizione=descrizione,
            note_prodotto=note_prodotto if note_prodotto else None
        )
        
        db.add(nuovo_prodotto)
    
    db.commit()
    
    return RedirectResponse(url="/acquisti", status_code=303)

@app.get("/acquisti/{acquisto_id}/seriali", response_class=HTMLResponse)
async def inserisci_seriali_form(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Form per inserire seriali mancanti"""
    
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    return templates.TemplateResponse("inserisci_seriali.html", {
        "request": request,
        "acquisto": acquisto
    })

@app.post("/acquisti/{acquisto_id}/seriali")
async def salva_seriali(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Salva i seriali inseriti"""
    
    acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    form_data = await request.form()
    
    # Raccogli i dati dei seriali
    prodotti_data = {}
    for key, value in form_data.items():
        if key.startswith('prodotti[') and value.strip():
            import re
            match = re.match(r'prodotti\[(\d+)\]\[(\w+)\]', key)
            if match:
                index = int(match.group(1))
                field = match.group(2)
                
                if index not in prodotti_data:
                    prodotti_data[index] = {}
                prodotti_data[index][field] = value.strip()
    
    # Aggiorna i seriali
    seriali_inseriti = 0
    for index, prodotto_info in prodotti_data.items():
        prodotto_id = prodotto_info.get('id')
        nuovo_seriale = prodotto_info.get('seriale', '').strip()
        
        if not prodotto_id or not nuovo_seriale:
            continue
            
        # Verifica che il seriale non esista già
        if db.query(Prodotto).filter(Prodotto.seriale == nuovo_seriale).first():
            raise HTTPException(status_code=400, detail=f"Seriale {nuovo_seriale} già esistente")
        
        # Aggiorna il prodotto
        prodotto = db.query(Prodotto).filter(Prodotto.id == int(prodotto_id)).first()
        if prodotto and not prodotto.seriale:  # Solo se non ha già un seriale
            prodotto.seriale = nuovo_seriale
            seriali_inseriti += 1
    
    db.commit()
    
    # Redirect con messaggio di successo
    if seriali_inseriti > 0:
        return RedirectResponse(url="/acquisti?seriali_inserted=1", status_code=303)
    else:
        return RedirectResponse(url="/acquisti", status_code=303)

@app.get("/acquisti/{acquisto_id}/modifica", response_class=HTMLResponse)
async def modifica_acquisto_form(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Form per modificare un acquisto"""
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    return templates.TemplateResponse("modifica_acquisto.html", {
        "request": request,
        "acquisto": acquisto
    })

@app.post("/acquisti/{acquisto_id}/modifica")
async def salva_modifica_acquisto(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Salva le modifiche di un acquisto"""
    
    acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    form_data = await request.form()
    
    # Aggiorna dati generali acquisto
    nuovo_id = form_data.get("id_acquisto_univoco", "").strip()
    if nuovo_id != acquisto.id_acquisto_univoco:
        # Verifica che il nuovo ID non esista già
        if db.query(Acquisto).filter(Acquisto.id_acquisto_univoco == nuovo_id, Acquisto.id != acquisto_id).first():
            raise HTTPException(status_code=400, detail="ID acquisto già esistente")
        acquisto.id_acquisto_univoco = nuovo_id
    
    acquisto.dove_acquistato = form_data.get("dove_acquistato", "").strip()
    acquisto.venditore = form_data.get("venditore", "").strip()
    acquisto.costo_acquisto = float(form_data.get("costo_acquisto", 0))
    acquisto.costi_accessori = float(form_data.get("costi_accessori", 0))
    acquisto.note = form_data.get("note", "").strip() or None
    
    # Gestisci date
    data_pagamento = form_data.get("data_pagamento", "").strip()
    if data_pagamento:
        try:
            acquisto.data_pagamento = datetime.strptime(data_pagamento, "%Y-%m-%d").date()
        except:
            pass
    else:
        acquisto.data_pagamento = None
        
    data_consegna = form_data.get("data_consegna", "").strip()
    if data_consegna:
        try:
            acquisto.data_consegna = datetime.strptime(data_consegna, "%Y-%m-%d").date()
        except:
            pass
    else:
        acquisto.data_consegna = None
    
    # Gestisci prodotti
    prodotti_data = {}
    
    # Raccogli tutti i prodotti esistenti per vedere quali eliminare
    prodotti_esistenti = {p.id: p for p in acquisto.prodotti}
    
    for key, value in form_data.items():
        if key.startswith('prodotti[') and value.strip():
            import re
            match = re.match(r'prodotti\[(\d+)\]\[(\w+)\]', key)
            if match:
                index = int(match.group(1))
                field = match.group(2)
                
                if index not in prodotti_data:
                    prodotti_data[index] = {}
                prodotti_data[index][field] = value.strip()
    
    # Aggiorna/crea prodotti
    prodotti_modificati = set()
    
    for index, prodotto_info in prodotti_data.items():
        prodotto_id = prodotto_info.get('id')
        seriale = prodotto_info.get('seriale', '').strip()
        descrizione = prodotto_info.get('descrizione', '').strip()
        note_prodotto = prodotto_info.get('note', '').strip()
        
        if not descrizione:
            continue
        
        if prodotto_id and prodotto_id.isdigit():
            # Prodotto esistente - aggiorna
            prodotto_id = int(prodotto_id)
            prodotto = db.query(Prodotto).filter(Prodotto.id == prodotto_id).first()
            if prodotto and not prodotto.venduto:  # Non modificare se già venduto
                # Verifica seriale univoco (escluso questo prodotto)
                if seriale and db.query(Prodotto).filter(Prodotto.seriale == seriale, Prodotto.id != prodotto_id).first():
                    raise HTTPException(status_code=400, detail=f"Seriale {seriale} già esistente")
                
                prodotto.seriale = seriale if seriale else None
                prodotto.prodotto_descrizione = descrizione
                prodotto.note_prodotto = note_prodotto if note_prodotto else None
                prodotti_modificati.add(prodotto_id)
        else:
            # Nuovo prodotto
            if seriale and db.query(Prodotto).filter(Prodotto.seriale == seriale).first():
                raise HTTPException(status_code=400, detail=f"Seriale {seriale} già esistente")
            
            nuovo_prodotto = Prodotto(
                acquisto_id=acquisto.id,
                seriale=seriale if seriale else None,
                prodotto_descrizione=descrizione,
                note_prodotto=note_prodotto if note_prodotto else None
            )
            db.add(nuovo_prodotto)
    
    # Elimina prodotti non più presenti (solo se non venduti)
    for prodotto_id, prodotto in prodotti_esistenti.items():
        if prodotto_id not in prodotti_modificati and not prodotto.venduto:
            db.delete(prodotto)
    
    db.commit()
    
    return RedirectResponse(url="/acquisti", status_code=303)

@app.get("/vendite", response_class=HTMLResponse)
async def lista_vendite(request: Request, db: Session = Depends(get_db)):
    """Pagina lista vendite"""
    vendite = db.query(Vendita).options(joinedload(Vendita.prodotto)).order_by(Vendita.created_at.desc()).all()
    return templates.TemplateResponse("vendite.html", {
        "request": request,
        "vendite": vendite
    })

@app.get("/performance", response_class=HTMLResponse)
async def performance_dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard performance acquisti - analisi 30 giorni + 25% margine"""
    
    # Ottieni tutti gli acquisti con prodotti e vendite
    acquisti = db.query(Acquisto).options(
        joinedload(Acquisto.prodotti).joinedload(Prodotto.vendite)
    ).filter(Acquisto.data_consegna.isnot(None)).all()  # Solo acquisti arrivati
    
    performance_data = []
    
    for acquisto in acquisti:
        if not acquisto.prodotti:
            continue
            
        # Calcola performance per questo acquisto
        prodotti_totali = len(acquisto.prodotti)
        prodotti_venduti = len([p for p in acquisto.prodotti if p.vendite])
        
        # Ricavi totali
        ricavi_totali = sum(
            sum(v.ricavo_netto for v in p.vendite) 
            for p in acquisto.prodotti if p.vendite
        )
        
        # Marginalità
        costo_totale = acquisto.costo_totale
        margine = ricavi_totali - costo_totale
        margine_percentuale = (margine / costo_totale * 100) if costo_totale > 0 else 0
        
        # Tempo di vendita (giorni dall'arrivo alla vendita)
        giorni_vendita = None
        vendita_completa = prodotti_venduti == prodotti_totali
        
        if vendita_completa and acquisto.data_consegna:
            # Trova la data dell'ultima vendita
            date_vendite = []
            for prodotto in acquisto.prodotti:
                for vendita in prodotto.vendite:
                    date_vendite.append(vendita.data_vendita)
            
            if date_vendite:
                ultima_vendita = max(date_vendite)
                giorni_vendita = (ultima_vendita - acquisto.data_consegna).days
        
        # Classificazione performance
        performance_issues = []
        
        if not vendita_completa:
            performance_issues.append(f"Vendita parziale ({prodotti_venduti}/{prodotti_totali})")
        elif giorni_vendita and giorni_vendita > 30:
            performance_issues.append(f"Vendita lenta ({giorni_vendita} giorni)")
        
        if margine_percentuale < 25:
            performance_issues.append(f"Margine basso ({margine_percentuale:.1f}%)")
        
        performance_status = "OK" if not performance_issues else "PROBLEMI"
        
        performance_data.append({
            "acquisto": acquisto,
            "prodotti_totali": prodotti_totali,
            "prodotti_venduti": prodotti_venduti,
            "vendita_completa": vendita_completa,
            "ricavi_totali": ricavi_totali,
            "margine": margine,
            "margine_percentuale": margine_percentuale,
            "giorni_vendita": giorni_vendita,
            "performance_status": performance_status,
            "performance_issues": performance_issues
        })
    
    # Ordina per problemi prima
    performance_data.sort(key=lambda x: (x["performance_status"] != "PROBLEMI", x["margine_percentuale"]))
    
    # Statistiche generali
    total_acquisti = len(performance_data)
    acquisti_ok = len([p for p in performance_data if p["performance_status"] == "OK"])
    acquisti_problemi = total_acquisti - acquisti_ok
    
    margine_medio = sum(p["margine_percentuale"] for p in performance_data) / total_acquisti if total_acquisti > 0 else 0
    
    stats = {
        "total_acquisti": total_acquisti,
        "acquisti_ok": acquisti_ok,
        "acquisti_problemi": acquisti_problemi,
        "percentuale_ok": (acquisti_ok / total_acquisti * 100) if total_acquisti > 0 else 0,
        "margine_medio": margine_medio
    }
    
    return templates.TemplateResponse("performance.html", {
        "request": request,
        "performance_data": performance_data,
        "stats": stats
    })

@app.get("/statistiche", response_class=HTMLResponse)
async def statistiche_periodiche(request: Request, db: Session = Depends(get_db)):
    """Statistiche per periodo (settimana/mese)"""
    
    periodo = request.query_params.get("periodo", "mese")  # mese o settimana
    
    # Query base per acquisti con vendite
    query = db.query(Acquisto).options(
        joinedload(Acquisto.prodotti).joinedload(Prodotto.vendite)
    ).filter(Acquisto.data_consegna.isnot(None))
    
    acquisti = query.all()
    
    # Raggruppa per periodo
    periodi = {}
    
    for acquisto in acquisti:
        if not acquisto.data_consegna:
            continue
            
        # Determina chiave periodo
        if periodo == "settimana":
            # Settimana ISO
            year, week, _ = acquisto.data_consegna.isocalendar()
            periodo_key = f"{year}-W{week:02d}"
            periodo_label = f"Settimana {week}/{year}"
        else:
            # Mese
            periodo_key = acquisto.data_consegna.strftime("%Y-%m")
            periodo_label = acquisto.data_consegna.strftime("%B %Y")
        
        if periodo_key not in periodi:
            periodi[periodo_key] = {
                "label": periodo_label,
                "acquisti": [],
                "investimento": 0,
                "ricavi": 0,
                "margine": 0,
                "count": 0
            }
        
        # Calcola metriche
        ricavi_acquisto = sum(
            sum(v.ricavo_netto for v in p.vendite) 
            for p in acquisto.prodotti if p.vendite
        )
        
        periodi[periodo_key]["acquisti"].append(acquisto)
        periodi[periodo_key]["investimento"] += acquisto.costo_totale
        periodi[periodo_key]["ricavi"] += ricavi_acquisto
        periodi[periodo_key]["margine"] += ricavi_acquisto - acquisto.costo_totale
        periodi[periodo_key]["count"] += 1
    
    # Converti in lista e calcola percentuali
    statistiche_lista = []
    for key, data in sorted(periodi.items(), reverse=True):
        margine_perc = (data["margine"] / data["investimento"] * 100) if data["investimento"] > 0 else 0
        
        statistiche_lista.append({
            "periodo": data["label"],
            "count": data["count"],
            "investimento": data["investimento"],
            "ricavi": data["ricavi"],
            "margine": data["margine"],
            "margine_percentuale": margine_perc,
            "acquisti": data["acquisti"]
        })
    
    return templates.TemplateResponse("statistiche.html", {
        "request": request,
        "statistiche": statistiche_lista,
        "periodo_selezionato": periodo
    })

@app.get("/api/acquisti/{acquisto_id}")
async def get_acquisto_dettaglio(acquisto_id: int, db: Session = Depends(get_db)):
    """API per ottenere dettagli completi di un acquisto"""
    # Carica l'acquisto con i prodotti usando joinedload
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    try:
        # Forza il caricamento dei prodotti
        prodotti_list = []
        for p in acquisto.prodotti:
            prodotti_list.append({
                "id": p.id,
                "seriale": p.seriale or "",
                "prodotto_descrizione": p.prodotto_descrizione,
                "note_prodotto": p.note_prodotto or "",
                "venduto": p.venduto,
                "ricavo_vendita": float(p.ricavo_vendita) if p.ricavo_vendita else 0.0
            })
        
        result = {
            "id": acquisto.id,
            "id_acquisto_univoco": acquisto.id_acquisto_univoco,
            "dove_acquistato": acquisto.dove_acquistato,
            "venditore": acquisto.venditore,
            "costo_acquisto": float(acquisto.costo_acquisto),
            "costi_accessori": float(acquisto.costi_accessori or 0),
            "costo_totale": acquisto.costo_totale,
            "data_pagamento": acquisto.data_pagamento.strftime('%d/%m/%Y') if acquisto.data_pagamento else None,
            "data_consegna": acquisto.data_consegna.strftime('%d/%m/%Y') if acquisto.data_consegna else None,
            "note": acquisto.note or "",
            "created_at": acquisto.created_at.strftime('%d/%m/%Y %H:%M'),
            "prodotti": prodotti_list
        }
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nel recupero dati: {str(e)}")

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
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
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

# ================================================================
# API ENDPOINTS PER SCRIPT LOCALE
# ================================================================

@app.post("/api/sync/acquisti")
async def ricevi_acquisti_da_script(request: Request, db: Session = Depends(get_db)):
    """API per ricevere acquisti dallo script locale Excel"""
    try:
        data = await request.json()
        
        # Verifica token di sicurezza
        if data.get("token") != "sync_token_2024":
            raise HTTPException(status_code=401, detail="Token non valido")
        
        acquisti_data = data.get("acquisti", [])
        risultati = {
            "acquisti_inseriti": 0,
            "prodotti_inseriti": 0,
            "prodotti_fotorip_venduti": 0,
            "acquisti_aggiornati": 0,
            "errori": []
        }
        
        for acquisto_info in acquisti_data:
            try:
                # Verifica se acquisto esiste già
                id_univoco = acquisto_info.get("id_acquisto_univoco")
                acquisto_esistente = db.query(Acquisto).filter(
                    Acquisto.id_acquisto_univoco == id_univoco
                ).first()
                
                if acquisto_esistente:
                    risultati["acquisti_aggiornati"] += 1
                    continue
                
                # Parse delle date
                data_pagamento = None
                data_consegna = None
                
                if acquisto_info.get("data_pagamento"):
                    try:
                        data_pagamento = datetime.strptime(
                            acquisto_info["data_pagamento"], "%Y-%m-%d"
                        ).date()
                    except:
                        pass
                
                if acquisto_info.get("data_consegna"):
                    try:
                        data_consegna = datetime.strptime(
                            acquisto_info["data_consegna"], "%Y-%m-%d"
                        ).date()
                    except:
                        pass
                
                # Crea nuovo acquisto
                nuovo_acquisto = Acquisto(
                    id_acquisto_univoco=id_univoco,
                    dove_acquistato=acquisto_info.get("dove_acquistato", ""),
                    venditore=acquisto_info.get("venditore", ""),
                    costo_acquisto=float(acquisto_info.get("costo_acquisto", 0)),
                    costi_accessori=float(acquisto_info.get("costi_accessori", 0)),
                    data_pagamento=data_pagamento,
                    data_consegna=data_consegna,
                    note=acquisto_info.get("note"),
                    # Imposta created_at alla data di consegna se disponibile per acquisti storici
                    created_at=data_consegna if data_consegna else datetime.now()
                )
                
                db.add(nuovo_acquisto)
                db.flush()  # Per ottenere l'ID
                
                # Crea i prodotti
                prodotti_info = acquisto_info.get("prodotti", [])
                for prodotto_info in prodotti_info:
                    seriale = prodotto_info.get("seriale")
                    descrizione = prodotto_info.get("descrizione", "")
                    note = prodotto_info.get("note")
                    is_fotorip = prodotto_info.get("is_fotorip", False)
                    
                    if not descrizione:
                        continue
                    
                    # Verifica seriale univoco (solo se fornito e non è fotorip)
                    if seriale and not is_fotorip:
                        if db.query(Prodotto).filter(Prodotto.seriale == seriale).first():
                            risultati["errori"].append(f"Seriale {seriale} già esistente")
                            continue
                    
                    nuovo_prodotto = Prodotto(
                        acquisto_id=nuovo_acquisto.id,
                        seriale=seriale,
                        prodotto_descrizione=descrizione,
                        note_prodotto=note
                    )
                    
                    db.add(nuovo_prodotto)
                    risultati["prodotti_inseriti"] += 1
                    
                    # Se è fotorip, crea subito una vendita fittizia
                    if is_fotorip:
                        db.flush()  # Per ottenere l'ID del prodotto
                        
                        # Per fotorip: prezzo vendita = costo totale (acquisto + accessori) per margine neutro
                        costo_totale_acquisto = float(acquisto_info.get("costo_acquisto", 0)) + float(acquisto_info.get("costi_accessori", 0))
                        
                        vendita_fotorip = Vendita(
                            prodotto_id=nuovo_prodotto.id,
                            data_vendita=data_consegna if data_consegna else date.today(),
                            canale_vendita="RIPARAZIONI",
                            prezzo_vendita=costo_totale_acquisto,  # Costo totale per margine neutro
                            commissioni=0.0,
                            synced_from_invoicex=False,
                            invoicex_id=f"FOTORIP_{nuovo_prodotto.id}",
                            note_vendita="Prodotto utilizzato per riparazioni - margine neutro - importato da Excel"
                        )
                        
                        db.add(vendita_fotorip)
                        risultati["prodotti_fotorip_venduti"] += 1
                
                risultati["acquisti_inseriti"] += 1
                
            except Exception as e:
                risultati["errori"].append(f"Errore acquisto {acquisto_info.get('id_acquisto_univoco', 'unknown')}: {str(e)}")
        
        db.commit()
        
        return {
            "status": "success",
            "message": f"Processati {len(acquisti_data)} acquisti",
            "risultati": risultati
        }
        
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.post("/api/sync/vendite")
async def ricevi_vendite_da_script(request: Request, db: Session = Depends(get_db)):
    """API per ricevere vendite dallo script locale"""
    try:
        data = await request.json()
        
        # Verifica token di sicurezza semplice
        if data.get("token") != "sync_token_2024":
            raise HTTPException(status_code=401, detail="Token non valido")
        
        vendite_data = data.get("vendite", [])
        risultati = {
            "vendite_inserite": 0,
            "vendite_aggiornate": 0,
            "errori": []
        }
        
        for vendita in vendite_data:
            try:
                # Cerca il prodotto tramite seriale
                seriale = vendita.get("seriale")
                if not seriale:
                    risultati["errori"].append("Seriale mancante")
                    continue
                
                prodotto = db.query(Prodotto).filter(Prodotto.seriale == seriale).first()
                if not prodotto:
                    risultati["errori"].append(f"Prodotto non trovato per seriale: {seriale}")
                    continue
                
                # Verifica se vendita già esiste
                invoicex_id = str(vendita.get("id", ""))
                vendita_esistente = db.query(Vendita).filter(Vendita.invoicex_id == invoicex_id).first()
                
                if vendita_esistente:
                    risultati["vendite_aggiornate"] += 1
                    continue
                
                # Crea nuova vendita
                nuova_vendita = Vendita(
                    prodotto_id=prodotto.id,
                    data_vendita=datetime.strptime(vendita.get("data_vendita"), "%Y-%m-%d").date(),
                    canale_vendita=vendita.get("canale_vendita", "unknown"),
                    prezzo_vendita=float(vendita.get("prezzo_vendita", 0)),
                    commissioni=float(vendita.get("commissioni", 0)),
                    synced_from_invoicex=True,
                    invoicex_id=invoicex_id,
                    note_vendita=vendita.get("note")
                )
                
                db.add(nuova_vendita)
                risultati["vendite_inserite"] += 1
                
            except Exception as e:
                risultati["errori"].append(f"Errore vendita {vendita.get('id', 'unknown')}: {str(e)}")
        
        db.commit()
        return {
            "status": "success",
            "message": f"Processate {len(vendite_data)} vendite",
            "risultati": risultati
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/sync/prodotti-senza-vendite")
async def get_prodotti_per_sync(db: Session = Depends(get_db)):
    """API per ottenere lista prodotti con seriali per lo script"""
    try:
        prodotti = db.query(Prodotto).filter(
            Prodotto.seriale.isnot(None),  # Solo prodotti con seriale
            ~Prodotto.vendite.any()  # Che non hanno vendite
        ).all()
        
        prodotti_data = []
        for p in prodotti:
            prodotti_data.append({
                "id": p.id,
                "seriale": p.seriale,
                "descrizione": p.prodotto_descrizione,
                "acquisto_id": p.acquisto.id_acquisto_univoco if p.acquisto else None
            })
        
        return {
            "status": "success",
            "prodotti": prodotti_data,
            "count": len(prodotti_data)
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check per Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)