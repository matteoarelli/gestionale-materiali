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

@app.get("/da-gestire", response_class=HTMLResponse)
async def da_gestire(request: Request, db: Session = Depends(get_db)):
    """Pagina Da Gestire - elementi che richiedono attenzione"""
    
    # Prodotti senza seriali (solo quelli non venduti)
    prodotti_senza_seriali = db.query(Prodotto).filter(
        Prodotto.seriale.is_(None),
        ~Prodotto.vendite.any()  # Non venduti
    ).options(joinedload(Prodotto.acquisto)).all()
    
    # Acquisti non ancora arrivati
    acquisti_non_arrivati = db.query(Acquisto).filter(
        Acquisto.data_consegna.is_(None)
    ).options(joinedload(Acquisto.prodotti)).all()
    
    # Calcola giorni di attesa per acquisti non arrivati
    now = datetime.now()
    for acquisto in acquisti_non_arrivati:
        if acquisto.data_pagamento:
            acquisto.giorni_attesa = (now.date() - acquisto.data_pagamento).days
        else:
            acquisto.giorni_attesa = (now.date() - acquisto.created_at.date()).days
    
    return templates.TemplateResponse("da_gestire.html", {
        "request": request,
        "prodotti_senza_seriali": prodotti_senza_seriali,
        "acquisti_non_arrivati": acquisti_non_arrivati,
        "now": now
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

def _calcola_metriche_acquisto(acquisto, now):
    """Calcola metriche aggiuntive per un acquisto"""
    
    # Prodotti senza seriali
    acquisto.prodotti_senza_seriali = len([p for p in acquisto.prodotti if not p.seriale])
    
    # Giorni in stock/attesa
    if acquisto.data_consegna:
        acquisto.giorni_stock = (now.date() - acquisto.data_consegna).days
        acquisto.giorni_attesa = None
    else:
        acquisto.giorni_stock = None
        if acquisto.data_pagamento:
            acquisto.giorni_attesa = (now.date() - acquisto.data_pagamento).days
        else:
            acquisto.giorni_attesa = (now.date() - acquisto.created_at.date()).days
    
    # Score di urgenza (0-100)
    urgenza_score = 0
    
    # Penalità per non arrivato
    if not acquisto.data_consegna and hasattr(acquisto, 'giorni_attesa'):
        if acquisto.giorni_attesa > 21:
            urgenza_score += 40
        elif acquisto.giorni_attesa > 14:
            urgenza_score += 30
        elif acquisto.giorni_attesa > 7:
            urgenza_score += 20
    
    # Penalità per seriali mancanti
    if acquisto.prodotti_senza_seriali > 0:
        urgenza_score += min(30, acquisto.prodotti_senza_seriali * 10)
    
    # Penalità per vendite lente
    if acquisto.giorni_stock and acquisto.giorni_stock > 30:
        prodotti_non_venduti = len([p for p in acquisto.prodotti if not p.vendite])
        if prodotti_non_venduti > 0:
            urgenza_score += min(30, (acquisto.giorni_stock - 30) // 15 * 10)
    
    acquisto.urgenza_score = min(100, urgenza_score)
    
    # Lista problemi testuali
    problemi = []
    if not acquisto.data_consegna:
        problemi.append("Non arrivato")
    if acquisto.prodotti_senza_seriali > 0:
        problemi.append(f"{acquisto.prodotti_senza_seriali} senza seriali")
    if acquisto.giorni_stock:
        if acquisto.giorni_stock > 60 and not acquisto.completamente_venduto:
            problemi.append("Vendita molto lenta")
        elif acquisto.giorni_stock > 30 and not acquisto.completamente_venduto:
            problemi.append("Vendita lenta")
    
    acquisto.problemi_list = problemi
    acquisto.problematico = len(problemi) > 0
    
    # Performance score (se ha vendite)
    if acquisto.prodotti_venduti > 0:
        performance_score = 50  # Base
        
        # Marginalità
        if acquisto.margine_totale > 0:
            margine_perc = (acquisto.margine_totale / acquisto.costo_totale * 100)
            if margine_perc >= 25:
                performance_score += 30
            elif margine_perc >= 15:
                performance_score += 20
            elif margine_perc >= 5:
                performance_score += 10
            else:
                performance_score -= 10
        
        # Velocità di vendita
        if acquisto.completamente_venduto and acquisto.giorni_stock:
            if acquisto.giorni_stock <= 30:
                performance_score += 20
            elif acquisto.giorni_stock <= 60:
                performance_score += 10
            else:
                performance_score -= 10
        
        acquisto.performance_score = max(0, min(100, performance_score))
    else:
        acquisto.performance_score = None

@app.get("/acquisti", response_class=HTMLResponse)
async def lista_acquisti(request: Request, db: Session = Depends(get_db)):
    """Pagina lista acquisti con filtri avanzati e ordinamento"""
    
    # Parametri di filtro dalla query string
    filtro_stato = request.query_params.get("filtro_stato", "tutti")
    ordinamento = request.query_params.get("ordinamento", "data_desc") 
    cerca = request.query_params.get("cerca", "")
    
    # Query base con eager loading
    query = db.query(Acquisto).options(
        joinedload(Acquisto.prodotti).joinedload(Prodotto.vendite)
    )
    
    # Conta totali per statistiche
    acquisti_totali = query.count()
    
    # Applica filtri di ricerca
    if cerca:
        query = query.filter(
            or_(
                Acquisto.id_acquisto_univoco.ilike(f"%{cerca}%"),
                Acquisto.venditore.ilike(f"%{cerca}%"),  
                Acquisto.dove_acquistato.ilike(f"%{cerca}%"),
                Acquisto.prodotti.any(Prodotto.prodotto_descrizione.ilike(f"%{cerca}%"))
            )
        )
    
    # Applica filtri di stato
    if filtro_stato == "in_stock":
        # Acquisti con prodotti non venduti
        query = query.filter(
            Acquisto.prodotti.any(~Prodotto.vendite.any())
        )
    elif filtro_stato == "venduti":
        # Acquisti completamente venduti
        query = query.filter(
            ~Acquisto.prodotti.any(~Prodotto.vendite.any())
        )
    elif filtro_stato == "parziali":  
        # Vendite parziali (almeno uno venduto E almeno uno non venduto)
        query = query.filter(
            and_(
                Acquisto.prodotti.any(Prodotto.vendite.any()),
                Acquisto.prodotti.any(~Prodotto.vendite.any())
            )
        )
    elif filtro_stato == "senza_seriali":
        # Acquisti con prodotti senza seriali
        query = query.filter(
            Acquisto.prodotti.any(Prodotto.seriale.is_(None))
        )
    elif filtro_stato == "non_arrivati":
        # Acquisti senza data di consegna
        query = query.filter(Acquisto.data_consegna.is_(None))
    elif filtro_stato == "problematici":
        # Acquisti con vari problemi
        query = query.filter(
            or_(
                # Senza seriali
                Acquisto.prodotti.any(Prodotto.seriale.is_(None)),
                # Non arrivati
                Acquisto.data_consegna.is_(None),
                # Vendite lente (arrivati da >30 giorni ma non venduti completamente)  
                and_(
                    Acquisto.data_consegna.isnot(None),
                    Acquisto.data_consegna < (date.today() - timedelta(days=30)),
                    Acquisto.prodotti.any(~Prodotto.vendite.any())
                )
            )
        )
    
    # Applica ordinamento  
    if ordinamento == "data_asc":
        query = query.order_by(Acquisto.created_at.asc())
    elif ordinamento == "costo_desc":
        query = query.order_by(
            (Acquisto.costo_acquisto + func.coalesce(Acquisto.costi_accessori, 0)).desc()
        )
    elif ordinamento == "urgenza":
        # Ordinamento per urgenza: prima problematici
        query = query.order_by(
            # Prima: non arrivati
            Acquisto.data_consegna.is_(None).desc(),
            # Poi: per data  
            Acquisto.created_at.desc()
        )
    elif ordinamento == "giorni_stock":
        # Ordinamento per giorni in stock (arrivati da più tempo prima)
        query = query.order_by(
            Acquisto.data_consegna.asc().nulls_last()
        )
    else:  # data_desc (default)
        query = query.order_by(Acquisto.created_at.desc())
    
    # Esegui query
    acquisti = query.all()
    
    # Aggiungi proprietà calcolate per ogni acquisto
    now = datetime.now()
    for acquisto in acquisti:
        # Calcola metriche aggiuntive per la UI
        _calcola_metriche_acquisto(acquisto, now)
    
    return templates.TemplateResponse("acquisti.html", {
        "request": request,
        "acquisti": acquisti,
        "acquisti_totali": acquisti_totali,
        "filtro_stato": filtro_stato,
        "ordinamento": ordinamento,  
        "cerca": cerca
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

@app.get("/vendite/{vendita_id}/modifica", response_class=HTMLResponse)
async def modifica_vendita_form(vendita_id: int, request: Request, db: Session = Depends(get_db)):
    """Form per modificare una vendita"""
    vendita = db.query(Vendita).options(joinedload(Vendita.prodotto)).filter(Vendita.id == vendita_id).first()
    if not vendita:
        raise HTTPException(status_code=404, detail="Vendita non trovata")
    
    return templates.TemplateResponse("modifica_vendita.html", {
        "request": request,
        "vendita": vendita
    })

@app.post("/vendite/{vendita_id}/modifica")
async def salva_modifica_vendita(vendita_id: int, request: Request, db: Session = Depends(get_db)):
    """Salva le modifiche di una vendita"""
    
    vendita = db.query(Vendita).filter(Vendita.id == vendita_id).first()
    if not vendita:
        raise HTTPException(status_code=404, detail="Vendita non trovata")
    
    form_data = await request.form()
    
    # Aggiorna dati vendita
    vendita.canale_vendita = form_data.get("canale_vendita", "").strip()
    vendita.prezzo_vendita = float(form_data.get("prezzo_vendita", 0))
    vendita.commissioni = float(form_data.get("commissioni", 0))
    vendita.note_vendita = form_data.get("note_vendita", "").strip() or None
    
    # Gestisci data vendita
    data_vendita = form_data.get("data_vendita", "").strip()
    if data_vendita:
        try:
            vendita.data_vendita = datetime.strptime(data_vendita, "%Y-%m-%d").date()
        except:
            pass
    
    db.commit()
    
    return RedirectResponse(url="/vendite", status_code=303)

@app.delete("/vendite/{vendita_id}")
async def elimina_vendita(vendita_id: int, db: Session = Depends(get_db)):
    """Elimina una vendita"""
    vendita = db.query(Vendita).filter(Vendita.id == vendita_id).first()
    if not vendita:
        raise HTTPException(status_code=404, detail="Vendita non trovata")
    
    db.delete(vendita)
    db.commit()
    
    return {"message": "Vendita eliminata con successo"}

@app.get("/performance", response_class=HTMLResponse)
async def performance_dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard performance acquisti - analisi 30 giorni + 25% margine"""
    
    # Ottieni tutti gli acquisti con prodotti e vendite, ESCLUSI i fotorip
    acquisti = db.query(Acquisto).options(
        joinedload(Acquisto.prodotti).joinedload(Prodotto.vendite)
    ).filter(
        Acquisto.data_consegna.isnot(None),  # Solo acquisti arrivati
        ~Acquisto.prodotti.any(  # Escludi acquisti che contengono prodotti fotorip
            Prodotto.vendite.any(Vendita.canale_vendita == "RIPARAZIONI")
        )
    ).all()
    
    performance_data = []
    
    for acquisto in acquisti:
        # Filtra solo prodotti NON fotorip per i calcoli
        prodotti_business = [p for p in acquisto.prodotti 
                           if not any(v.canale_vendita == "RIPARAZIONI" for v in p.vendite)]
        
        if not prodotti_business:
            continue  # Salta acquisti che sono solo fotorip
            
        # Calcola performance per questo acquisto (solo prodotti business)
        prodotti_totali = len(prodotti_business)
        prodotti_venduti = len([p for p in prodotti_business if p.vendite])
        
        # Ricavi totali (solo da prodotti business)
        ricavi_totali = sum(
            sum(v.ricavo_netto for v in p.vendite if v.canale_vendita != "RIPARAZIONI") 
            for p in prodotti_business if p.vendite
        )
        
        # Marginalità (costo diviso per prodotti business, non totali)
        costo_per_prodotto = acquisto.costo_totale / len(acquisto.prodotti)  # Costo unitario originale
        costo_business = costo_per_prodotto * prodotti_totali  # Costo solo prodotti business
        margine = ricavi_totali - costo_business
        margine_percentuale = (margine / costo_business * 100) if costo_business > 0 else 0
        
        # Tempo di vendita (giorni dall'arrivo alla vendita) - solo prodotti business
        giorni_vendita = None
        vendita_completa = prodotti_venduti == prodotti_totali
        
        if vendita_completa and acquisto.data_consegna:
            # Trova la data dell'ultima vendita (escluse riparazioni)
            date_vendite = []
            for prodotto in prodotti_business:
                for vendita in prodotto.vendite:
                    if vendita.canale_vendita != "RIPARAZIONI":
                        date_vendite.append(vendita.data_vendita)
            
            if date_vendite:
                ultima_vendita = max(date_vendite)
                giorni_vendita = (ultima_vendita - acquisto.data_consegna).days
        
        # Classificazione performance (solo per prodotti business)
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
            "prodotti_totali": prodotti_totali,  # Solo business
            "prodotti_venduti": prodotti_venduti,  # Solo business
            "vendita_completa": vendita_completa,
            "ricavi_totali": ricavi_totali,
            "margine": margine,
            "margine_percentuale": margine_percentuale,
            "giorni_vendita": giorni_vendita,
            "performance_status": performance_status,
            "performance_issues": performance_issues,
            "costo_business": costo_business,  # Costo solo parte business
            "ha_fotorip": len(prodotti_business) < len(acquisto.prodotti)  # Flag per UI
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
    """Statistiche per periodo (settimana/mese) - ESCLUSI prodotti fotorip"""
    
    periodo = request.query_params.get("periodo", "mese")  # mese o settimana
    
    # Query base per acquisti con vendite, esclusi fotorip
    query = db.query(Acquisto).options(
        joinedload(Acquisto.prodotti).joinedload(Prodotto.vendite)
    ).filter(
        Acquisto.data_consegna.isnot(None),
        ~Acquisto.prodotti.any(  # Escludi acquisti che contengono solo prodotti fotorip
            Prodotto.vendite.any(Vendita.canale_vendita == "RIPARAZIONI")
        )
    )
    
    acquisti = query.all()
    
    # Raggruppa per periodo
    periodi = {}
    
    for acquisto in acquisti:
        if not acquisto.data_consegna:
            continue
        
        # Filtra solo prodotti business (non fotorip)
        prodotti_business = [p for p in acquisto.prodotti 
                           if not any(v.canale_vendita == "RIPARAZIONI" for v in p.vendite)]
        
        if not prodotti_business:
            continue  # Salta acquisti che sono solo fotorip
            
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
        
        # Calcola metriche (solo per prodotti business)
        costo_per_prodotto = acquisto.costo_totale / len(acquisto.prodotti)  # Costo unitario
        costo_business = costo_per_prodotto * len(prodotti_business)  # Costo solo business
        
        ricavi_business = sum(
            sum(v.ricavo_netto for v in p.vendite if v.canale_vendita != "RIPARAZIONI") 
            for p in prodotti_business if p.vendite
        )
        
        periodi[periodo_key]["acquisti"].append(acquisto)
        periodi[periodo_key]["investimento"] += costo_business
        periodi[periodo_key]["ricavi"] += ricavi_business
        periodi[periodo_key]["margine"] += ricavi_business - costo_business
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

@app.get("/admin/reset", response_class=HTMLResponse)
async def reset_form(request: Request):
    """Form per reset dati"""
    return """
    <html>
    <head><title>Reset Dati</title></head>
    <body style="font-family: Arial; max-width: 400px; margin: 100px auto; padding: 20px;">
        <h2>⚠️ Reset Completo Database</h2>
        <p>Questa azione cancellerà <strong>TUTTI</strong> gli acquisti, prodotti e vendite.</p>
        <form method="POST" action="/admin/reset-data" onsubmit="return confirm('Sei SICURO di voler cancellare tutto?')">
            <label>Password di conferma:</label>
            <input type="password" name="password" placeholder="Inserisci password" required>
            <br><br>
            <button type="submit" style="background: red; color: white; padding: 10px 20px; border: none; cursor: pointer;">
                🗑️ CANCELLA TUTTO
            </button>
            <a href="/" style="margin-left: 20px;">Annulla</a>
        </form>
        <p><small>Password: <code>reset2024</code></small></p>
    </body>
    </html>
    """

@app.post("/admin/reset-data")
async def reset_all_data(request: Request, db: Session = Depends(get_db)):
    """ADMIN: Cancella tutti i dati (acquisti, prodotti, vendite)"""
    try:
        # Verifica password semplice
        form_data = await request.form()
        password = form_data.get("password", "")
        
        if password != "reset2024":
            return {"status": "error", "message": "Password errata"}
        
        # Cancella tutto in ordine (vendite -> prodotti -> acquisti)
        vendite_count = db.query(Vendita).count()
        prodotti_count = db.query(Prodotto).count()  
        acquisti_count = db.query(Acquisto).count()
        
        db.query(Vendita).delete()
        db.query(Prodotto).delete()
        db.query(Acquisto).delete()
        
        db.commit()
        
        return {
            "status": "success", 
            "message": f"Cancellati: {acquisti_count} acquisti, {prodotti_count} prodotti, {vendite_count} vendite"
        }
        
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check per Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)