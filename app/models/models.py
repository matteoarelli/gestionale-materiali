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
    costo_acquisto = Column(DECIMAL(10, 2), nullable=False)  # Costo totale di tutti i prodotti
    costi_accessori = Column(DECIMAL(10, 2), default=0.00)  # Spedizione, commissioni, etc.
    data_pagamento = Column(Date, nullable=True)
    data_consegna = Column(Date, nullable=True)
    note = Column(Text, nullable=True)  # Note aggiuntive sull'acquisto
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relazione con prodotti
    prodotti = relationship("Prodotto", back_populates="acquisto")
    
    @property
    def costo_totale(self):
        return float(self.costo_acquisto) + float(self.costi_accessori or 0)
    
    @property
    def numero_prodotti(self):
        return len(self.prodotti)
    
    @property
    def prodotti_venduti(self):
        return len([p for p in self.prodotti if p.venduto])
    
    @property
    def prodotti_in_stock(self):
        return len([p for p in self.prodotti if not p.venduto])
    
    @property
    def completamente_venduto(self):
        return len(self.prodotti) > 0 and all(p.venduto for p in self.prodotti)
    
    @property
    def ricavo_totale(self):
        return sum(p.ricavo_vendita for p in self.prodotti if p.venduto)
    
    @property
    def margine_totale(self):
        return self.ricavo_totale - self.costo_totale

class Prodotto(Base):
    __tablename__ = "prodotti"
    
    id = Column(Integer, primary_key=True, index=True)
    acquisto_id = Column(Integer, ForeignKey("acquisti.id"), nullable=False, index=True)
    seriale = Column(String(100), unique=False, index=True, nullable=True)  # Ora può essere null
    prodotto_descrizione = Column(Text, nullable=False)
    note_prodotto = Column(Text, nullable=True)  # Note specifiche del prodotto
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relazioni
    acquisto = relationship("Acquisto", back_populates="prodotti")
    vendite = relationship("Vendita", back_populates="prodotto")
    
    @property
    def venduto(self):
        return len(self.vendite) > 0
    
    @property
    def ricavo_vendita(self):
        if not self.vendite:
            return 0
        return sum(float(v.prezzo_vendita) - float(v.commissioni or 0) for v in self.vendite)

class Vendita(Base):
    __tablename__ = "vendite"
    
    id = Column(Integer, primary_key=True, index=True)
    seriale = Column(String(100), ForeignKey("prodotti.seriale"), nullable=False, index=True)
    data_vendita = Column(Date, nullable=False)
    canale_vendita = Column(String(50), nullable=False)  # ebay, backmarket, refurbed, sede, etc.
    prezzo_vendita = Column(DECIMAL(10, 2), nullable=False)
    commissioni = Column(DECIMAL(10, 2), default=0.00)
    synced_from_invoicex = Column(Boolean, default=True)
    invoicex_id = Column(String(50), nullable=True)  # ID dalla fattura di InvoiceX
    note_vendita = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relazione con prodotto
    prodotto = relationship("Prodotto", back_populates="vendite")
    
    @property
    def ricavo_netto(self):
        return float(self.prezzo_vendita) - float(self.commissioni or 0)