import os
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import uvicorn
from datetime import datetime, date

from app.database import get_db, engine, Base
from app.models.models import Acquisto, Vendita, Prodotto
from app.routers import acquisti

# Rimuovi il drop_all dopo il primo deploy per non perdere dati
# Base.metadata.drop_all(bind=engine)  # Commentato
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
    print(f"DEBUG: Accesso a /acquisti/{acquisto_id}/seriali")  # Debug log
    
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        print(f"DEBUG: Acquisto {acquisto_id} non trovato")  # Debug log
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    print(f"DEBUG: Acquisto trovato: {acquisto.id_acquisto_univoco}")  # Debug log
    
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
    prodotti_da_eliminare = []
    
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

@app.get("/api/acquisti/{acquisto_id}")
async def get_acquisto_dettaglio(acquisto_id: int, db: Session = Depends(get_db)):
    """API per ottenere dettagli completi di un acquisto"""
    # Carica l'acquisto con i prodotti usando joinedload
    acquisto = db.query(Acquisto).options(joinedload(Acquisto.prodotti)).filter(Acquisto.id == acquisto_id).first()
    if not acquisto:
        raise HTTPException(status_code=404, detail="Acquisto non trovato")
    
    try:
        print(f"DEBUG API: Acquisto {acquisto.id} ha {len(acquisto.prodotti)} prodotti")  # Debug
        
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
        
        print(f"DEBUG API: Restituisco {len(prodotti_list)} prodotti")  # Debug
        return result
        
    except Exception as e:
        print(f"Errore API dettagli: {str(e)}")  # Debug log
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

@app.get("/debug-ip")
async def debug_ip(request: Request):
    """Mostra informazioni IP e rete"""
    import socket
    import subprocess
    
    try:
        # IP locale
        local_ip = socket.gethostbyname(socket.gethostname())
        
        # Prova a ottenere IP pubblico
        try:
            import urllib.request
            public_ip = urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
        except:
            public_ip = "Non disponibile"
            
        # Headers della richiesta
        headers = dict(request.headers)
        
        return {
            "local_ip": local_ip,
            "public_ip": public_ip,
            "request_headers": headers,
            "host": request.url.hostname
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/explore-invoicex")
async def explore_invoicex_detailed():
    """Esplorazione dettagliata del database InvoiceX"""
    try:
        from sqlalchemy import create_engine, text
        
        config_invoicex = {
            'user': 'ilblogdi_inv2021',
            'password': 'pWTrEKV}=fF-',
            'host': 'nl1-ts3.a2hosting.com',
            'database': 'ilblogdi_invoicex2021',
            'port': '3306'
        }
        
        connection_string = f"mysql+pymysql://{config_invoicex['user']}:{config_invoicex['password']}@{config_invoicex['host']}:{config_invoicex['port']}/{config_invoicex['database']}"
        engine = create_engine(connection_string)
        
        with engine.connect() as conn:
            # Ottieni tutte le tabelle
            tables_result = conn.execute(text("SHOW TABLES"))
            all_tables = [row[0] for row in tables_result.fetchall()]
            
            # Cerca tabelle che probabilmente contengono fatture/vendite
            target_keywords = ['fattur', 'invoice', 'documen', 'righe', 'testata', 'corpo', 'dettagl']
            
            detailed_tables = []
            
            for table in all_tables:
                if any(keyword in table.lower() for keyword in target_keywords):
                    try:
                        # Struttura tabella
                        structure = conn.execute(text(f"DESCRIBE {table}"))
                        columns = [{"name": col[0], "type": col[1]} for col in structure.fetchall()]
                        
                        # Conta righe
                        count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = count_result.fetchone()[0]
                        
                        # Se ha dati, prendi un campione
                        sample_data = []
                        if count > 0:
                            sample_result = conn.execute(text(f"SELECT * FROM {table} LIMIT 2"))
                            samples = sample_result.fetchall()
                            
                            for sample in samples:
                                row_data = {}
                                for i, col in enumerate(columns):
                                    value = sample[i]
                                    # Converti in stringa se necessario per JSON
                                    if value is not None:
                                        row_data[col["name"]] = str(value)
                                    else:
                                        row_data[col["name"]] = None
                                sample_data.append(row_data)
                        
                        detailed_tables.append({
                            "name": table,
                            "columns": columns,
                            "row_count": count,
                            "sample_data": sample_data
                        })
                        
                    except Exception as e:
                        continue
            
            return {
                "status": "success",
                "total_tables": len(all_tables),
                "detailed_tables": detailed_tables,
                "table_names": [t["name"] for t in detailed_tables]
            }
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/test-invoicex")
async def test_invoicex_connection():
    """Test connessione InvoiceX via web"""
    try:
        from sqlalchemy import create_engine, text
        
        # Configurazione DB Invoicex
        config_invoicex = {
            'user': 'ilblogdi_inv2021',
            'password': 'pWTrEKV}=fF-',
            'host': 'nl1-ts3.a2hosting.com',
            'database': 'ilblogdi_invoicex2021',
            'port': '3306'
        }
        
        connection_string = f"mysql+pymysql://{config_invoicex['user']}:{config_invoicex['password']}@{config_invoicex['host']}:{config_invoicex['port']}/{config_invoicex['database']}"
        engine = create_engine(connection_string)
        
        with engine.connect() as conn:
            # Test connessione
            result = conn.execute(text("SELECT 1 as test"))
            test_result = result.fetchone()
            
            if not test_result:
                return {"status": "error", "message": "Test query failed"}
            
            # Ottieni elenco tabelle
            tables_result = conn.execute(text("SHOW TABLES"))
            tables = [row[0] for row in tables_result.fetchall()]
            
            # Cerca tabelle potenzialmente interessanti
            interesting_tables = []
            keywords = ['invoice', 'fattur', 'sale', 'vend', 'item', 'product', 'order']
            
            for table in tables:
                if any(keyword in table.lower() for keyword in keywords):
                    try:
                        # Ottieni struttura
                        structure = conn.execute(text(f"DESCRIBE {table}"))
                        columns = [{"name": col[0], "type": col[1]} for col in structure.fetchall()]
                        
                        # Conta righe
                        count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = count_result.fetchone()[0]
                        
                        interesting_tables.append({
                            "name": table,
                            "columns": columns,
                            "row_count": count
                        })
                    except:
                        continue
            
            return {
                "status": "success",
                "message": "Connessione riuscita",
                "total_tables": len(tables),
                "all_tables": tables[:20],  # Prime 20
                "interesting_tables": interesting_tables
            }
            
    except Exception as e:
        return {
            "status": "error", 
            "message": str(e),
            "type": type(e).__name__
        }

@app.get("/health")
async def health_check():
    """Health check per Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)