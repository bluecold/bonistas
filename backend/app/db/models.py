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
    Index,
    Float,
    Boolean,
    JSON,
)
from sqlalchemy.orm import relationship
from backend.app.db.types import UTCDateTime
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
    timestamp = Column(UTCDateTime(), default=lambda: datetime.now(timezone.utc), index=True)
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
    timestamp = Column(UTCDateTime(), default=lambda: datetime.now(timezone.utc), index=True)
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
    # Persistencia de señales (etapa 3): una señal es la misma mientras siga vigente
    signal_key = Column(String(120), nullable=True, index=True)   # estrategia|venta|compra|acción
    first_seen = Column(UTCDateTime(), nullable=True)
    last_seen = Column(UTCDateTime(), nullable=True)
    net_profit_pct = Column(Float, nullable=True)                 # ganancia neta estimada (%)
    confirmation = Column(String(30), nullable=True)              # 'DEMORA_20MIN' | 'TIEMPO_REAL'
    details = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<ArbitrageSignal {self.strategy_name}: Sell {self.leg_sell_ticker} -> Buy {self.leg_buy_ticker} ({self.action_recommended})>"


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, index=True, nullable=False)
    name = Column(String(40), index=True, nullable=False) # 'IPC', 'CER', 'TAMAR', 'DOLAR_OFICIAL', 'DOLAR_MEP', 'DOLAR_CCL'
    value = Column(Numeric(14, 4), nullable=False)
    source = Column(String(60), nullable=True)
    created_at = Column(UTCDateTime(), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_macro_date_name", "date", "name", unique=True),
    )

    def __repr__(self):
        return f"<MacroIndicator {self.name} on {self.date}: {self.value}>"


class BookQuote(Base):
    """
    Mejor punta compradora / vendedora de una especie en un plazo, tal como la publica la
    fuente (BYMA Open Data con 20 min de demora, o Bull Market en tiempo real).
    Se guarda una fila nueva solo cuando algo cambió respecto de la anterior.
    """
    __tablename__ = "book_quotes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(UTCDateTime(), default=lambda: datetime.now(timezone.utc), index=True)
    source = Column(String(20), nullable=False)          # 'BYMA', 'BULLMARKET'
    symbol = Column(String(20), nullable=False)          # especie: AL30, AL30D, AL30C
    base_ticker = Column(String(20), nullable=False, index=True)  # AL30 para las tres especies
    currency = Column(String(5), nullable=False)         # 'ARS', 'MEP', 'CCL'
    settlement = Column(String(5), nullable=False)       # 'CI', '24HS'
    bid = Column(Float, nullable=True)
    bid_qty = Column(Float, nullable=True)
    ask = Column(Float, nullable=True)
    ask_qty = Column(Float, nullable=True)
    last = Column(Float, nullable=True)
    prev_close = Column(Float, nullable=True)
    volume_nominal = Column(Float, nullable=True)
    volume_amount = Column(Float, nullable=True)
    trades = Column(Integer, nullable=True)
    trade_time = Column(String(12), nullable=True)       # hora de la última operación según la fuente
    maturity_date = Column(Date, nullable=True)
    # Profundidad {"bids": [[precio, cantidad], ...], "asks": [...]} si la fuente la publica
    depth = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_book_symbol_settlement", "source", "symbol", "settlement", "id"),
    )

    def __repr__(self):
        return f"<BookQuote {self.source} {self.symbol} {self.settlement}: {self.bid} / {self.ask}>"


class ReferenceBond(Base):
    """
    Datos de referencia diarios por ticker base (CompararBonos): flujos futuros por 100 VN,
    valor técnico, pago final, etc. Se reemplaza en cada actualización diaria.
    """
    __tablename__ = "reference_bonds"

    ticker_base = Column(String(20), primary_key=True)
    source = Column(String(30), nullable=False, default="COMPARARBONOS")
    fetched_at = Column(UTCDateTime(), default=lambda: datetime.now(timezone.utc))
    market_date = Column(Date, nullable=True)            # rueda a la que corresponden los datos
    settlement_date = Column(Date, nullable=True)        # liquidación que usa la fuente (24hs)
    tipo = Column(String(30), nullable=True)
    currency = Column(String(10), nullable=True)
    flows = Column(JSON, nullable=False, default=list)   # [["2027-01-09", 8.24], ...]
    technical_value = Column(Float, nullable=True)
    residual_capital = Column(Float, nullable=True)
    final_payment = Column(Float, nullable=True)
    yield_is_real = Column(Boolean, default=False)
    flows_cer_adjusted = Column(Boolean, default=False)
    ref_ytm_pct = Column(Float, nullable=True)
    ref_duration = Column(Float, nullable=True)
    payment_structure = Column(String(200), nullable=True)
    species = Column(JSON, nullable=False, default=list)

    def __repr__(self):
        return f"<ReferenceBond {self.ticker_base} ({self.tipo}) {len(self.flows or [])} flujos>"


class UserSetting(Base):
    """Parámetros editables desde el dashboard (clave -> valor JSON)."""
    __tablename__ = "user_settings"

    key = Column(String(60), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(UTCDateTime(), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class Alert(Base):
    """
    Historial de alertas del dashboard (y de las notificaciones de Windows): oportunidades
    nuevas o confirmadas en tiempo real, sesión de Bull Market vencida, fuente caída/recuperada.
    """
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(UTCDateTime(), default=lambda: datetime.now(timezone.utc), index=True)
    kind = Column(String(30), nullable=False)        # OPORTUNIDAD, CONFIRMADA, SESION_VENCIDA, FUENTE_CAIDA, FUENTE_OK, PRUEBA
    severity = Column(String(10), nullable=False)    # OPORTUNIDAD / AVISO / INFO
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=True)
    signal_id = Column(Integer, nullable=True)
    dedupe_key = Column(String(200), nullable=True, index=True)
    notified = Column(Boolean, default=False)        # se mostró notificación de Windows
    read = Column(Boolean, default=False)

