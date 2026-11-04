from datetime import datetime, date, timezone
from sqlalchemy import (
    Column,
    String,
    Numeric,
    Date,
    DateTime,
    Integer,
    BigInteger,
    ForeignKey,
    Text,
    Index
)
from sqlalchemy.orm import relationship
from backend.app.db.session import Base

class Bond(Base):
    __tablename__ = "bonds"

    ticker = Column(String(20), primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    isin = Column(String(20), nullable=True)
    currency = Column(String(10), nullable=False)  # 'USD', 'ARS'
    law = Column(String(15), nullable=False)       # 'ARG', 'NY'
    bond_type = Column(String(30), nullable=False, index=True)  # 'HARD_DOLLAR', 'CER', 'TASA_FIJA', 'DUAL', 'TAMAR', 'BOPREAL', 'DOLLAR_LINKED'
    amortization_type = Column(String(30), nullable=True)  # 'BULLET', 'SEMESTRAL', 'MENSUAL'
    start_date = Column(Date, nullable=True)
    maturity_date = Column(Date, nullable=False, index=True)
    coupon_rate = Column(Numeric(8, 4), nullable=True)
    base_nominal = Column(Numeric(12, 2), default=100.0)
    description = Column(Text, nullable=True)
    short_description = Column(String(200), nullable=True)

    # Relaciones
    snapshots = relationship("PriceSnapshot", back_populates="bond", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Bond {self.ticker} ({self.bond_type} - {self.law})>"


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("bonds.ticker"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    settlement_type = Column(String(10), nullable=False, default="24HS") # 'CI', '24HS'
    
    price_ars = Column(Numeric(14, 4), nullable=True)
    price_mep = Column(Numeric(14, 4), nullable=True) # Especie D
    price_ccl = Column(Numeric(14, 4), nullable=True) # Especie C
    last_price = Column(Numeric(14, 4), nullable=True) # Precio en especie principal
    
    day_difference = Column(Numeric(8, 4), nullable=True)
    volume_millions = Column(Numeric(14, 4), nullable=True)
    technical_value = Column(Numeric(14, 4), nullable=True)
    parity_percentage = Column(Numeric(8, 3), nullable=True)
    ytm_percentage = Column(Numeric(8, 4), nullable=True) # TIR
    tem_percentage = Column(Numeric(8, 4), nullable=True) # Tasa Efectiva Mensual
    tna_percentage = Column(Numeric(8, 4), nullable=True) # TNA
    modified_duration = Column(Numeric(8, 4), nullable=True)
    
    # Relación
    bond = relationship("Bond", back_populates="snapshots")

    __table_args__ = (
        Index("idx_snapshot_ticker_time", "ticker", "timestamp"),
        Index("idx_snapshot_settlement", "ticker", "settlement_type"),
    )

    def __repr__(self):
        return f"<PriceSnapshot {self.ticker} @ {self.timestamp}: P={self.last_price} TIR={self.ytm_percentage}%>"


class ArbitrageSignal(Base):
    __tablename__ = "arbitrage_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    strategy_name = Column(String(50), nullable=False, index=True) # 'LAW_PREMIUM', 'RELATIVE_VALUE_CURVE', 'BREAKEVEN_CER_FIXED', 'DUAL_TAMAR_CER'
    leg_sell_ticker = Column(String(20), nullable=False)
    leg_buy_ticker = Column(String(20), nullable=False)
    metric_name = Column(String(40), nullable=False) # 'SPREAD_PRICE_RATIO', 'SPREAD_YIELD_BPS', 'BREAKEVEN_TEM'
    metric_value = Column(Numeric(12, 4), nullable=False)
    historical_mean = Column(Numeric(12, 4), nullable=True)
    std_deviations = Column(Numeric(6, 2), nullable=True)
    action_recommended = Column(String(40), nullable=False) # 'ROTAR_A_NY', 'ROTAR_A_ARG', 'SWAP_DURACION', 'COMPRAR_CER', 'COMPRAR_TASA_FIJA'
    status = Column(String(20), default="ACTIVE", index=True) # 'ACTIVE', 'EXECUTED', 'EXPIRED'
    notes = Column(Text, nullable=True)

    def __repr__(self):
        return f"<ArbitrageSignal {self.strategy_name}: Sell {self.leg_sell_ticker} -> Buy {self.leg_buy_ticker} ({self.action_recommended})>"


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, index=True, nullable=False)
    name = Column(String(40), index=True, nullable=False) # 'IPC', 'CER', 'TAMAR', 'DOLAR_OFICIAL', 'DOLAR_MEP', 'DOLAR_CCL'
    value = Column(Numeric(14, 4), nullable=False)
    source = Column(String(60), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_macro_date_name", "date", "name", unique=True),
    )

    def __repr__(self):
        return f"<MacroIndicator {self.name} on {self.date}: {self.value}>"
