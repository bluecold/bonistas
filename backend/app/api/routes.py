import logging
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from datetime import date

from backend.app.db.session import get_db
from backend.app.db.models import Bond, BookQuote, MacroIndicator, PriceSnapshot, ArbitrageSignal
from backend.app.schemas.bond import BondResponse
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.schemas.valuation import (
    CashFlowItemResponse,
    ValuationRequest,
    ValuationResponse,
    BreakevenResponse,
    LawSpreadPair,
    SwapRequest,
    SwapResponse
)
from backend.app.quant import (
    generate_cashflows,
    calculate_accrued_interest,
    calculate_residual_capital,
    calculate_technical_value,
    calculate_parity,
    calculate_ytm,
    calculate_duration_and_md,
    calculate_tem,
    calculate_tna,
    calculate_breakeven_inflation,
    calculate_law_spread,
    simulate_bond_swap
)
from backend.app.schemas.arbitrage import (
    ArbitrageSignalBase,
    ArbitrageSignalCreate,
    ArbitrageSignalResponse
)
from backend.app.arbitrage.engine import ArbitrageEngine
from backend.app.services.ingestion_service import IngestionService
from backend.app.quant.cashflows import base_ticker, has_verified_schedule, CashFlowItem
from backend.app.services.market_book_service import MarketBookService
from backend.app.services.reference_data_service import ReferenceDataService
from backend.app.services.market_calendar import MarketCalendar, next_business_day
from backend.app.services.source_health import source_health
from backend.app.services.quote_table import consolidate
from backend.app.services.on_cashflows import OnCashflowService, OnCashflowUnavailable, source_of
from backend.app.data.bonistas_payments_client import bonistas_payments
from backend.app.services.bullmarket_session import InvalidCookieError
from backend.app.services.alert_service import AlertService, get_prefs, update_prefs
from backend.app.services.price_history_service import PriceHistoryService
from backend.app.services import bond_profile_service as profile
from backend.app.services import swap_pricing
from backend.app.services.quote_table import live_price
from backend.app.services.trading_settings import get_params, update_params
from backend.app.config import settings

router = APIRouter()
ingestion_service = IngestionService()
market_book_service = MarketBookService()
bullmarket_session = market_book_service.bm_session
on_cashflow_service = OnCashflowService(bullmarket_session, bonistas=bonistas_payments)
logger = logging.getLogger(__name__)
arbitrage_engine = ArbitrageEngine(ingestion_service, book_service=market_book_service)
alert_service = AlertService()
price_history_service = PriceHistoryService()
arbitrage_engine.listeners.append(alert_service.on_evaluation)


def check_source_alerts(db: Session) -> None:
    """Alertas de sesión vencida / fuente caída después de consultar las fuentes."""
    alert_service.check_sources(db, source_health.snapshot(),
                                bm_just_expired=market_book_service.bm_just_expired,
                                bm_status=bullmarket_session.status)
reference_service = ReferenceDataService()
market_calendar = MarketCalendar()

@router.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": "Sistema de Arbitraje de Bonos Argentinos",
        "version": settings.VERSION
    }

@router.get("/bonds", response_model=List[BondResponse], tags=["Bonds"])
def list_bonds(
    bond_type: Optional[str] = Query(None, description="Filtrar por tipo: HARD_DOLLAR, CER, TASA_FIJA, DUAL, BOPREAL, DOLLAR_LINKED"),
    law: Optional[str] = Query(None, description="Filtrar por ley: ARG, NY"),
    db: Session = Depends(get_db)
):
    """Lista todos los títulos públicos registrados en el maestro."""
    query = select(Bond)
    if bond_type:
        query = query.where(Bond.bond_type == bond_type.upper())
    if law:
        query = query.where(Bond.law == law.upper())
    
    bonds = db.execute(query).scalars().all()
    return bonds

@router.get("/bonds/{ticker}", response_model=BondResponse, tags=["Bonds"])
def get_bond(ticker: str, db: Session = Depends(get_db)):
    """Obtiene el detalle y metadatos de un bono específico por su ticker."""
    bond = db.execute(select(Bond).where(Bond.ticker == ticker.upper())).scalar_one_or_none()
    if not bond:
        raise HTTPException(status_code=404, detail=f"Bono con ticker '{ticker}' no encontrado.")
    return bond

@router.get("/quotes", response_model=List[BondQuoteView], tags=["Market Data"])
def get_latest_quotes(
    bond_type: Optional[str] = Query(None, description="Filtrar por tipo: HARD_DOLLAR, CER, TASA_FIJA, DUAL, BOPREAL, DOLLAR_LINKED"),
    settlement: str = Query("24HS", pattern="^(?i:CI|24HS)$", description="Plazo de liquidación: CI o 24HS"),
    db: Session = Depends(get_db)
):
    """Obtiene las cotizaciones y métricas más recientes de los bonos para un plazo de liquidación."""
    quotes = ingestion_service.get_latest_quotes(db, bond_type=bond_type, settlement=settlement)
    return quotes


@router.get("/quotes/table", tags=["Market Data"])
def get_quotes_table(
    bond_type: Optional[str] = Query(None, description="Filtrar por tipo: HARD_DOLLAR, ON, CER, TASA_FIJA, ..."),
    settlement: str = Query("24HS", pattern="^(?i:CI|24HS)$", description="Plazo de liquidación: CI o 24HS"),
    db: Session = Depends(get_db),
):
    """
    Una fila por instrumento (pesos / MEP / cable juntos). Con sesión de Bull Market vigente, los
    precios son el último operado en Bull Market; si no, los de bonistas.com.
    """
    st = settlement.upper()
    quotes = [q.model_dump() for q in
              ingestion_service.get_latest_quotes(db, bond_type=bond_type, settlement=st)]
    live_books: Dict[str, Any] = {}
    # Bonos con prioridad sobre ON si un símbolo viniera en los dos índices
    for source in (market_book_service.BULLMARKET_ON, market_book_service.BULLMARKET):
        keys = market_book_service.live_keys(source, max_age_seconds=settings.BULLMARKET_MAX_AGE_SECONDS)
        if not keys:
            continue
        for b in market_book_service.latest_books(db, source=source, settlement=st):
            if (b.symbol, b.settlement) in keys:
                live_books[b.symbol] = b
    return {"settlement": st, "live_source": "BULLMARKET" if live_books else None,
            "rows": consolidate(quotes, live_books, market_book_service.on_names)}


@router.get("/macro", tags=["Macro"])
def get_macro_indicators(db: Session = Depends(get_db)):
    """Obtiene las cotizaciones de tipos de cambio y variables macroeconómicas recientes."""
    indicators = db.execute(select(MacroIndicator).order_by(MacroIndicator.date.desc())).scalars().all()
    res = {}
    for ind in indicators:
        if ind.name not in res:
            res[ind.name] = {
                "value": float(ind.value),
                "date": ind.date.isoformat(),
                "source": ind.source
            }
    return res

@router.post("/ingest", tags=["Ingestion"])
async def trigger_ingestion(db: Session = Depends(get_db)):
    """
    Sincronización manual inmediata (ignora el horario de mercado): analítica de Bonistas,
    dólares de referencia, libro de BYMA (puntas CI y 24hs) con la caución a 1 día y, si hay
    sesión, libro de Bull Market en tiempo real.
    """
    details: Dict[str, Any] = {}
    errors: List[str] = []
    try:
        details.update(await ingestion_service.ingest_market_data(db))
    except Exception as e:
        errors.append(f"Bonistas: {e}")
    byma = await market_book_service.ingest_byma(db)
    details["byma"] = byma
    if "books_error" in byma:
        errors.append(f"BYMA: {byma['books_error']}")
    bm = await market_book_service.ingest_bullmarket(db)
    details["bullmarket"] = bm
    check_source_alerts(db)
    if "error" in bm:
        errors.append(f"Bull Market: {bm['error']}")
    bonistas_failed = any(e.startswith("Bonistas") for e in errors)
    if bonistas_failed and "books" not in byma and "books" not in bm:
        raise HTTPException(status_code=502, detail="; ".join(errors))
    return {
        "status": "success" if not errors else "partial",
        "message": "Ingesta de mercado completada",
        "errors": errors,
        "details": details,
    }


@router.post("/reference/refresh", tags=["Ingestion"])
async def trigger_reference_refresh(db: Session = Depends(get_db)):
    """Actualiza ya los datos de referencia diarios (flujos de CompararBonos, CER/TAMAR/A3500 del BCRA, IPC)."""
    return await reference_service.refresh(db)


@router.get("/reference/{ticker}", tags=["Quant Analytics"])
def get_reference_bond(ticker: str, db: Session = Depends(get_db)):
    """Datos de referencia (CompararBonos) de un bono: flujos, VT, pago final, especies."""
    ref = ReferenceDataService.get_reference(db, ticker)
    if ref is None:
        raise HTTPException(status_code=404, detail=f"Sin datos de referencia para '{ticker}'.")
    return {
        "ticker_base": ref.ticker_base, "tipo": ref.tipo, "currency": ref.currency,
        "market_date": ref.market_date, "settlement_date": ref.settlement_date,
        "technical_value": ref.technical_value, "residual_capital": ref.residual_capital,
        "final_payment": ref.final_payment, "yield_is_real": ref.yield_is_real,
        "flows_cer_adjusted": ref.flows_cer_adjusted, "ref_ytm_pct": ref.ref_ytm_pct,
        "ref_duration": ref.ref_duration, "payment_structure": ref.payment_structure,
        "species": ref.species, "flows": ref.flows, "fetched_at": ref.fetched_at,
    }


@router.get("/books", tags=["Market Data"])
def get_books(
    settlement: Optional[str] = Query(None, pattern="^(?i:CI|24HS)$", description="CI o 24HS (default: ambos)"),
    base_ticker: Optional[str] = Query(None, description="Ticker base, ej: AL30 (trae AL30, AL30D y AL30C)"),
    source: str = Query("BYMA", description="Fuente: BYMA (20 min de demora) o BULLMARKET"),
    db: Session = Depends(get_db),
):
    """Últimas puntas compradora/vendedora por especie y plazo."""
    rows = market_book_service.latest_books(db, source=source.upper(), settlement=settlement,
                                             base_ticker=base_ticker)
    return [
        {
            "symbol": r.symbol, "base_ticker": r.base_ticker, "currency": r.currency,
            "settlement": r.settlement, "bid": r.bid, "bid_qty": r.bid_qty, "ask": r.ask,
            "ask_qty": r.ask_qty, "last": r.last, "prev_close": r.prev_close,
            "volume_nominal": r.volume_nominal, "trades": r.trades, "trade_time": r.trade_time,
            "maturity_date": r.maturity_date, "timestamp": r.timestamp, "source": r.source,
            "depth": r.depth,
        }
        for r in rows
    ]


@router.get("/status", tags=["Health"])
async def get_status(db: Session = Depends(get_db)):
    """Estado de las fuentes de datos y del horario de mercado (para el dashboard)."""
    from backend.app.services import holiday_service
    window = await market_calendar.today()
    today = date.fromisoformat(window.to_dict()["date"])
    return {
        "settlement_24hs": next_business_day(today).isoformat(),
        "holidays": holiday_service.upcoming(db, today),
        "market": window.to_dict(),
        "market_hours_only": settings.MARKET_HOURS_ONLY,
        "polling_interval_seconds": settings.POLLING_INTERVAL_SECONDS,
        "sources": source_health.snapshot(),
        "bullmarket": bullmarket_session.to_dict(),
    }


# ==========================================
# BULL MARKET (TIEMPO REAL) — SESIÓN DEL TRADER
# ==========================================

class BullMarketCookieRequest(BaseModel):
    cookie: str = Field(..., min_length=3, max_length=64000)


@router.get("/bullmarket/session", tags=["Bull Market"])
def get_bullmarket_session():
    """Estado de la sesión de Bull Market. Nunca devuelve la cookie."""
    return bullmarket_session.to_dict()


@router.put("/bullmarket/session", tags=["Bull Market"])
async def set_bullmarket_session(req: BullMarketCookieRequest, db: Session = Depends(get_db)):
    """
    Guarda la cookie de sesión (copiada del navegador con la sesión iniciada) en secrets/ y
    prueba la conexión con una consulta de bonos. La cookie no se devuelve ni se registra.
    """
    try:
        bullmarket_session.set_cookie(req.cookie)
    except InvalidCookieError as e:
        raise HTTPException(status_code=422, detail=str(e))
    result = await market_book_service.ingest_bullmarket(db)
    market_book_service.bm_just_expired = False     # el trader está mirando: no hace falta notificar
    status = bullmarket_session.to_dict()
    status["test"] = {k: v for k, v in result.items() if k in ("rows", "books", "error")}
    if status["status"] == "ACTIVA":
        try:
            if reference_service.bullmarket_cashflows_day != date.today():
                status["cashflows"] = {k: v for k, v in (await reference_service.apply_bullmarket_cashflows(
                    db, bullmarket_session.get_cookie())).items() if k in ("verified", "imminent", "bullmarket_schedules")}
        except Exception as e:
            db.rollback()
            status["cashflows_error"] = str(e)[:200]
        arbitrage_engine.evaluate_all_strategies(db)
    return status


@router.delete("/bullmarket/session", tags=["Bull Market"])
def delete_bullmarket_session():
    """Borra la cookie guardada (vuelve a usar solo BYMA con demora)."""
    bullmarket_session.clear()
    market_book_service.live.pop("BULLMARKET", None)
    return bullmarket_session.to_dict()

# ==========================================
# ENDPOINTS CUANTITATIVOS (FASE 2)
# ==========================================

def _find_bond(db: Session, ticker: str) -> Optional[Bond]:
    """Busca un bono por ticker exacto o por su ticker base (AL30D -> AL30)."""
    t = ticker.strip().upper()
    bond = db.execute(select(Bond).where(Bond.ticker == t)).scalar_one_or_none()
    if bond is None and base_ticker(t) != t:
        bond = db.execute(select(Bond).where(Bond.ticker == base_ticker(t))).scalar_one_or_none()
    return bond


def _latest_snapshot(db: Session, ticker: str, settlement: str = "24HS") -> Optional[PriceSnapshot]:
    """Último snapshot de un ticker en un plazo de liquidación concreto (CI o 24HS)."""
    return db.execute(
        select(PriceSnapshot)
        .where(PriceSnapshot.ticker == ticker.upper(), PriceSnapshot.settlement_type == settlement.upper())
        .order_by(PriceSnapshot.id.desc())
    ).scalars().first()


def _resolve_settlement_date(settlement_date: Optional[date], settlement_type: str) -> date:
    """Fecha de liquidación: la indicada, o hoy (CI) / próximo día hábil (24HS)."""
    if settlement_date:
        return settlement_date
    today = date.today()
    return today if settlement_type.upper() == "CI" else next_business_day(today)


def _cashflow_source(db: Session, ticker: str):
    """
    Decide de dónde salen los flujos de un bono:
    1. Cronograma propio verificado (Bonares / Globales 2020).
    2. Flujos de referencia diarios de CompararBonos (LECAP, BONCAP, CER, BOPREAL, tasa fija...).
    Devuelve (bond o None, reference o None). Lanza 404/422 si no hay ninguna fuente válida.
    """
    bond = _find_bond(db, ticker)
    if bond is not None and has_verified_schedule(bond.ticker):
        return bond, None
    ref = ReferenceDataService.get_reference(db, ticker)
    if ref is not None and ref.flows:
        return bond, ref
    if bond is None and ref is None:
        raise HTTPException(status_code=404, detail=f"Bono '{ticker}' no encontrado.")
    detail = f"Sin flujos disponibles para {ticker.upper()}"
    if ref is not None and ref.payment_structure:
        detail += f" (estructura: {ref.payment_structure})"
    detail += ". Duales, dollar linked y algunos CER/provinciales no publican flujos proyectables."
    raise HTTPException(status_code=422, detail=detail)


def _reference_cashflows(ref, s_date: date) -> List[CashFlowItem]:
    flows = [(d, amt) for d, amt in ReferenceDataService.flows_of(ref) if d > s_date]
    return [
        CashFlowItem(
            date=d, days_from_settlement=(d - s_date).days, interest_rate=0.0,
            coupon_amount=0.0, amortization_amount=0.0, total_cashflow=amt, residual_capital=0.0,
        )
        for d, amt in flows
    ]


@router.get("/bonds/{ticker}/cashflows", response_model=List[CashFlowItemResponse], tags=["Quant Analytics"])
async def get_bond_cashflows(
    ticker: str,
    settlement_date: Optional[date] = Query(None, description="Fecha de liquidación (default: próximo día hábil)"),
    db: Session = Depends(get_db)
):
    """
    Flujos de fondos futuros por 100 VN. Para Bonares/Globales se detalla renta, amortización y
    residual; para el resto (fuente CompararBonos) solo se conoce el flujo total de cada fecha.
    Las obligaciones negociables salen de Bull Market (con la sesión activa) o, sin sesión, del
    calendario de próximos pagos de bonistas.com.
    """
    on_bond = _find_bond(db, ticker)
    if on_bond is not None and on_bond.bond_type == "ON":
        s_date = _resolve_settlement_date(settlement_date, "24HS")
        try:
            sch = await on_cashflow_service.get(on_bond.ticker)
        except OnCashflowUnavailable as e:
            raise HTTPException(status_code=422, detail=str(e))
        pay = getattr(sch, "payment_currency", None)
        return [
            CashFlowItemResponse(
                date=r.date, days_from_settlement=(r.date - s_date).days, interest_rate=None,
                coupon_amount=r.coupon, amortization_amount=r.amortization, total_cashflow=r.total,
                residual_capital=r.residual, source=source_of(sch), currency=sch.currency,
                payment_currency=pay,
            )
            for r in sch.rows if r.date > s_date
        ]

    bond, ref = _cashflow_source(db, ticker)
    s_date = _resolve_settlement_date(settlement_date, "24HS")

    if ref is None:
        return [
            CashFlowItemResponse(
                date=cf.date, days_from_settlement=cf.days_from_settlement,
                interest_rate=cf.interest_rate, coupon_amount=cf.coupon_amount,
                amortization_amount=cf.amortization_amount, total_cashflow=cf.total_cashflow,
                residual_capital=cf.residual_capital, source="PROPIO",
            )
            for cf in generate_cashflows(bond.ticker, s_date, bond.maturity_date)
        ]

    source = ref.flows_source or "COMPARARBONOS"
    if ref.flows_detail:
        out = []
        for d, coupon, amort, total, residual in ref.flows_detail:
            d = date.fromisoformat(d)
            if d > s_date:
                out.append(CashFlowItemResponse(
                    date=d, days_from_settlement=(d - s_date).days, interest_rate=None,
                    coupon_amount=coupon, amortization_amount=amort, total_cashflow=total,
                    residual_capital=residual, source=source,
                ))
        return out
    return [
        CashFlowItemResponse(
            date=cf.date, days_from_settlement=cf.days_from_settlement,
            interest_rate=None, coupon_amount=None, amortization_amount=None,
            total_cashflow=cf.total_cashflow, residual_capital=None, source=source,
        )
        for cf in _reference_cashflows(ref, s_date)
    ]


# ==========================================
# FICHA DEL BONO
# ==========================================

async def _profile_model(db: Session, ticker: str, today: date) -> profile.BondModel:
    bond = _find_bond(db, ticker)
    if bond is None and ReferenceDataService.get_reference(db, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Bono '{ticker}' no encontrado.")
    on_schedule = None
    if bond is not None and bond.bond_type == "ON":
        try:
            on_schedule = await on_cashflow_service.get(bond.ticker)
        except OnCashflowUnavailable:
            on_schedule = None
    return profile.build_model(db, ticker, today, on_schedule=on_schedule)


def _profile_price(db: Session, model: profile.BondModel) -> Dict[str, Any]:
    """Precio actual de la especie de la ficha: Bull Market si está vigente, si no bonistas.com."""
    symbol = model.price_symbol
    out: Dict[str, Any] = {"symbol": symbol, "price": None, "source": None, "kind": None, "time": None,
                           "bid": None, "ask": None, "prev_close": None, "change_pct": None}
    for source in (market_book_service.BULLMARKET, market_book_service.BULLMARKET_ON):
        keys = market_book_service.live_keys(source, max_age_seconds=settings.BULLMARKET_MAX_AGE_SECONDS)
        if not keys or (symbol, "24HS") not in keys:
            continue
        book = next((b for b in market_book_service.latest_books(db, source=source, settlement="24HS")
                     if b.symbol == symbol), None)
        price, kind = live_price(book) if book is not None else (None, None)
        if price:
            out.update(price=price, source="BULLMARKET", kind=kind, time=book.trade_time,
                       bid=book.bid, ask=book.ask, prev_close=book.prev_close)
            break
    usd = model.flow_currency == "USD"
    if out["price"] is None:
        for t in dict.fromkeys((symbol, model.base)):
            snap = _latest_snapshot(db, t)
            if snap is None:
                continue
            value = (snap.price_mep if usd else snap.price_ars) or (snap.last_price if t == symbol else None)
            if value:
                out.update(price=float(value), source="BONISTAS", time=snap.timestamp.isoformat())
                break
    if out["prev_close"] is None:
        book = db.execute(
            select(BookQuote).where(BookQuote.symbol == symbol, BookQuote.settlement == "24HS",
                                    BookQuote.prev_close.is_not(None))
            .order_by(BookQuote.id.desc())).scalars().first()
        if book is not None:
            out["prev_close"] = book.prev_close
    if out["price"] and out["prev_close"]:
        out["change_pct"] = round((out["price"] / out["prev_close"] - 1.0) * 100.0, 2)
    return out


def _profile_reference_metrics(db: Session, model: profile.BondModel) -> Dict[str, Any]:
    """Métricas de bonistas.com de la misma especie, para lo que no se puede calcular con flujos propios."""
    for t in dict.fromkeys((model.price_symbol, model.base)):
        snap = _latest_snapshot(db, t)
        if snap is not None and snap.ytm_percentage is not None:
            f = lambda v: float(v) if v is not None else None
            return {"ytm_pct": f(snap.ytm_percentage), "modified_duration": f(snap.modified_duration),
                    "technical_value": f(snap.technical_value), "parity_pct": f(snap.parity_percentage),
                    "tem_pct": f(snap.tem_percentage)}
    return {}


async def _profile_on(db: Session, model: profile.BondModel) -> Optional[Dict[str, Any]]:
    """
    Bloque propio de las ON en la ficha: emisor, spread contra las otras ON de la empresa y contra
    el soberano, liquidez y moneda de pago. Reusa el análisis de valor relativo, acotado a las ON
    del mismo emisor (sus cronogramas se piden acá si todavía no se descargaron hoy).
    """
    bond = model.bond
    if bond is None or bond.bond_type != "ON":
        return None
    from backend.app.arbitrage.on_relative_value import analyze_ons, profile_block, sovereign_curve
    from backend.app.services.on_cashflows import on_base_tickers
    t = bond.ticker
    stem = t[:-1] if t[-1:] in ("O", "D", "C") else t
    bases = on_base_tickers(db)
    base = next((b for b in (stem + "O", stem + "D", stem + "C") if b in bases), t)
    issuers = ingestion_service.issuer_by_ticker
    issuer = next((issuers[x] for x in (base, t, stem + "D") if issuers.get(x)), None)
    group = [b for b in bases if issuer and issuers.get(b) == issuer]
    if base not in group:
        group.append(base)
    try:
        await on_cashflow_service.prefetch(group, mark_day=False)
    except Exception as e:
        logger.warning(f"Ficha ON {t}: cronogramas del emisor: {e}")
    cached = on_cashflow_service.schedules()
    schedules = {b: cached[b] for b in group if b in cached}
    if base not in schedules and t in cached:
        schedules[base] = cached[t]          # la ficha se abrió por la especie D o C
    scan = arbitrage_engine.scan(db)
    quotes = [q.model_dump() for q in ingestion_service.get_latest_quotes(db, settlement="24HS")]
    by_ticker = {q["ticker"]: q for q in quotes}
    rows, _ = analyze_ons(scan.on_view, schedules, {b: issuer for b in schedules} if issuer else {},
                          by_ticker, sovereign_curve(quotes), scan.params.commission_pct)
    return profile_block(base, issuer, rows, by_ticker)


async def _profile_cer(db: Session, model: profile.BondModel) -> Optional[profile.CerSeries]:
    return profile.CerSeries(await price_history_service.ensure_cer(db)) if model.cer else None


@router.get("/bonds/{ticker}/profile", tags=["Quant Analytics"])
async def get_bond_profile(ticker: str, db: Session = Depends(get_db)):
    """
    Ficha del bono: datos de contexto, precio actual, métricas calculadas con los flujos propios
    (TIR, duration, valor técnico, paridad) y sensibilidad del precio a cambios de TIR.
    """
    today = date.today()
    model = await _profile_model(db, ticker, today)
    price = _profile_price(db, model)
    cer = await _profile_cer(db, model)
    s_date = next_business_day(today)
    metrics = profile.valuation(model, price["price"], s_date, cer)
    metrics["settlement_date"] = s_date.isoformat()
    try:
        on_block = await _profile_on(db, model)
    except Exception as e:                      # el bloque de ON es un agregado: nunca rompe la ficha
        db.rollback()
        logger.warning(f"Ficha {ticker}: bloque de ON no disponible: {e}")
        on_block = None
    return {"context": profile.context(model, today), "quote": price, "metrics": metrics,
            "reference_metrics": _profile_reference_metrics(db, model), "on": on_block}


@router.get("/bonds/{ticker}/history", tags=["Quant Analytics"])
async def get_bond_history(ticker: str, db: Session = Depends(get_db)):
    """
    Historia diaria de la ficha: precio de cierre (Rava, se descarga a demanda una vez por día),
    TIR y paridad recalculadas con los flujos de cada fecha, pagos para marcar en los gráficos y
    ratio contra los pares del bono con su banda móvil.
    """
    today = date.today()
    model = await _profile_model(db, ticker, today)
    pairs = [sp for sp in profile.pair_specs() if model.base in (sp.a, sp.b)]
    symbols = [model.price_symbol] + [x for sp in pairs for x in (sp.symbol_a, sp.symbol_b)]
    errors = await price_history_service.ensure(db, symbols)
    closes = PriceHistoryService.closes(db, model.price_symbol)
    cer = await _profile_cer(db, model)
    notes = list(model.notes)
    if model.cer and not cer:
        notes.append("No se pudo obtener la serie del CER (BCRA): sin TIR ni paridad históricas.")
    if not closes:
        detail = errors.get(model.price_symbol, "sin datos")
        notes.append(f"Rava no tiene historia de {model.price_symbol} ({detail}).")
    history = profile.compute_history(model, closes, today, cer)
    history["payments"] = profile.payment_marks(model, closes[0][0] if closes else None, today)
    history["pairs"] = profile.pair_series(db, model.base, today)
    history["source"] = "RAVA"
    history["notes"] = notes
    return history


@router.post("/calculator/valuation", response_model=ValuationResponse, tags=["Quant Analytics"])
def calculate_bond_valuation(
    request: ValuationRequest,
    db: Session = Depends(get_db)
):
    """
    TIR, TEM, TNA, Duration y (cuando se conoce) Valor Técnico y Paridad para un precio dado.
    El precio es el precio de mercado (sucio) por 100 VN, en la moneda de los flujos.
    """
    bond, ref = _cashflow_source(db, request.ticker)
    s_date = _resolve_settlement_date(request.settlement_date, request.settlement)

    res_cap = accrued = vt = parity = None
    yield_is_real = False
    if ref is None:
        ticker = bond.ticker
        source = "PROPIO"
        res_cap = calculate_residual_capital(ticker, s_date)
        accrued = calculate_accrued_interest(ticker, s_date)
        vt = calculate_technical_value(res_cap, accrued)
        cfs = generate_cashflows(ticker, s_date, bond.maturity_date)
    else:
        ticker = ref.ticker_base
        source = "COMPARARBONOS"
        yield_is_real = bool(ref.yield_is_real)
        res_cap = ref.residual_capital
        # El VT de referencia vale para la liquidación de la rueda de la fuente
        if ref.technical_value and ref.settlement_date == s_date:
            vt = ref.technical_value
        cfs = _reference_cashflows(ref, s_date)
        if not cfs:
            raise HTTPException(status_code=422, detail=f"{ticker} no tiene flujos posteriores a {s_date}.")

    if vt:
        parity = calculate_parity(request.price, vt)

    ytm = calculate_ytm(request.price, cfs)
    tem = tna = d_mac = md = None
    if ytm is not None:
        tem = calculate_tem(ytm)
        tna = calculate_tna(tem)
        d_mac, md = calculate_duration_and_md(request.price, ytm, cfs)

    return ValuationResponse(
        ticker=ticker,
        price=request.price,
        settlement_date=s_date,
        residual_capital=res_cap,
        accrued_interest=accrued,
        technical_value=vt,
        parity_percentage=parity,
        ytm_percentage=round(ytm * 100.0, 4) if ytm is not None else None,
        tem_percentage=round(tem * 100.0, 4) if tem is not None else None,
        tna_percentage=round(tna * 100.0, 4) if tna is not None else None,
        macaulay_duration=d_mac,
        modified_duration=md,
        source=source,
        yield_is_real=yield_is_real,
    )

@router.get("/arbitrage/breakeven", response_model=BreakevenResponse, tags=["Quant Analytics"])
def get_breakeven_inflation_route(
    fixed_ytm: Optional[float] = Query(None, description="TIR anual de Tasa Fija/LECAP (%) ej: 26.8"),
    cer_ytm: Optional[float] = Query(None, description="TIR real anual de BONCER (%) ej: 7.5"),
    fixed_ticker: Optional[str] = Query(None, description="Ticker de bono a tasa fija ej: S30N6"),
    cer_ticker: Optional[str] = Query(None, description="Ticker de bono CER ej: TZX27"),
    db: Session = Depends(get_db)
):
    """Calcula la inflación implícita mensual y anual que iguala el retorno de tasa fija vs CER (Ecuación Fisher)."""
    # Si se pasan tickers, buscar la TIR más reciente en la base de datos
    r_fixed = fixed_ytm
    r_cer = cer_ytm

    if fixed_ticker:
        snap_fixed = db.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.ticker == fixed_ticker.upper())
            .order_by(PriceSnapshot.timestamp.desc())
        ).scalars().first()
        if snap_fixed and snap_fixed.ytm_percentage:
            r_fixed = float(snap_fixed.ytm_percentage)

    if cer_ticker:
        snap_cer = db.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.ticker == cer_ticker.upper())
            .order_by(PriceSnapshot.timestamp.desc())
        ).scalars().first()
        if snap_cer and snap_cer.ytm_percentage:
            r_cer = float(snap_cer.ytm_percentage)

    if r_fixed is None or r_cer is None:
        raise HTTPException(
            status_code=422,
            detail="Faltan datos: indicar fixed_ytm/cer_ytm o tickers con TIR disponible en la base."
        )

    be = calculate_breakeven_inflation(r_fixed / 100.0, r_cer / 100.0)

    desc = (
        f"Con una inflación mensual proyectada superior a {be['breakeven_monthly_pct']}%, "
        f"el bono CER supera en rendimiento a la tasa fija. Si la inflación es menor, conviene posicionarse en Tasa Fija."
    )

    return BreakevenResponse(
        fixed_ticker=fixed_ticker,
        fixed_ytm_percentage=r_fixed,
        cer_ticker=cer_ticker,
        cer_ytm_percentage=r_cer,
        breakeven_annual_percentage=be["breakeven_annual_pct"],
        breakeven_monthly_percentage=be["breakeven_monthly_pct"],
        description=desc
    )

@router.get("/arbitrage/law-spreads", response_model=List[LawSpreadPair], tags=["Quant Analytics"])
def get_law_spreads(
    settlement: str = Query("24HS", description="Plazo de liquidación: CI o 24HS"),
    db: Session = Depends(get_db)
):
    """Retorna la matriz de pares gemelos Ley Local vs Ley Nueva York (AL vs GD) con ratios y yield spreads."""
    pairs = [
        ("AL29", "GD29"),
        ("AL30", "GD30"),
        ("AL35", "GD35"),
        ("AE38", "GD38"),
        ("AL41", "GD41")
    ]

    results: List[LawSpreadPair] = []

    for al, gd in pairs:
        snap_al = _latest_snapshot(db, al, settlement)
        snap_gd = _latest_snapshot(db, gd, settlement)

        # Solo especie D (dólar MEP) contra especie D: nunca mezclar con precios en pesos
        p_al = float(snap_al.price_mep) if snap_al and snap_al.price_mep else None
        p_gd = float(snap_gd.price_mep) if snap_gd and snap_gd.price_mep else None
        ytm_al = float(snap_al.ytm_percentage) / 100.0 if snap_al and snap_al.ytm_percentage else None
        ytm_gd = float(snap_gd.ytm_percentage) / 100.0 if snap_gd and snap_gd.ytm_percentage else None

        spread = calculate_law_spread(
            price_gd=p_gd or 0.0,
            price_al=p_al or 0.0,
            ytm_gd=ytm_gd,
            ytm_al=ytm_al
        )

        status = "NORMAL"
        if spread["price_ratio"]:
            if spread["price_ratio"] <= 1.01:
                status = "COMPRESSED_ROTAR_A_NY"
            # La prima alta se evalúa con la banda propia de cada par (Command Center), no con un corte fijo

        results.append(
            LawSpreadPair(
                al_ticker=al,
                gd_ticker=gd,
                price_al=p_al,
                price_gd=p_gd,
                price_ratio=spread["price_ratio"],
                price_spread_percentage=spread["price_spread_pct"],
                ytm_al=round(ytm_al * 100.0, 2) if ytm_al else None,
                ytm_gd=round(ytm_gd * 100.0, 2) if ytm_gd else None,
                yield_spread_bps=spread["yield_spread_bps"],
                status=status
            )
        )

    return results

# ==========================================
# ENDPOINTS MOTOR DE ARBITRAJES (FASE 3)
# ==========================================

@router.post("/calculator/swap", response_model=SwapResponse, tags=["Quant Analytics"])
def simulate_swap_endpoint(
    request: SwapRequest,
    db: Session = Depends(get_db)
):
    """
    Simula una rotación entre dos bonos: nominales resultantes, costos e impacto en TIR y duration.
    Usa precios ejecutables: se vende a la punta compradora y se compra a la vendedora, recorriendo
    el libro (Bull Market en tiempo real o BYMA con demora). Sin libro, el último operado.
    """
    sell_t = request.sell_ticker.strip().upper()
    buy_t = request.buy_ticker.strip().upper()
    settlement = request.settlement.upper()

    snap_sell = _latest_snapshot(db, sell_t, settlement)
    snap_buy = _latest_snapshot(db, buy_t, settlement)
    missing = [t for t, snap in ((sell_t, snap_sell), (buy_t, snap_buy)) if snap is None]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Sin cotización {settlement} para: {', '.join(missing)}."
        )

    # Ambas patas en la MISMA moneda: primero dólar MEP (especie D), si no pesos.
    if snap_sell.price_mep and snap_buy.price_mep:
        p_sell, p_buy, currency = float(snap_sell.price_mep), float(snap_buy.price_mep), "USD"
    elif snap_sell.price_ars and snap_buy.price_ars:
        p_sell, p_buy, currency = float(snap_sell.price_ars), float(snap_buy.price_ars), "ARS"
    else:
        raise HTTPException(
            status_code=422,
            detail=f"{sell_t} y {buy_t} no tienen precio en una moneda común (MEP o pesos)."
        )

    ytm_sell = float(snap_sell.ytm_percentage) / 100.0 if snap_sell.ytm_percentage else None
    ytm_buy = float(snap_buy.ytm_percentage) / 100.0 if snap_buy.ytm_percentage else None
    md_sell = float(snap_sell.modified_duration) if snap_sell.modified_duration else None
    md_buy = float(snap_buy.modified_duration) if snap_buy.modified_duration else None

    # Precios ejecutables: puntas con profundidad; el último operado queda como respaldo
    fee_rate = (request.broker_commission_pct + request.byma_fee_pct) / 100.0
    max_age = settings.BULLMARKET_MAX_AGE_SECONDS
    leg_s = swap_pricing.sell_leg(
        swap_pricing.book_for_leg(db, market_book_service, sell_t, currency, settlement, max_age),
        request.sell_nominal, p_sell, sell_t)
    cash = (request.sell_nominal / 100.0) * leg_s.price * (1.0 - fee_rate)
    leg_b = swap_pricing.buy_leg(
        swap_pricing.book_for_leg(db, market_book_service, buy_t, currency, settlement, max_age),
        cash, fee_rate, p_buy, buy_t)
    notes = [n for n in (swap_pricing.describe(leg_s, "venta"), swap_pricing.describe(leg_b, "compra")) if n]

    res = simulate_bond_swap(
        sell_ticker=leg_s.symbol,
        sell_price=leg_s.price,
        sell_nominal=request.sell_nominal,
        buy_ticker=leg_b.symbol,
        buy_price=leg_b.price,
        broker_commission_pct=request.broker_commission_pct,
        byma_fee_pct=request.byma_fee_pct,
        ytm_sell=ytm_sell,
        ytm_buy=ytm_buy,
        md_sell=md_sell,
        md_buy=md_buy
    )

    return SwapResponse(
        sell_ticker=sell_t,
        sell_nominal=res.sell_nominal,
        sell_price=res.sell_price,
        sell_gross_amount=res.sell_gross_amount,
        sell_fees=res.sell_fees,
        sell_net_proceeds=res.sell_net_proceeds,
        buy_ticker=buy_t,
        buy_nominal_acquired=res.buy_nominal_acquired,
        buy_price=res.buy_price,
        buy_net_cost=res.buy_net_cost,
        buy_fees=res.buy_fees,
        cash_leftover=res.cash_leftover,
        nominal_expansion_ratio=res.nominal_expansion_ratio,
        nominal_pickup=res.nominal_pickup,
        yield_pickup_bps=res.yield_pickup_bps,
        duration_change=res.duration_change,
        summary_message=res.summary_message,
        currency=currency,
        settlement=settlement,
        sell_symbol=leg_s.symbol, buy_symbol=leg_b.symbol,
        sell_price_kind=leg_s.kind, buy_price_kind=leg_b.kind,
        sell_price_source=leg_s.source, buy_price_source=leg_b.source,
        sell_depth_ok=leg_s.depth_ok, buy_depth_ok=leg_b.depth_ok,
        notes=notes,
    )

@router.get("/arbitrage/signals", response_model=List[ArbitrageSignalResponse], tags=["Arbitrage Engine"])
def get_arbitrage_signals(
    strategy_name: Optional[str] = Query(None, description="Filtrar por: LAW_PREMIUM, RELATIVE_VALUE_CURVE, BREAKEVEN_CER_FIXED, DUAL_TAMAR_CER"),
    status: Optional[str] = Query("ACTIVE", description="Filtrar por estado: ACTIVE, EXECUTED, EXPIRED"),
    db: Session = Depends(get_db)
):
    """Retorna las señales de arbitraje registradas por el motor algorítmico."""
    query = select(ArbitrageSignal)
    if strategy_name:
        query = query.where(ArbitrageSignal.strategy_name == strategy_name.upper())
    if status:
        query = query.where(ArbitrageSignal.status == status.upper())

    signals = db.execute(query.order_by(ArbitrageSignal.timestamp.desc())).scalars().all()
    return signals

@router.post("/arbitrage/evaluate", tags=["Arbitrage Engine"])
def trigger_arbitrage_evaluation(db: Session = Depends(get_db)):
    """Ejecuta inmediatamente el motor de evaluación para todas las estrategias sobre las cotizaciones actuales."""
    signals = arbitrage_engine.evaluate_all_strategies(db)
    return {
        "status": "success",
        "signals_generated_count": len(signals),
        "new_signals_count": len(arbitrage_engine.last_new_signals),
        "expired_signals_count": arbitrage_engine.last_expired_count,
        "signals": [
            {
                "id": s.id,
                "strategy": s.strategy_name,
                "action": s.action_recommended,
                "sell": s.leg_sell_ticker,
                "buy": s.leg_buy_ticker,
                "metric_value": float(s.metric_value),
                "notes": s.notes
            }
            for s in signals
        ]
    }

@router.get("/arbitrage/ci-24hs", tags=["Arbitrage Engine"])
def get_ci_24hs_scanner(
    only_signals: bool = Query(False, description="Solo oportunidades que superan la ganancia mínima"),
    limit: int = Query(100, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """
    Arbitraje entre plazos CI vs 24hs (misma especie), en las dos direcciones, con puntas,
    costos, caución y ajuste por corte de cupón. Ordenado por ganancia neta.
    """
    scan = arbitrage_engine.scan(db)
    rows = [o for o in scan.ci_24hs if o.signal] if only_signals else scan.ci_24hs
    return {
        "params": scan.params.to_dict(),
        "today": scan.view.today, "settlement_24hs": scan.view.next_bd,
        "days": scan.view.settlement_days, "caucion_tna_pct": scan.view.caucion_tna_pct,
        "mep_reference": scan.view.mep_reference,
        "opportunities": [o.to_dict() for o in rows[:limit]],
    }


@router.get("/arbitrage/fx-implied", tags=["Arbitrage Engine"])
def get_fx_implied(
    kind: str = Query("MEP", pattern="^(?i:MEP|CCL)$"),
    db: Session = Depends(get_db),
):
    """Dólar MEP / CCL ejecutable por bono y plazo (comprar y vender dólares), y mejor ida y vuelta."""
    scan = arbitrage_engine.scan(db)
    k = kind.upper()
    quotes = [q for q in scan.fx_quotes if q.kind == k]
    buys = sorted([q for q in quotes if q.buy_usd_rate], key=lambda q: q.buy_usd_rate)
    sells = sorted([q for q in quotes if q.sell_usd_rate], key=lambda q: q.sell_usd_rate, reverse=True)
    return {
        "params": scan.params.to_dict(),
        "kind": k,
        "best_to_buy_usd": [q.to_dict() for q in buys[:30]],
        "best_to_sell_usd": [q.to_dict() for q in sells[:30]],
        "round_trips": [t.to_dict() for t in scan.fx_round_trips if t.kind == k],
        "cable_to_mep": [c.to_dict() for c in
                         sorted(scan.cable_to_mep, key=lambda c: (not c.depth_ok, -c.net_pct))[:10]],
    }


@router.get("/arbitrage/on-relative-value", tags=["Arbitrage Engine"])
def get_on_relative_value(db: Session = Depends(get_db)):
    """
    Obligaciones negociables en dólares: TIR y duration con precio de Bull Market y cronograma de
    Bull Market (sin sesión: cronograma de bonistas.com), spread contra su emisor y contra el
    soberano, e ideas de canje (informativo).
    """
    from backend.app.arbitrage.on_relative_value import analyze_ons, sovereign_curve
    scan = arbitrage_engine.scan(db)
    quotes = [q.model_dump() for q in ingestion_service.get_latest_quotes(db, settlement="24HS")]
    schedules = on_cashflow_service.schedules()
    rows, ideas = analyze_ons(
        scan.on_view, schedules, ingestion_service.issuer_by_ticker,
        {q["ticker"]: q for q in quotes}, sovereign_curve(quotes), scan.params.commission_pct,
    )
    live = scan.on_view is not None and bool(scan.on_view.books)
    status = None
    if not settings.BULLMARKET_ON_ENABLED:
        status = "Deshabilitado (BULLMARKET_ON_ENABLED)."
    elif not schedules:
        status = ("Sin cronogramas de ON todavía: se descargan una vez por día durante la rueda "
                  "(Bull Market con la sesión activa; sin sesión, bonistas.com).")
    elif not live:
        status = "Sin precios de ON en tiempo real: se usan los de bonistas.com, con demora."
    return {
        "params": scan.params.to_dict(), "settlement": "24HS",
        "settlement_date": scan.on_view.next_bd if scan.on_view is not None else None,
        "schedules": len(schedules), "live": live, "status": status,
        "schedule_sources": {src: sum(1 for s in schedules.values() if source_of(s) == src)
                             for src in sorted({source_of(s) for s in schedules.values()})},
        "rows": [r.to_dict() for r in rows], "swap_ideas": [i.to_dict() for i in ideas],
    }


@router.get("/arbitrage/ratios", tags=["Arbitrage Engine"])
def get_pair_ratios(db: Session = Depends(get_db)):
    """Ratios AL/GD y entre bonos de la curva, con puntas y z-score (historia real cuando alcanza)."""
    scan = arbitrage_engine.scan(db)
    return {"params": scan.params.to_dict(), "ratios": [r.to_dict() for r in scan.ratios]}


@router.get("/settings/trading", tags=["Settings"])
def get_trading_settings(db: Session = Depends(get_db)):
    """Parámetros operativos: costo por operación (%), ganancia neta mínima (%) y tamaño (USD)."""
    return get_params(db).to_dict()


@router.put("/settings/trading", tags=["Settings"])
def put_trading_settings(values: Dict[str, float], db: Session = Depends(get_db)):
    """Actualiza uno o más parámetros operativos (se guardan en la base)."""
    try:
        return update_params(db, values).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/arbitrage/command-center", tags=["Arbitrage Engine"])
def get_arbitrage_command_center(db: Session = Depends(get_db)):
    """Retorna la matriz de control y monitoreo en tiempo real con semáforos e indicadores clave."""
    return arbitrage_engine.get_arbitrage_command_center(db)


# ==========================================
# ALERTAS Y NOTIFICACIONES (ETAPA 5)
# ==========================================

class MarkReadRequest(BaseModel):
    ids: Optional[List[int]] = None     # None = todas


@router.get("/alerts", tags=["Alertas"])
def get_alerts(
    limit: int = Query(50, ge=1, le=500),
    unread_only: bool = False,
    after_id: Optional[int] = Query(None, description="Solo alertas posteriores a este id"),
    db: Session = Depends(get_db),
):
    """
    Historial de alertas (más nuevas primero), cada una con la vigencia de su señal.
    `pending` es el número de la campanita: sin leer y todavía vigentes. `unread`: todas las sin leer.
    """
    alerts = AlertService.list_alerts(db, limit=limit, unread_only=unread_only, after_id=after_id)
    return {"unread": AlertService.unread_count(db), "pending": AlertService.pending_count(db),
            "alerts": AlertService.describe(db, alerts)}


@router.post("/alerts/read", tags=["Alertas"])
def mark_alerts_read(req: MarkReadRequest, db: Session = Depends(get_db)):
    return {"marked": AlertService.mark_read(db, req.ids), "unread": AlertService.unread_count(db),
            "pending": AlertService.pending_count(db)}


@router.post("/alerts/test", tags=["Alertas"])
def send_test_alert(db: Session = Depends(get_db)):
    """Genera una alerta de prueba (y la notificación de Windows si está habilitada)."""
    prefs = get_prefs(db)
    a = alert_service.emit(db, "PRUEBA", "INFO", "Prueba de notificación",
                           "Si ves este aviso, las notificaciones de Windows funcionan.",
                           toast=prefs.windows)
    return AlertService.to_dict(a)


@router.get("/settings/notifications", tags=["Alertas"])
def get_notification_settings(db: Session = Depends(get_db)):
    return get_prefs(db).to_dict()


@router.put("/settings/notifications", tags=["Alertas"])
def put_notification_settings(values: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        return update_prefs(db, values).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))



# ==========================================
# CURVAS DE RENDIMIENTO POR FAMILIA
# ==========================================

@router.get("/curves", tags=["Quant Analytics"])
def get_curves(
    dolar: str = Query("MEP", pattern="^(?i:MEP|CCL)$", description="TIR de bonos en dólares: MEP o CCL (cable)"),
    db: Session = Depends(get_db),
):
    """
    Curvas agrupadas por familia (soberanos USD, tasa fija, CER, provinciales, dollar linked,
    TAMAR/duales y Argentina vs región), con curva ajustada y desvío de cada bono en bps.
    """
    from backend.app.services.curves_service import build_curves
    quotes = {q.ticker: q for q in ingestion_service.get_latest_quotes(db)}
    prices = {}
    for b in market_book_service.latest_books(db, source="BYMA", settlement="24HS"):
        mid = (b.bid + b.ask) / 2.0 if b.bid and b.ask else b.last
        if mid:
            prices[b.symbol] = (mid, b.currency)
    mep = None
    if prices.get("AL30") and prices.get("AL30D"):
        mep = prices["AL30"][0] / prices["AL30D"][0]
    if mep is None:
        row = db.execute(select(MacroIndicator).where(MacroIndicator.name == "DOLAR_BOLSA")
                         .order_by(MacroIndicator.date.desc())).scalars().first()
        mep = float(row.value) if row else None
    ccl = prices["AL30"][0] / prices["AL30C"][0] if prices.get("AL30") and prices.get("AL30C") else None
    if ccl is None:
        row = db.execute(select(MacroIndicator).where(MacroIndicator.name == "DOLAR_CONTADOCONLIQUI")
                         .order_by(MacroIndicator.date.desc())).scalars().first()
        ccl = float(row.value) if row else None
    dollar = dolar.upper()
    groups = build_curves(db, quotes, book_prices=prices, mep_reference=mep, dollar=dollar, ccl_reference=ccl)
    return {"dolar": dollar, "mep_reference": round(mep, 2) if mep else None,
            "ccl_reference": round(ccl, 2) if ccl else None, "groups": [g.to_dict() for g in groups]}
