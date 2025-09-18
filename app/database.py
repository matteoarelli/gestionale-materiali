import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Database principale (Railway PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database InvoiceX (per la sincronizzazione)
config_invoicex = {
    'user': 'ilblogdi_inv2021',
    'password': 'pWTrEKV}=fF-',
    'host': 'nl1-ts3.a2hosting.com',
    'database': 'ilblogdi_invoicex2021',
    'port': '3306'  # Porta MySQL standard
}

def get_invoicex_connection_string():
    # Assumendo che sia MySQL (più comune per hosting condivisi)
    return f"mysql+pymysql://{config_invoicex['user']}:{config_invoicex['password']}@{config_invoicex['host']}:{config_invoicex['port']}/{config_invoicex['database']}"

INVOICEX_DATABASE_URL = get_invoicex_connection_string()
invoicex_engine = None
InvoiceXSessionLocal = None

if INVOICEX_DATABASE_URL:
    try:
        invoicex_engine = create_engine(INVOICEX_DATABASE_URL)
        InvoiceXSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=invoicex_engine)
    except Exception as e:
        print(f"Errore connessione InvoiceX: {e}")
        invoicex_engine = None
        InvoiceXSessionLocal = None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_invoicex_db():
    if InvoiceXSessionLocal is None:
        raise Exception("InvoiceX database not configured")
    db = InvoiceXSessionLocal()
    try:
        yield db
    finally:
        db.close()