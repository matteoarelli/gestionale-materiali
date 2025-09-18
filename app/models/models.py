from sqlalchemy import Column, Integer, String, Date, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.types import DECIMAL
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Acquisto(Base):
    __tablename__ = "acquisti"
    
    id = Column(Integer, primary_key=True, index=True)
    id_acquisto_univoco = Column(String(50), unique=True, index=True, nullable=False)
    dove_acquistato = Column(String(100), nullable=False)
    venditore = Column(String(100), nullable=False)
    prodotto_descrizione = Column(Text, nullable=False)
    seriale = Column(String(100), unique=True, index=True, nullable=False)
    costo_acquisto = Column(DECIMAL(10, 2), nullable=False)
    costi_accessori = Column(DECIMAL(10, 2), default=0.00)
    data_pagamento = Column(Date, nullable=True)
    data_consegna = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relazione con vendite
    vendite = relationship("Vendita", back_populates="acquisto")
    
    @property
    def costo_totale(self):
        return float(self.costo_acquisto) + float(self.costi_accessori or 0)
    
    @property
    def venduto(self):
        return len(self.vendite) > 0
    
    @property
    def ricavo_totale(self):
        if not self.vendite:
            return 0
        return sum(float(v.prezzo_vendita) - float(v.commissioni or 0) for v in self.vendite)
    
    @property
    def margine(self):
        if not self.venduto:
            return 0
        return self.ricavo_totale - self.costo_totale

class Vendita(Base):
    __tablename__ = "vendite"
    
    id = Column(Integer, primary_key=True, index=True)
    seriale = Column(String(100), ForeignKey("acquisti.seriale"), nullable=False, index=True)
    data_vendita = Column(Date, nullable=False)
    canale_vendita = Column(String(50), nullable=False)  # ebay, backmarket, refurbed, sede, etc.
    prezzo_vendita = Column(DECIMAL(10, 2), nullable=False)
    commissioni = Column(DECIMAL(10, 2), default=0.00)
    synced_from_invoicex = Column(Boolean, default=True)
    invoicex_id = Column(String(50), nullable=True)  # ID dalla fattura di InvoiceX
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relazione con acquisto
    acquisto = relationship("Acquisto", back_populates="vendite")
    
    @property
    def ricavo_netto(self):
        return float(self.prezzo_vendita) - float(self.commissioni or 0)