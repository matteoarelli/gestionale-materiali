from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from datetime import datetime, date
from typing import List

from app.database import get_db
from app.models.models import Acquisto, Vendita, Prodotto

api_router = APIRouter()
debug_router = APIRouter()

# ================================================================
# API ENDPOINTS PER SCRIPT LOCALE
# ================================================================

@api_router.post("/sync/acquisti")
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
                    created_at=data_consegna if data_consegna else datetime.now()
                )
                
                db.add(nuovo_acquisto)
                db.flush()
                
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
                        db.flush()
                        
                        costo_totale_acquisto = float(acquisto_info.get("costo_acquisto", 0)) + float(acquisto_info.get("costi_accessori", 0))
                        
                        vendita_fotorip = Vendita(
                            prodotto_id=nuovo_prodotto.id,
                            data_vendita=data_consegna if data_consegna else date.today(),
                            canale_vendita="RIPARAZIONI",
                            prezzo_vendita=costo_totale_acquisto,
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

@api_router.post("/sync/vendite")
async def ricevi_vendite_da_script(request: Request, db: Session = Depends(get_db)):
    """API per ricevere vendite dallo script locale"""
    try:
        data = await request.json()
        
        # Verifica token di sicurezza
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

@api_router.get("/sync/prodotti-senza-vendite")
async def get_prodotti_per_sync(db: Session = Depends(get_db)):
    """API per ottenere lista prodotti con seriali per lo script"""
    try:
        prodotti = db.query(Prodotto).filter(
            Prodotto.seriale.isnot(None),
            ~Prodotto.vendite.any()
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

@api_router.get("/prodotti-con-seriali-senza-vendite")
async def get_prodotti_con_seriali_senza_vendite(db: Session = Depends(get_db)):
    """Restituisce prodotti che hanno seriali ma nessuna vendita associata"""
    
    prodotti_senza_vendite = db.query(Prodotto).filter(
        and_(
            Prodotto.seriale.isnot(None),
            Prodotto.seriale != "",
            Prodotto.seriale != "N/A",
            ~Prodotto.seriale.like("%fotorip%")
        )
    ).all()
    
    prodotti_problema = []
    
    for prodotto in prodotti_senza_vendite:
        vendite = db.query(Vendita).filter(
            Vendita.seriale == prodotto.seriale
        ).all()
        
        if not vendite:
            prodotti_problema.append({
                "id": prodotto.id,
                "seriale": prodotto.seriale,
                "descrizione": prodotto.descrizione,
                "venduto": prodotto.venduto,
                "acquisto_id": prodotto.acquisto_id,
                "giorni_in_stock": prodotto.giorni_in_stock,
                "note": prodotto.note
            })
    
    return {
        "count": len(prodotti_problema),
        "prodotti": prodotti_problema
    }

# ================================================================
# DEBUG ENDPOINTS
# ================================================================

@debug_router.get("/sync-vendite")
async def debug_sync_vendite(db: Session = Depends(get_db)):
    """Debug per identificare problemi sincronizzazione vendite"""
    
    # Usa la stessa logica del dashboard: prodotti senza vendite associate
    prodotti_non_venduti = db.query(Prodotto).filter(
        ~Prodotto.vendite.any()  # Nessuna vendita associata
    ).options(joinedload(Prodotto.acquisto)).all()
    
    debug_info = []
    
    for prodotto in prodotti_non_venduti:
        # Salta prodotti senza seriale
        if not prodotto.seriale or prodotto.seriale in ["", "???", "N/A"]:
            continue
            
        # Cerca vendite per questo seriale
        vendita_esatta = db.query(Vendita).filter(
            Vendita.seriale == prodotto.seriale
        ).first()
        
        vendita_case_insensitive = db.query(Vendita).filter(
            func.lower(Vendita.seriale) == func.lower(prodotto.seriale)
        ).first()
        
        vendite_contenenti = db.query(Vendita).filter(
            Vendita.seriale.ilike(f"%{prodotto.seriale}%")
        ).all()
        
        # Calcola giorni in stock se possibile
        giorni_stock = None
        if prodotto.acquisto and prodotto.acquisto.data_consegna:
            from datetime import datetime
            giorni_stock = (datetime.now().date() - prodotto.acquisto.data_consegna).days
        
        debug_info.append({
            "prodotto_id": prodotto.id,
            "seriale": prodotto.seriale,
            "descrizione": prodotto.prodotto_descrizione,
            "acquisto_id": prodotto.acquisto.id_acquisto_univoco if prodotto.acquisto else None,
            "vendita_esatta": vendita_esatta.id if vendita_esatta else None,
            "vendita_case_insensitive": vendita_case_insensitive.id if vendita_case_insensitive else None,
            "vendite_contenenti_count": len(vendite_contenenti),
            "giorni_in_stock": giorni_stock,
            "problema": "SERIALE_NON_SINCRONIZZATO" if vendita_esatta else "POSSIBILE_MISMATCH" if vendite_contenenti else "VENDITA_MANCANTE"
        })
    
    # Ordina per problemi più gravi prima
    debug_info.sort(key=lambda x: (x["problema"] != "SERIALE_NON_SINCRONIZZATO", x["giorni_in_stock"] or 0), reverse=True)
    
    return {
        "prodotti_in_stock_totali": len(prodotti_non_venduti),
        "prodotti_con_seriali_in_stock": len(debug_info),
        "debug_dettagli": debug_info[:50],  # Aumentato per vedere più dettagli
        "statistiche": {
            "con_vendita_esatta": len([d for d in debug_info if d["vendita_esatta"]]),
            "con_vendita_case_insensitive": len([d for d in debug_info if d["vendita_case_insensitive"]]),
            "con_vendite_contenenti": len([d for d in debug_info if d["vendite_contenenti_count"] > 0]),
            "solo_vendita_mancante": len([d for d in debug_info if d["problema"] == "VENDITA_MANCANTE"])
        },
        "breakdown_problemi": {
            "SERIALE_NON_SINCRONIZZATO": len([d for d in debug_info if d["problema"] == "SERIALE_NON_SINCRONIZZATO"]),
            "POSSIBILE_MISMATCH": len([d for d in debug_info if d["problema"] == "POSSIBILE_MISMATCH"]), 
            "VENDITA_MANCANTE": len([d for d in debug_info if d["problema"] == "VENDITA_MANCANTE"])
        }
    }

@debug_router.get("/seriali-specifici")
async def debug_seriali_specifici(seriali: str, db: Session = Depends(get_db)):
    """Debug per seriali specifici separati da virgola"""
    
    seriali_lista = [s.strip() for s in seriali.split(",")]
    risultati = []
    
    for seriale in seriali_lista:
        prodotto = db.query(Prodotto).filter(
            Prodotto.seriale == seriale
        ).first()
        
        vendite = db.query(Vendita).filter(
            Vendita.seriale == seriale
        ).all()
        
        # FIX: usa ilike invece di func.lower
        prodotti_simili = db.query(Prodotto).filter(
            Prodotto.seriale.ilike(f"%{seriale}%")
        ).all()
        
        vendite_simili = db.query(Vendita).filter(
            Vendita.seriale.ilike(f"%{seriale}%") 
        ).all()
        
        risultati.append({
            "seriale_cercato": seriale,
            "prodotto_trovato": {
                "id": prodotto.id if prodotto else None,
                "seriale": prodotto.seriale if prodotto else None,
                "venduto": prodotto.venduto if prodotto else None,
                "descrizione": prodotto.descrizione if prodotto else None
            },
            "vendite_trovate": [
                {
                    "id": v.id,
                    "data": v.data_vendita.isoformat() if v.data_vendita else None,
                    "seriale": v.seriale,
                    "prezzo": float(v.prezzo_vendita) if v.prezzo_vendita else None
                } for v in vendite
            ],
            "prodotti_simili_count": len(prodotti_simili),
            "vendite_simili_count": len(vendite_simili)
        })
    
    return risultati

@debug_router.post("/fix-vendite-mancanti")
async def fix_vendite_mancanti(db: Session = Depends(get_db)):
    """Corregge automaticamente prodotti con vendite non associate"""
    
    corretti = 0
    errori = []
    
    prodotti_non_venduti = db.query(Prodotto).filter(
        Prodotto.venduto == False
    ).all()
    
    for prodotto in prodotti_non_venduti:
        vendita = db.query(Vendita).filter(
            or_(
                Vendita.seriale == prodotto.seriale,
                Vendita.seriale.ilike(f"%{prodotto.seriale}%")
            )
        ).first()
        
        if vendita:
            try:
                prodotto.venduto = True
                
                if vendita.seriale != prodotto.seriale:
                    vendita.seriale = prodotto.seriale
                
                corretti += 1
                
            except Exception as e:
                errori.append({
                    "seriale": prodotto.seriale,
                    "errore": str(e)
                })
    
    if corretti > 0:
        db.commit()
    
    return {
        "corretti": corretti,
        "errori": errori,
        "messaggio": f"Corretti {corretti} prodotti con vendite mancanti"
    }