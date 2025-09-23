from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, date

Base = declarative_base()

class Acquisto(Base):
    __tablename__ = "acquisti"
    
    id = Column(Integer, primary_key=True, index=True)
    id_acquisto_univoco = Column(String, unique=True, index=True, nullable=False)
    dove_acquistato = Column(String, nullable=False)
    venditore = Column(String, nullable=False)
    costo_acquisto = Column(Float, nullable=False)
    costi_accessori = Column(Float, default=0.0)
    data_pagamento = Column(Date, nullable=True)
    data_consegna = Column(Date, nullable=True)
    note = Column(Text, nullable=True)
    acquirente = Column(String(100), default="Alessio")
    
    # NUOVI CAMPI per gestione problemi
    problema_tipo = Column(String(50), nullable=True)  # 'pacco_perso', 'prodotti_non_conformi', etc.
    problema_descrizione = Column(Text, nullable=True)
    problema_data_segnalazione = Column(DateTime, nullable=True)
    problema_segnalato = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    prodotti = relationship("Prodotto", back_populates="acquisto", cascade="all, delete-orphan")
    
    # Proprietà calcolate
    @property 
    def numero_prodotti(self):
        """Numero totale di prodotti in questo acquisto"""
        return len(self.prodotti)
    
    @property
    def prodotti_venduti(self):
        """Numero di prodotti venduti"""
        return len([p for p in self.prodotti if p.venduto])
    
    @property
    def prodotti_senza_seriali(self):
        """Numero di prodotti senza seriali"""
        return len([p for p in self.prodotti if not p.seriale or p.seriale.strip() in ['', '???', 'N/A']])
    
    @property
    def completamente_venduto(self):
        """True se tutti i prodotti sono stati venduti"""
        if not self.prodotti:
            return False
        return all(p.venduto for p in self.prodotti)
    
    @property
    def costo_totale(self):
        """Costo totale (acquisto + accessori)"""
        return float(self.costo_acquisto or 0) + float(self.costi_accessori or 0)
    
    @property
    def ricavo_totale(self):
        """Ricavo totale da tutte le vendite"""
        return sum(p.ricavo_vendita for p in self.prodotti if p.venduto)
    
    @property
    def margine_totale(self):
        """Margine totale (ricavi - costi)"""
        return self.ricavo_totale - self.costo_totale
    
    @property
    def margine_percentuale(self):
        """Margine percentuale"""
        if self.costo_totale == 0:
            return 0
        return (self.margine_totale / self.costo_totale) * 100
    
    @property
    def giorni_attesa(self):
        """Giorni di attesa se l'acquisto non è ancora arrivato"""
        if self.data_consegna:
            return None  # Se è già arrivato, non c'è attesa
        
        # Calcola giorni dall'acquisto/pagamento a oggi
        if self.data_pagamento:
            return (date.today() - self.data_pagamento).days
        else:
            # Se non c'è data pagamento, usa la data di creazione
            return (date.today() - self.created_at.date()).days
    
    @property
    def giorni_stock(self):
        """Giorni in stock dall'arrivo (se arrivato)"""
        if not self.data_consegna:
            return None
        return (date.today() - self.data_consegna).days
    
    @property
    def giorni_stock_medio(self):
        """Giorni medi in stock per prodotti venduti"""
        if not self.data_consegna:
            return None
            
        prodotti_venduti = [p for p in self.prodotti if p.vendite]
        if not prodotti_venduti:
            return None
            
        giorni_totali = 0
        count = 0
        
        for prodotto in prodotti_venduti:
            for vendita in prodotto.vendite:
                if vendita.canale_vendita != "RIPARAZIONI":  # Escludi fotorip
                    giorni = (vendita.data_vendita - self.data_consegna).days
                    giorni_totali += giorni
                    count += 1
        
        return giorni_totali / count if count > 0 else None
    
    @property
    def problematico(self):
        """True se l'acquisto ha problemi che richiedono attenzione (include problemi segnalati)"""
        problemi = []
        
        # Problema segnalato manualmente
        if self.problema_segnalato:
            problemi.append("problema_segnalato")
        
        # Non ancora arrivato
        if not self.data_consegna:
            problemi.append("non_arrivato")
        
        # Prodotti senza seriali
        if self.prodotti_senza_seriali > 0:
            problemi.append("senza_seriali")
        
        # Vendita lenta (se arrivato da più di 30 giorni e non completamente venduto)
        if self.data_consegna and not self.completamente_venduto:
            giorni_stock = (date.today() - self.data_consegna).days
            if giorni_stock > 30:
                problemi.append("vendita_lenta")
        
        # Margine basso (se ha vendite)
        if self.prodotti_venduti > 0:
            # Calcola marginalità business (escluso fotorip)
            ricavi_business = sum(
                sum(v.ricavo_netto for v in p.vendite if v.canale_vendita != "RIPARAZIONI")
                for p in self.prodotti if p.vendite
            )
            
            # Investimento proporzionale solo per prodotti business
            prodotti_business = [p for p in self.prodotti 
                               if not any(v.canale_vendita == "RIPARAZIONI" for v in p.vendite)]
            
            if prodotti_business:
                costo_per_prodotto = self.costo_totale / len(self.prodotti)
                investimento_business = costo_per_prodotto * len(prodotti_business)
                
                if investimento_business > 0:
                    margine_percentuale = ((ricavi_business - investimento_business) / investimento_business * 100)
                    if margine_percentuale < 25:
                        problemi.append("margine_basso")
        
        return len(problemi) > 0
    
    @property
    def problemi_list(self):
        """Lista testuale dei problemi (include problemi segnalati)"""
        problemi = []
        
        # Problemi segnalati manualmente
        if self.problema_segnalato and self.problema_tipo:
            problemi.append(self.problema_tipo.replace('_', ' ').title())
        
        # Problemi automatici
        if not self.data_consegna and not self.problema_segnalato:
            problemi.append("Non arrivato")
        if self.prodotti_senza_seriali > 0:
            problemi.append(f"{self.prodotti_senza_seriali} senza seriali")
        if self.data_consegna and not self.completamente_venduto:
            giorni_stock = (date.today() - self.data_consegna).days
            if giorni_stock > 60:
                problemi.append("Vendita molto lenta")
            elif giorni_stock > 30:
                problemi.append("Vendita lenta")
        
        return problemi
    
    @property
    def urgenza_score(self):
        """Score di urgenza 0-100 (include problemi segnalati)"""
        score = 0
        
        # Problema segnalato manualmente - alta priorità
        if self.problema_segnalato:
            score += 50  # Base score alto per problemi segnalati
            
            # Score aggiuntivo per tipo problema
            if self.problema_tipo in ['pacco_perso', 'prodotti_danneggiati']:
                score += 30
            elif self.problema_tipo in ['prodotti_non_conformi', 'problema_venditore']:
                score += 20
            elif self.problema_tipo == 'ritardo_consegna':
                score += 15
        
        # Non arrivato (solo se non c'è problema segnalato)
        if not self.data_consegna and not self.problema_segnalato:
            giorni_attesa = self.giorni_attesa or 0
            if giorni_attesa > 21:
                score += 40
            elif giorni_attesa > 14:
                score += 30
            elif giorni_attesa > 7:
                score += 20
        
        # Seriali mancanti
        if self.prodotti_senza_seriali > 0:
            score += min(30, self.prodotti_senza_seriali * 10)
        
        # Vendite lente
        if self.giorni_stock and self.giorni_stock > 30 and not self.completamente_venduto:
            prodotti_non_venduti = len([p for p in self.prodotti if not p.vendite])
            if prodotti_non_venduti > 0:
                score += min(30, (self.giorni_stock - 30) // 15 * 10)
        
        return min(100, score)

class Prodotto(Base):
    __tablename__ = "prodotti"
    
    id = Column(Integer, primary_key=True, index=True)
    acquisto_id = Column(Integer, ForeignKey("acquisti.id"), nullable=False)
    seriale = Column(String, unique=True, nullable=True, index=True)
    prodotto_descrizione = Column(Text, nullable=False)
    note_prodotto = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    acquisto = relationship("Acquisto", back_populates="prodotti")
    vendite = relationship("Vendita", back_populates="prodotto", cascade="all, delete-orphan")
    
    # Proprietà calcolate
    @property
    def venduto(self):
        """True se il prodotto è stato venduto"""
        return len(self.vendite) > 0
    
    @property 
    def ricavo_vendita(self):
        """Ricavo totale dalle vendite di questo prodotto"""
        return sum(v.ricavo_netto for v in self.vendite)
    
    @property
    def giorni_in_stock(self):
        """Giorni in stock dall'arrivo (se non venduto)"""
        if self.venduto or not self.acquisto.data_consegna:
            return None
        return (date.today() - self.acquisto.data_consegna).days
    
    @property
    def costo_unitario(self):
        """Costo unitario di questo prodotto"""
        if not self.acquisto or self.acquisto.numero_prodotti == 0:
            return 0
        return self.acquisto.costo_totale / self.acquisto.numero_prodotti
    
    @property
    def margine_vendita(self):
        """Margine totale dalle vendite di questo prodotto"""
        return self.ricavo_vendita - self.costo_unitario
    
    @property
    def margine_percentuale(self):
        """Margine percentuale di questo prodotto"""
        if self.costo_unitario == 0:
            return 0
        return (self.margine_vendita / self.costo_unitario) * 100
    
    @property
    def giorni_vendita_media(self):
        """Giorni medi dall'arrivo alla vendita"""
        if not self.vendite or not self.acquisto.data_consegna:
            return None
        
        giorni_totali = 0
        count = 0
        for vendita in self.vendite:
            if vendita.canale_vendita != "RIPARAZIONI":  # Escludi fotorip
                giorni = (vendita.data_vendita - self.acquisto.data_consegna).days
                giorni_totali += giorni
                count += 1
        
        return giorni_totali / count if count > 0 else None

class Vendita(Base):
    __tablename__ = "vendite"
    
    id = Column(Integer, primary_key=True, index=True)
    prodotto_id = Column(Integer, ForeignKey("prodotti.id"), nullable=False)
    data_vendita = Column(Date, nullable=False)
    canale_vendita = Column(String, nullable=False)
    prezzo_vendita = Column(Float, nullable=False)
    commissioni = Column(Float, default=0.0)
    note_vendita = Column(Text, nullable=True)
    synced_from_invoicex = Column(Boolean, default=False)
    invoicex_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    prodotto = relationship("Prodotto", back_populates="vendite")
    
    # Proprietà calcolate
    @property
    def ricavo_netto(self):
        """Ricavo netto (prezzo - commissioni)"""
        return float(self.prezzo_vendita or 0) - float(self.commissioni or 0)
    
    @property
    def seriale(self):
        """Seriale del prodotto venduto"""
        return self.prodotto.seriale if self.prodotto else None
    
    @property
    def margine(self):
        """Margine di questa vendita"""
        if not self.prodotto:
            return 0
        return self.ricavo_netto - self.prodotto.costo_unitario
    
    @property
    def margine_percentuale(self):
        """Margine percentuale di questa vendita"""
        if not self.prodotto or self.prodotto.costo_unitario == 0:
            return 0
        return (self.margine / self.prodotto.costo_unitario) * 100
    
    @property
    def giorni_vendita(self):
        """Giorni dall'arrivo alla vendita"""
        if not self.prodotto or not self.prodotto.acquisto.data_consegna:
            return None
        return (self.data_vendita - self.prodotto.acquisto.data_consegna).days
    
    @property
    def roi_percentuale(self):
        """ROI percentuale di questa vendita"""
        return self.margine_percentuale  # Alias per coerenza
    
    @property
    def tipo_vendita(self):
        """Classificazione tipo di vendita"""
        if self.canale_vendita == "RIPARAZIONI":
            return "fotorip"
        elif self.margine_percentuale >= 25:
            return "ottima"
        elif self.margine_percentuale >= 15:
            return "buona"
        elif self.margine_percentuale >= 5:
            return "accettabile"
        else:
            return "critica"
    
    @property
    def velocita_vendita(self):
        """Classificazione velocità di vendita"""
        giorni = self.giorni_vendita
        if giorni is None:
            return "sconosciuta"
        elif giorni <= 7:
            return "molto_veloce"
        elif giorni <= 30:
            return "veloce"
        elif giorni <= 60:
            return "normale"
        elif giorni <= 90:
            return "lenta"
        else:
            return "molto_lenta"