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

@app.post("/api/create-sale-from-purchase")
async def create_sale_from_purchase(request: Request, db: Session = Depends(get_db)):
    """API per creare vendita manuale da pagina acquisti"""
    try:
        data = await request.json()
        
        # Parametri richiesti
        prodotto_id = data.get("prodotto_id")
        canale_vendita = data.get("canale_vendita")
        prezzo_vendita = float(data.get("prezzo_vendita", 0))
        data_vendita_str = data.get("data_vendita")
        note_vendita = data.get("note_vendita", "")
        
        if not all([prodotto_id, canale_vendita, prezzo_vendita]):
            return {"success": False, "error": "Parametri mancanti"}
        
        # Trova il prodotto
        prodotto = db.query(Prodotto).filter(Prodotto.id == prodotto_id).first()
        if not prodotto:
            return {"success": False, "error": "Prodotto non trovato"}
        
        # Controllo seriali duplicati - NO SERIALI DUPLICATI
        if prodotto.vendite:
            return {"success": False, "error": f"Prodotto già venduto"}
        
        # Controllo seriale duplicato su altri prodotti
        if prodotto.seriale:
            vendita_esistente = db.query(Vendita).join(Prodotto).filter(
                Prodotto.seriale == prodotto.seriale,
                Prodotto.id != prodotto_id
            ).first()
            if vendita_esistente:
                return {"success": False, "error": f"Seriale '{prodotto.seriale}' già venduto"}
        
        # Parse data vendita
        try:
            if data_vendita_str:
                data_vendita = datetime.strptime(data_vendita_str, "%Y-%m-%d").date()
            else:
                data_vendita = date.today()
        except:
            return {"success": False, "error": "Formato data non valido"}
        
        # Calcola commissioni automaticamente
        commissioni_canali = {
            'BONIFICO BANCARIO': 0.0,
            'CARTA DI CREDITO': 0.0,
            'BACKMARKET': 0.15,
            'CDISCOUNT': 0.15,
            'CONTRASSEGNO': 0.0,
            'EBAY': 0.08,
            'PAYPAL': 0.04,
            'PERMUTA': 0.0,
            'REFURBED': 0.17,
            'SEDE-BANCOMAT': 0.0,
            'SEDE-CONTANTI': 0.0,
            'SEDE-PERMUTA': 0.0
        }
        
        commissione_percentuale = commissioni_canali.get(canale_vendita.upper(), 0.0)
        commissioni = prezzo_vendita * commissione_percentuale
        
        # Crea la vendita
        nuova_vendita = Vendita(
            prodotto_id=prodotto_id,
            data_vendita=data_vendita,
            canale_vendita=canale_vendita,
            prezzo_vendita=prezzo_vendita,
            commissioni=commissioni,
            synced_from_invoicex=False,
            invoicex_id=f"MANUAL_{prodotto_id}_{int(datetime.now().timestamp())}",
            note_vendita=note_vendita
        )
        
        db.add(nuova_vendita)
        db.commit()
        db.refresh(nuova_vendita)
        
        return {
            "success": True, 
            "message": f"Vendita creata: €{prezzo_vendita}",
            "vendita_id": nuova_vendita.id,
            "ricavo_netto": nuova_vendita.ricavo_netto,
            "commissioni_applicate": commissioni
        }
        
    except Exception as e:
        db.rollback()
        return {"success": False, "error": f"Errore: {str(e)}"}

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
    
    # Ordina per prioritÃ  (acquisti arrivati da piÃ¹ tempo prima)
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
            # Verifica che il seriale non esista giÃ  
            if db.query(Prodotto).filter(Prodotto.seriale == nuovo_seriale).first():
                errori.append(f"Seriale {nuovo_seriale} giÃ  esistente nel database")
                seriali_duplicati += 1
                continue
            
            # Aggiorna il prodotto
            prodotto = db.query(Prodotto).filter(Prodotto.id == int(prodotto_id)).first()
            if prodotto and not prodotto.seriale:  # Solo se non ha giÃ  un seriale
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
    
    # Vendite lente: prodotti in stock da piÃ¹ di 30 giorni
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
    
    # Margini critici: acquisti con marginalitÃ  < 25% (solo vendite complete o parziali)
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
    
    # Ordina per gravitÃ  
    vendite_lente.sort(key=lambda x: x['giorni_stock'], reverse=True)
    margini_critici.sort(key=lambda x: x['margine_percentuale'])
    
    problemi_count = len(vendite_lente) + len(margini_critici)
    
    return templates.TemplateResponse("problemi.html", {
        "request": request,
        "vendite_lente": vendite_lente,
        "margini_critici": margini_critici,
        "problemi_count": problemi_count
    })

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
        query = query.filter(
            Acquisto.prodotti.any(~Prodotto.vendite.any())
        )
    elif filtro_stato == "venduti":
        query = query.filter(
            ~Acquisto.prodotti.any(~Prodotto.vendite.any())
        )
    elif filtro_stato == "parziali":  
        query = query.filter(
            and_(
                Acquisto.prodotti.any(Prodotto.vendite.any()),
                Acquisto.prodotti.any(~Prodotto.vendite.any())
            )
        )
    elif filtro_stato == "senza_seriali":
        query = query.filter(
            Acquisto.prodotti.any(Prodotto.seriale.is_(None))
        )
    elif filtro_stato == "non_arrivati":
        query = query.filter(Acquisto.data_consegna.is_(None))
    elif filtro_stato == "problematici":
        query = query.filter(
            or_(
                # Prodotti senza seriali MA solo se non sono fotorip (non hanno vendite RIPARAZIONI)
                and_(
                    Acquisto.prodotti.any(
                        and_(
                            Prodotto.seriale.is_(None),
                            ~Prodotto.vendite.any(Vendita.canale_vendita == "RIPARAZIONI")
                        )
                    )
                ),
                # Acquisti non arrivati
                Acquisto.data_consegna.is_(None),
                # Prodotti in stock da più di 30 giorni (escludendo fotorip)
                and_(
                    Acquisto.data_consegna.isnot(None),
                    Acquisto.data_consegna < (date.today() - timedelta(days=30)),
                    Acquisto.prodotti.any(
                        and_(
                            ~Prodotto.vendite.any(),
                            ~Prodotto.vendite.any(Vendita.canale_vendita == "RIPARAZIONI")
                        )
                    )
                )
            )
        )
    
    # Applica ordinamento  
    if ordinamento == "data_asc":
        query = query.order_by(Acquisto.data_pagamento.asc().nulls_last(), Acquisto.created_at.asc())
    elif ordinamento == "consegna_desc":
        query = query.order_by(Acquisto.data_consegna.desc().nulls_last())
    elif ordinamento == "consegna_asc":
        query = query.order_by(Acquisto.data_consegna.asc().nulls_last())
    elif ordinamento == "costo_desc":
        query = query.order_by(
            (Acquisto.costo_acquisto + func.coalesce(Acquisto.costi_accessori, 0)).desc()
        )
    elif ordinamento == "urgenza":
        query = query.order_by(
            Acquisto.data_consegna.is_(None).desc(),
            Acquisto.created_at.desc()
        )
    elif ordinamento == "giorni_stock":
        query = query.order_by(
            Acquisto.data_consegna.asc().nulls_last()
        )
    else:  # data_desc (default)
        query = query.order_by(Acquisto.data_pagamento.desc().nulls_last(), Acquisto.created_at.desc())
    
    # Esegui query
    acquisti = query.all()
    
    return templates.TemplateResponse("acquisti.html", {
        "request": request,
        "acquisti": acquisti,
        "acquisti_totali": acquisti_totali,
        "filtro_stato": filtro_stato,
        "ordinamento": ordinamento,  
        "cerca": cerca
    })

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
        
        # MarginalitÃ  (costo diviso per prodotti business, non totali)
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

@app.get("/diagnostica", response_class=HTMLResponse)
async def diagnostica_sincronizzazione(request: Request, db: Session = Depends(get_db)):
    """Diagnostica completa problemi di sincronizzazione"""
    
    # 1. Prodotti senza seriali
    prodotti_senza_seriali = db.query(Prodotto).filter(
        or_(
            Prodotto.seriale.is_(None),
            Prodotto.seriale == "",
            Prodotto.seriale == "???",
            Prodotto.seriale == "N/A"
        )
    ).options(joinedload(Prodotto.acquisto)).all()
    
    # 2. Prodotti con seriali ma senza vendite
    prodotti_con_seriali_no_vendite = db.query(Prodotto).filter(
        Prodotto.seriale.isnot(None),
        Prodotto.seriale != "",
        Prodotto.seriale != "???",
        Prodotto.seriale != "N/A",
        ~Prodotto.vendite.any()
    ).options(joinedload(Prodotto.acquisto)).all()
    
    # 3. Seriali duplicati
    seriali_duplicati = db.query(Prodotto.seriale, func.count(Prodotto.id).label('count')).filter(
        Prodotto.seriale.isnot(None),
        Prodotto.seriale != "",
        Prodotto.seriale != "???",
        Prodotto.seriale != "N/A"
    ).group_by(Prodotto.seriale).having(func.count(Prodotto.id) > 1).all()
    
    # 4. Prodotti venduti senza seriali
    prodotti_venduti_senza_seriali = db.query(Prodotto).filter(
        or_(
            Prodotto.seriale.is_(None),
            Prodotto.seriale == "",
            Prodotto.seriale == "???",
            Prodotto.seriale == "N/A"
        ),
        Prodotto.vendite.any()
    ).options(joinedload(Prodotto.vendite)).all()
    
    # 5. Statistiche generali
    total_prodotti = db.query(Prodotto).count()
    total_vendite = db.query(Vendita).count()
    total_acquisti = db.query(Acquisto).count()
    
    prodotti_venduti = db.query(Prodotto).filter(Prodotto.vendite.any()).count()
    prodotti_in_stock = total_prodotti - prodotti_venduti
    
    # 6. Analisi seriali problematici
    seriali_problematici = []
    
    # Seriali con caratteri strani
    prodotti_seriali_strani = db.query(Prodotto).filter(
        Prodotto.seriale.isnot(None),
        or_(
            Prodotto.seriale.like("%???%"),
            Prodotto.seriale.like("%-"),
            Prodotto.seriale.like("% %"),  # Con spazi
            func.char_length(Prodotto.seriale) < 3,
            func.char_length(Prodotto.seriale) > 50
        )
    ).all()
    
    # 7. Acquisti senza prodotti
    acquisti_senza_prodotti = db.query(Acquisto).filter(
        ~Acquisto.prodotti.any()
    ).all()
    
    # 8. Vendite orfane (senza prodotto)
    vendite_orfane = db.query(Vendita).filter(
        Vendita.prodotto_id.is_(None)
    ).all()
    
    # 9. Pattern seriali comuni
    pattern_seriali = db.query(
        func.substring(Prodotto.seriale, 1, 3).label('prefisso'),
        func.count(Prodotto.id).label('count')
    ).filter(
        Prodotto.seriale.isnot(None),
        func.char_length(Prodotto.seriale) >= 3
    ).group_by(func.substring(Prodotto.seriale, 1, 3)).order_by(func.count(Prodotto.id).desc()).limit(20).all()
    
    diagnostica_data = {
        "statistiche_generali": {
            "total_prodotti": total_prodotti,
            "total_vendite": total_vendite,
            "total_acquisti": total_acquisti,
            "prodotti_venduti": prodotti_venduti,
            "prodotti_in_stock": prodotti_in_stock
        },
        "prodotti_senza_seriali": prodotti_senza_seriali,
        "prodotti_con_seriali_no_vendite": prodotti_con_seriali_no_vendite,
        "seriali_duplicati": seriali_duplicati,
        "prodotti_venduti_senza_seriali": prodotti_venduti_senza_seriali,
        "seriali_problematici": prodotti_seriali_strani,
        "acquisti_senza_prodotti": acquisti_senza_prodotti,
        "vendite_orfane": vendite_orfane,
        "pattern_seriali": pattern_seriali,
        "problemi_count": {
            "senza_seriali": len(prodotti_senza_seriali),
            "con_seriali_no_vendite": len(prodotti_con_seriali_no_vendite),
            "seriali_duplicati": len(seriali_duplicati),
            "seriali_strani": len(prodotti_seriali_strani),
            "acquisti_vuoti": len(acquisti_senza_prodotti),
            "vendite_orfane": len(vendite_orfane)
        }
    }
    
    return templates.TemplateResponse("diagnostica.html", {
        "request": request,
        "diagnostica": diagnostica_data
    })

@app.get("/acquisti/nuovo", response_class=HTMLResponse)
async def nuovo_acquisto_form(request: Request):
    """Form per creare nuovo acquisto"""
    return templates.TemplateResponse("nuovo_acquisto.html", {
        "request": request
    })

@app.post("/acquisti/nuovo")
async def crea_nuovo_acquisto(request: Request, db: Session = Depends(get_db)):
    """Crea nuovo acquisto"""
    form_data = await request.form()
    
    try:
        # Crea nuovo acquisto
        nuovo_acquisto = Acquisto(
            id_acquisto_univoco=form_data.get("id_acquisto_univoco"),
            dove_acquistato=form_data.get("dove_acquistato", ""),
            venditore=form_data.get("venditore", ""),
            costo_acquisto=float(form_data.get("costo_acquisto", 0)),
            costi_accessori=float(form_data.get("costi_accessori", 0)),
            data_pagamento=datetime.strptime(form_data.get("data_pagamento"), "%Y-%m-%d").date() if form_data.get("data_pagamento") else None,
            data_consegna=datetime.strptime(form_data.get("data_consegna"), "%Y-%m-%d").date() if form_data.get("data_consegna") else None,
            note=form_data.get("note"),
            created_at=datetime.now()
        )
        
        db.add(nuovo_acquisto)
        db.flush()
        
        # Parsea i prodotti dal formato del template: prodotti[0][seriale], prodotti[0][descrizione], etc.
        prodotti_data = {}
        for key, value in form_data.items():
            if key.startswith('prodotti['):
                # Estrai index e campo da prodotti[0][seriale] -> index=0, campo=seriale
                import re
                match = re.match(r'prodotti\[(\d+)\]\[(\w+)\]', key)
                if match:
                    index = int(match.group(1))
                    campo = match.group(2)
                    
                    if index not in prodotti_data:
                        prodotti_data[index] = {}
                    
                    # Gestisci il checkbox is_fotorip
                    if campo == 'is_fotorip':
                        prodotti_data[index][campo] = True  # Se presente nel form è checked
                    else:
                        prodotti_data[index][campo] = value.strip() if value else None

        # Crea i prodotti
        for index, dati_prodotto in prodotti_data.items():
            if dati_prodotto.get("descrizione"):  # Solo se ha descrizione (campo obbligatorio)
                is_fotorip = dati_prodotto.get("is_fotorip", False)
                
                # Per fotorip, genera seriale automatico se non fornito
                seriale = dati_prodotto.get("seriale")
                if is_fotorip and not seriale:
                    # Genera seriale automatico per fotorip
                    import time
                    seriale = f"FOTORIP_{int(time.time())}_{index}"
                
                prodotto = Prodotto(
                    acquisto_id=nuovo_acquisto.id,
                    seriale=seriale,
                    prodotto_descrizione=dati_prodotto.get("descrizione", ""),
                    note_prodotto=dati_prodotto.get("note")
                )
                db.add(prodotto)
                
                # Se è fotorip, crea subito una vendita fittizia
                if is_fotorip:
                    db.flush()  # Per ottenere l'ID del prodotto
                    
                    costo_totale_acquisto = nuovo_acquisto.costo_acquisto + (nuovo_acquisto.costi_accessori or 0)
                    
                    vendita_fotorip = Vendita(
                        prodotto_id=prodotto.id,
                        data_vendita=nuovo_acquisto.data_consegna if nuovo_acquisto.data_consegna else date.today(),
                        canale_vendita="RIPARAZIONI",
                        prezzo_vendita=costo_totale_acquisto,
                        commissioni=0.0,
                        synced_from_invoicex=False,
                        invoicex_id=f"FOTORIP_{prodotto.id}",
                        note_vendita="Prodotto utilizzato per riparazioni - margine neutro - creato manualmente"
                    )
                    
                    db.add(vendita_fotorip)
        
        db.commit()
        
        return RedirectResponse(url="/acquisti?nuovo=success", status_code=303)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore nella creazione: {str(e)}")

@app.get("/acquisti/{acquisto_id}/modifica", response_class=HTMLResponse)
async def modifica_acquisto_form(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Form per modificare acquisto esistente"""
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
    
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    return templates.TemplateResponse("modifica_acquisto.html", {
        "request": request,
        "acquisto": acquisto
    })

@app.post("/acquisti/{acquisto_id}/modifica")
async def modifica_acquisto(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Aggiorna acquisto esistente"""
    form_data = await request.form()
    
    try:
        acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
        if not acquisto:
            raise HTTPException(status_code=404, detail="Acquisto non trovato")
        
        # Aggiorna dati acquisto
        acquisto.id_acquisto_univoco = form_data.get("id_acquisto_univoco")
        acquisto.dove_acquistato = form_data.get("dove_acquistato", "")
        acquisto.venditore = form_data.get("venditore", "")
        acquisto.costo_acquisto = float(form_data.get("costo_acquisto", 0))
        acquisto.costi_accessori = float(form_data.get("costi_accessori", 0))
        acquisto.data_pagamento = datetime.strptime(form_data.get("data_pagamento"), "%Y-%m-%d").date() if form_data.get("data_pagamento") else None
        acquisto.data_consegna = datetime.strptime(form_data.get("data_consegna"), "%Y-%m-%d").date() if form_data.get("data_consegna") else None
        acquisto.note = form_data.get("note")
        
        # Aggiorna prodotti esistenti
        prodotti_data = {}
        for key, value in form_data.items():
            if key.startswith('prodotti['):
                import re
                match = re.match(r'prodotti\[(\d+)\]\[(\w+)\]', key)
                if match:
                    index = int(match.group(1))
                    campo = match.group(2)
                    
                    if index not in prodotti_data:
                        prodotti_data[index] = {}
                    prodotti_data[index][campo] = value.strip() if value else None
        
        # Aggiorna prodotti esistenti e crea nuovi
        prodotti_esistenti = {p.id: p for p in acquisto.prodotti}
        prodotti_nel_form = set()
        
        for index, dati_prodotto in prodotti_data.items():
            prodotto_id = dati_prodotto.get("id")
            
            if prodotto_id and int(prodotto_id) in prodotti_esistenti:
                # Aggiorna prodotto esistente
                prodotto = prodotti_esistenti[int(prodotto_id)]
                prodotti_nel_form.add(int(prodotto_id))
                
                # Non aggiornare prodotti già venduti
                if not prodotto.vendite:
                    prodotto.seriale = dati_prodotto.get("seriale")
                    prodotto.prodotto_descrizione = dati_prodotto.get("descrizione", "")
                    prodotto.note_prodotto = dati_prodotto.get("note")
            elif dati_prodotto.get("descrizione"):
                # Nuovo prodotto (solo se ha descrizione)
                nuovo_prodotto = Prodotto(
                    acquisto_id=acquisto.id,
                    seriale=dati_prodotto.get("seriale"),
                    prodotto_descrizione=dati_prodotto.get("descrizione", ""),
                    note_prodotto=dati_prodotto.get("note")
                )
                db.add(nuovo_prodotto)
        
        # ELIMINA prodotti che non sono più nel form (solo se non venduti)
        for prodotto_id, prodotto in prodotti_esistenti.items():
            if prodotto_id not in prodotti_nel_form:
                # Elimina solo se non ha vendite
                if not prodotto.vendite:
                    db.delete(prodotto)
                else:
                    # Log warning - prodotto venduto non può essere eliminato
                    print(f"WARNING: Tentativo di eliminare prodotto venduto {prodotto_id}")
        
        
        db.commit()
        
        return RedirectResponse(url="/acquisti?modificato=success", status_code=303)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore nella modifica: {str(e)}")

@app.delete("/acquisti/{acquisto_id}")
async def elimina_acquisto(acquisto_id: int, db: Session = Depends(get_db)):
    """Elimina acquisto (solo se non ha vendite)"""
    try:
        acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti).joinedload(Prodotto.vendite)).filter(Acquisto.id == acquisto_id).first()
        
        if not acquisto:
            return {"success": False, "error": "Acquisto non trovato"}
        
        # Verifica che nessun prodotto sia stato venduto
        prodotti_venduti = [p for p in acquisto.prodotti if p.vendite]
        if prodotti_venduti:
            return {"success": False, "error": f"Impossibile eliminare: {len(prodotti_venduti)} prodotti già venduti"}
        
        # Elimina prodotti e poi acquisto
        for prodotto in acquisto.prodotti:
            db.delete(prodotto)
        db.delete(acquisto)
        
        db.commit()
        return {"success": True, "message": "Acquisto eliminato con successo"}
        
    except Exception as e:
        db.rollback()
        return {"success": False, "error": f"Errore: {str(e)}"}

@app.post("/acquisti/{acquisto_id}/segna-arrivato")
async def segna_acquisto_arrivato(acquisto_id: int, db: Session = Depends(get_db)):
    """Segna acquisto come arrivato oggi"""
    try:
        acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
        
        if not acquisto:
            return {"success": False, "error": "Acquisto non trovato"}
        
        acquisto.data_consegna = date.today()
        db.commit()
        
        return {"success": True, "message": "Acquisto segnato come arrivato"}
        
    except Exception as e:
        db.rollback()
        return {"success": False, "error": f"Errore: {str(e)}"}

@app.get("/favicon.ico")
async def favicon():
    """Favicon placeholder"""
    return {"message": "No favicon"}

@app.get("/vendite/{vendita_id}/modifica", response_class=HTMLResponse)
async def modifica_vendita_form(vendita_id: int, request: Request, db: Session = Depends(get_db)):
    """Form per modificare vendita esistente"""
    vendita = db.query(Vendita).options(joinedload(Vendita.prodotto)).filter(Vendita.id == vendita_id).first()
    
    if not vendita:
        raise HTTPException(status_code=404, detail="Vendita non trovata")
    
    return templates.TemplateResponse("modifica_vendita.html", {
        "request": request,
        "vendita": vendita
    })

@app.post("/vendite/{vendita_id}/modifica")
async def modifica_vendita(vendita_id: int, request: Request, db: Session = Depends(get_db)):
    """Aggiorna vendita esistente"""
    form_data = await request.form()
    
    try:
        vendita = db.query(Vendita).filter(Vendita.id == vendita_id).first()
        if not vendita:
            raise HTTPException(status_code=404, detail="Vendita non trovata")
        
        # Aggiorna dati vendita
        vendita.data_vendita = datetime.strptime(form_data.get("data_vendita"), "%Y-%m-%d").date()
        vendita.canale_vendita = form_data.get("canale_vendita")
        vendita.prezzo_vendita = float(form_data.get("prezzo_vendita", 0))
        vendita.commissioni = float(form_data.get("commissioni", 0))
        vendita.note_vendita = form_data.get("note_vendita")
        
        db.commit()
        
        return RedirectResponse(url="/vendite?modificato=success", status_code=303)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore nella modifica: {str(e)}")

@app.delete("/vendite/{vendita_id}")
async def elimina_vendita(vendita_id: int, db: Session = Depends(get_db)):
    """Elimina vendita"""
    try:
        vendita = db.query(Vendita).filter(Vendita.id == vendita_id).first()
        
        if not vendita:
            return {"success": False, "error": "Vendita non trovata"}
        
        db.delete(vendita)
        db.commit()
        
        return {"success": True, "message": "Vendita eliminata con successo"}
        
    except Exception as e:
        db.rollback()
        return {"success": False, "error": f"Errore: {str(e)}"}

@app.get("/acquisti/{acquisto_id}/seriali", response_class=HTMLResponse)
async def inserisci_seriali_form(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Form per inserire seriali mancanti per un acquisto"""
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
    
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    return templates.TemplateResponse("inserisci_seriali.html", {
        "request": request,
        "acquisto": acquisto
    })

@app.post("/acquisti/{acquisto_id}/seriali")
async def salva_seriali_acquisto(acquisto_id: int, request: Request, db: Session = Depends(get_db)):
    """Salva i seriali per un acquisto specifico"""
    form_data = await request.form()
    
    try:
        acquisto = db.query(Acquisto).filter(Acquisto.id == acquisto_id).first()
        if not acquisto:
            raise HTTPException(status_code=404, detail="Acquisto non trovato")
        
        # Parsea i seriali dal formato: prodotti[0][id], prodotti[0][seriale]
        seriali_data = {}
        for key, value in form_data.items():
            if key.startswith('prodotti[') and value.strip():
                import re
                match = re.match(r'prodotti\[(\d+)\]\[(\w+)\]', key)
                if match:
                    index = int(match.group(1))
                    campo = match.group(2)
                    
                    if index not in seriali_data:
                        seriali_data[index] = {}
                    seriali_data[index][campo] = value.strip()
        
        seriali_aggiornati = 0
        errori = []
        
        for index, dati in seriali_data.items():
            prodotto_id = dati.get('id')
            nuovo_seriale = dati.get('seriale')
            
            if not prodotto_id or not nuovo_seriale:
                continue
            
            try:
                # Verifica seriale univoco
                if db.query(Prodotto).filter(
                    Prodotto.seriale == nuovo_seriale,
                    Prodotto.id != int(prodotto_id)
                ).first():
                    errori.append(f"Seriale {nuovo_seriale} già esistente")
                    continue
                
                # Aggiorna il prodotto
                prodotto = db.query(Prodotto).filter(Prodotto.id == int(prodotto_id)).first()
                if prodotto and not prodotto.seriale:  # Solo se non ha già un seriale
                    prodotto.seriale = nuovo_seriale
                    seriali_aggiornati += 1
                    
            except Exception as e:
                errori.append(f"Errore prodotto ID {prodotto_id}: {str(e)}")
        
        db.commit()
        
        if seriali_aggiornati > 0:
            return RedirectResponse(url=f"/acquisti?seriali_inserted={seriali_aggiornati}", status_code=303)
        else:
            return RedirectResponse(url=f"/acquisti?errori={len(errori)}", status_code=303)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore nel salvataggio: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check per Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)