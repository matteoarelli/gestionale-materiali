import sys
import os
from datetime import datetime, date
from sqlalchemy import text, create_engine

# Aggiungi la cartella parent al path per importare app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, SessionLocal
from app.models.models import Acquisto, Vendita, Prodotto

# Configurazione DB Invoicex
config_invoicex = {
    'user': 'ilblogdi_inv2021',
    'password': 'pWTrEKV}=fF-',
    'host': 'nl1-ts3.a2hosting.com',
    'database': 'ilblogdi_invoicex2021',
    'port': '3306'  # Porta MySQL standard
}

def get_invoicex_connection():
    """Crea connessione diretta al database InvoiceX"""
    try:
        connection_string = f"mysql+pymysql://{config_invoicex['user']}:{config_invoicex['password']}@{config_invoicex['host']}:{config_invoicex['port']}/{config_invoicex['database']}"
        engine = create_engine(connection_string)
        return engine
    except Exception as e:
        print(f"Errore creazione connessione InvoiceX: {e}")
        return None

def test_invoicex_connection():
    """Test della connessione al database InvoiceX"""
    
    engine = get_invoicex_connection()
    if not engine:
        print("❌ Impossibile creare connessione a InvoiceX")
        return False
    
    try:
        with engine.connect() as conn:
            # Query semplice per testare la connessione
            result = conn.execute(text("SELECT 1 as test"))
            test_result = result.fetchone()
            
            if test_result:
                print("✅ Connessione a InvoiceX riuscita")
                
                # Mostra le tabelle disponibili
                print("\n📋 Esplorazione database InvoiceX:")
                tables_result = conn.execute(text("SHOW TABLES"))
                tables = [row[0] for row in tables_result.fetchall()]
                print(f"Trovate {len(tables)} tabelle:")
                for i, table in enumerate(tables[:20], 1):  # Prime 20 tabelle
                    print(f"  {i}. {table}")
                
                if len(tables) > 20:
                    print(f"  ... e altre {len(tables) - 20} tabelle")
                
                return True, tables
            else:
                print("❌ Test connessione fallito")
                return False, []
                
    except Exception as e:
        print(f"❌ Errore connessione InvoiceX: {e}")
        return False, []

def explore_invoicex_tables(tables_to_check=None):
    """Esplora le tabelle di InvoiceX per trovare i dati delle vendite"""
    
    engine = get_invoicex_connection()
    if not engine:
        return
    
    # Tabelle che potrebbero contenere dati di vendita
    if not tables_to_check:
        tables_to_check = [
            'invoices', 'invoice', 'fatture', 'fattura',
            'sales', 'sale', 'vendite', 'vendita',
            'items', 'item', 'articoli', 'articolo',
            'products', 'product', 'prodotti', 'prodotto',
            'orders', 'order', 'ordini', 'ordine'
        ]
    
    try:
        with engine.connect() as conn:
            # Prima ottieni tutte le tabelle
            all_tables_result = conn.execute(text("SHOW TABLES"))
            all_tables = [row[0] for row in all_tables_result.fetchall()]
            
            print(f"\n🔍 Esplorazione tabelle potenziali per vendite:")
            
            for table_name in tables_to_check:
                # Cerca tabelle che contengono il nome
                matching_tables = [t for t in all_tables if table_name.lower() in t.lower()]
                
                for table in matching_tables:
                    print(f"\n📊 Tabella: {table}")
                    try:
                        # Ottieni struttura tabella
                        structure = conn.execute(text(f"DESCRIBE {table}"))
                        columns = structure.fetchall()
                        
                        print("  Colonne:")
                        for col in columns:
                            print(f"    - {col[0]} ({col[1]})")
                        
                        # Conta righe
                        count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = count_result.fetchone()[0]
                        print(f"  Righe: {count}")
                        
                        # Se ci sono dati, mostra un esempio
                        if count > 0:
                            sample_result = conn.execute(text(f"SELECT * FROM {table} LIMIT 3"))
                            samples = sample_result.fetchall()
                            print("  Esempio dati:")
                            for i, sample in enumerate(samples, 1):
                                print(f"    Riga {i}: {dict(zip([col[0] for col in columns], sample))}")
                        
                    except Exception as e:
                        print(f"  ❌ Errore nell'esplorazione: {e}")
                        
            return all_tables
                        
    except Exception as e:
        print(f"❌ Errore nell'esplorazione: {e}")
        return []

def find_sales_data():
    """Cerca specificamente i dati delle vendite con seriali"""
    
    engine = get_invoicex_connection()
    if not engine:
        return
        
    try:
        with engine.connect() as conn:
            # Prima ottieni tutte le tabelle
            all_tables_result = conn.execute(text("SHOW TABLES"))
            all_tables = [row[0] for row in all_tables_result.fetchall()]
            
            print(f"\n🎯 Ricerca dati vendite con seriali...")
            
            # Cerca tabelle che potrebbero avere seriali
            for table in all_tables:
                try:
                    # Ottieni struttura
                    structure = conn.execute(text(f"DESCRIBE {table}"))
                    columns = [col[0].lower() for col in structure.fetchall()]
                    
                    # Cerca colonne che potrebbero contenere seriali
                    serial_columns = [col for col in columns if any(keyword in col for keyword in 
                                    ['serial', 'seriale', 'sn', 'code', 'codice', 'model', 'imei'])]
                    
                    if serial_columns:
                        print(f"\n🔍 Tabella {table} - Possibili colonne seriali: {serial_columns}")
                        
                        # Mostra alcuni dati di esempio
                        sample_result = conn.execute(text(f"SELECT * FROM {table} LIMIT 2"))
                        samples = sample_result.fetchall()
                        
                        if samples:
                            # Ottieni nomi colonne originali
                            original_structure = conn.execute(text(f"DESCRIBE {table}"))
                            original_columns = [col[0] for col in original_structure.fetchall()]
                            
                            print("  Esempio dati:")
                            for i, sample in enumerate(samples, 1):
                                row_data = dict(zip(original_columns, sample))
                                print(f"    Riga {i}:")
                                for col, val in row_data.items():
                                    if col.lower() in serial_columns:
                                        print(f"      🎯 {col}: {val}")
                                    elif any(keyword in col.lower() for keyword in ['date', 'data', 'price', 'prezzo', 'amount']):
                                        print(f"      📅 {col}: {val}")
                        
                except Exception as e:
                    continue  # Salta tabelle problematiche
                    
    except Exception as e:
        print(f"❌ Errore nella ricerca: {e}")

if __name__ == "__main__":
    print("🔄 Test connessione InvoiceX...")
    print(f"⏰ {datetime.now()}")
    print(f"🌐 Host: {config_invoicex['host']}")
    print(f"🗄️  Database: {config_invoicex['database']}")
    print(f"👤 User: {config_invoicex['user']}")
    
    # Test connessione base
    success, tables = test_invoicex_connection()
    
    if success:
        print(f"\n🎉 Connessione riuscita! Database InvoiceX accessibile.")
        
        # Esplora le tabelle principali
        print("\n" + "="*50)
        all_tables = explore_invoicex_tables()
        
        # Cerca specificamente dati vendite
        print("\n" + "="*50)
        find_sales_data()
        
        print(f"\n✅ Esplorazione completata")
        print(f"💡 Prossimo passo: identificare la tabella con i dati delle vendite")
        
    else:
        print("❌ Impossibile procedere senza connessione")
    
    print("\n🏁 Script completato")