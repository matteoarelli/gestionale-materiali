import sys
import os
from datetime import datetime, date
from sqlalchemy import text

# Aggiungi la cartella parent al path per importare app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, invoicex_engine, SessionLocal
from app.models.models import Acquisto, Vendita, Prodotto

def sync_vendite_from_invoicex():
    """
    Sincronizza le vendite dal database InvoiceX
    Questa funzione dovrai personalizzarla in base alla struttura del tuo database InvoiceX
    """
    
    if not invoicex_engine:
        print("Database InvoiceX non configurato")
        return
    
    db = SessionLocal()
    
    try:
        # Query di esempio - dovrai modificarla in base alla struttura del tuo DB InvoiceX
        # Assumendo una tabella 'fatture' o simile con i dati di vendita
        
        with invoicex_engine.connect() as conn:
            # MODIFICA QUESTA QUERY in base alla struttura del tuo database InvoiceX
            query = text("""
                SELECT 
                    id,
                    serial_number,
                    sale_date,
                    sale_channel,
                    sale_price,
                    commission,
                    created_at
                FROM sales 
                WHERE sync_status != 'synced' 
                OR sync_status IS NULL
                ORDER BY created_at DESC
            """)
            
            result = conn.execute(query)
            vendite_invoicex = result.fetchall()
            
            print(f"Trovate {len(vendite_invoicex)} vendite da sincronizzare")
            
            for vendita_data in vendite_invoicex:
                # Cerca il prodotto corrispondente tramite seriale
                prodotto = db.query(Prodotto).filter(
                    Prodotto.seriale == vendita_data.serial_number
                ).first()
                
                if not prodotto:
                    print(f"Prodotto non trovato per seriale: {vendita_data.serial_number}")
                    continue
                
                # Verifica se la vendita è già stata sincronizzata
                vendita_esistente = db.query(Vendita).filter(
                    Vendita.invoicex_id == str(vendita_data.id)
                ).first()
                
                if vendita_esistente:
                    print(f"Vendita già sincronizzata: {vendita_data.id}")
                    continue
                
                # Crea nuova vendita
                nuova_vendita = Vendita(
                    seriale=vendita_data.serial_number,
                    data_vendita=vendita_data.sale_date,
                    canale_vendita=vendita_data.sale_channel or 'unknown',
                    prezzo_vendita=float(vendita_data.sale_price),
                    commissioni=float(vendita_data.commission or 0),
                    synced_from_invoicex=True,
                    invoicex_id=str(vendita_data.id)
                )
                
                db.add(nuova_vendita)
                print(f"Sincronizzata vendita: {vendita_data.serial_number} - €{vendita_data.sale_price}")
            
            db.commit()
            print("Sincronizzazione completata con successo")
            
    except Exception as e:
        print(f"Errore durante la sincronizzazione: {e}")
        db.rollback()
    finally:
        db.close()

def test_invoicex_connection():
    """Test della connessione al database InvoiceX"""
    
    if not invoicex_engine:
        print("❌ Database InvoiceX non configurato")
        return False
    
    try:
        with invoicex_engine.connect() as conn:
            # Query semplice per testare la connessione
            result = conn.execute(text("SELECT 1 as test"))
            test_result = result.fetchone()
            
            if test_result:
                print("✅ Connessione a InvoiceX riuscita")
                
                # Mostra le tabelle disponibili
                tables_result = conn.execute(text("SHOW TABLES"))
                tables = [row[0] for row in tables_result.fetchall()]
                print(f"📋 Tabelle disponibili: {', '.join(tables[:10])}")  # Prime 10 tabelle
                
                return True
            else:
                print("❌ Test connessione fallito")
                return False
                
    except Exception as e:
        print(f"❌ Errore connessione InvoiceX: {e}")
        return False

if __name__ == "__main__":
    print("🔄 Avvio sincronizzazione InvoiceX...")
    print(f"⏰ {datetime.now()}")
    
    # Test connessione
    if test_invoicex_connection():
        # Esegui sincronizzazione
        sync_vendite_from_invoicex()
    else:
        print("❌ Impossibile procedere senza connessione")
    
    print("✅ Script completato")