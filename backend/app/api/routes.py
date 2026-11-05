from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from datetime import date

from backend.app.db.session import get_db
from backend.app.db.models import Bond, MacroIndicator, PriceSnapshot, ArbitrageSignal
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
from backend.app.services.bullmarket_session import InvalidCookieError
from backend.app.services.alert_service import AlertService, get_prefs, update_prefs
from backend.app.services.trading_settings import get_params, update_params
from backend.app.config import settings

router = APIRouter()
ingestion_service = IngestionService()
market_book_service = MarketBookService()
bullmarket_session = market_book_service.bm_session
arbitrage_engine = ArbitrageEngine(ingestion_service, book_service=market_book_service)
alert_service = AlertService()
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
async def get_status():
    """Estado de las fuentes de datos y del horario de mercado (para el dashboard)."""
    window = await market_calendar.today()
    return {
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
def get_bond_cashflows(
    ticker: str,
    settlement_date: Optional[date] = Query(None, description="Fecha de liquidación (default: próximo día hábil)"),
    db: Session = Depends(get_db)
):
    """
    Flujos de fondos futuros por 100 VN. Para Bonares/Globales se detalla renta, amortización y
    residual; para el resto (fuente CompararBonos) solo se conoce el flujo total de cada fecha.
    """
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

    return [
        CashFlowItemResponse(
            date=cf.date, days_from_settlement=cf.days_from_settlement,
            interest_rate=None, coupon_amount=None, amortization_amount=None,
            total_cashflow=cf.total_cashflow, residual_capital=None, source="COMPARARBONOS",
        )
        for cf in _reference_cashflows(ref, s_date)
    ]


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
            elif spread["price_ratio"] >= 1.12:
                status = "EXPANDED_ROTAR_A_ARG"

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
    """Simula una rotación o swap de bonos calculando nominales resultantes, comisiones e impacto en cartera."""
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

    res = simulate_bond_swap(
        sell_ticker=sell_t,
        sell_price=p_sell,
        sell_nominal=request.sell_nominal,
        buy_ticker=buy_t,
        buy_price=p_buy,
        broker_commission_pct=request.broker_commission_pct,
        byma_fee_pct=request.byma_fee_pct,
        ytm_sell=ytm_sell,
        ytm_buy=ytm_buy,
        md_sell=md_sell,
        md_buy=md_buy
    )

    return SwapResponse(
        sell_ticker=res.sell_ticker,
        sell_nominal=res.sell_nominal,
        sell_price=res.sell_price,
        sell_gross_amount=res.sell_gross_amount,
        sell_fees=res.sell_fees,
        sell_net_proceeds=res.sell_net_proceeds,
        buy_ticker=res.buy_ticker,
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
        settlement=settlement
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
    """Historial de alertas (más nuevas primero) y cantidad sin leer."""
    alerts = AlertService.list_alerts(db, limit=limit, unread_only=unread_only, after_id=after_id)
    return {"unread": AlertService.unread_count(db), "alerts": [AlertService.to_dict(a) for a in alerts]}


@router.post("/alerts/read", tags=["Alertas"])
def mark_alerts_read(req: MarkReadRequest, db: Session = Depends(get_db)):
    return {"marked": AlertService.mark_read(db, req.ids), "unread": AlertService.unread_count(db)}


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
def get_curves(db: Session = Depends(get_db)):
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
            prices[b.symbol] = mid
    return {"groups": [g.to_dict() for g in build_curves(db, quotes, book_prices=prices)]}
