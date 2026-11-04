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

router = APIRouter()
ingestion_service = IngestionService()
arbitrage_engine = ArbitrageEngine(ingestion_service)

@router.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": "Sistema de Arbitraje de Bonos Argentinos",
        "phase": "Fase 1 - Ingesta & Base de Datos"
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
    db: Session = Depends(get_db)
):
    """Obtiene las cotizaciones y métricas más recientes de los bonos en cartera."""
    quotes = ingestion_service.get_latest_quotes(db, bond_type=bond_type)
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
    """Dispara una sincronización manual e inmediata de cotizaciones y tipos de cambio."""
    try:
        result = await ingestion_service.ingest_market_data(db)
        return {
            "status": "success",
            "message": "Ingesta de mercado completada",
            "details": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error durante la ingesta: {str(e)}")

# ==========================================
# ENDPOINTS CUANTITATIVOS (FASE 2)
# ==========================================

@router.get("/bonds/{ticker}/cashflows", response_model=List[CashFlowItemResponse], tags=["Quant Analytics"])
def get_bond_cashflows(
    ticker: str,
    settlement_date: Optional[date] = Query(None, description="Fecha de liquidación (default: hoy)"),
    db: Session = Depends(get_db)
):
    """Obtiene el vector cronológico completo de flujos de fondos futuros del bono."""
    clean_ticker = ticker.upper()
    bond = db.execute(select(Bond).where(Bond.ticker == clean_ticker)).scalar_one_or_none()
    if not bond:
        raise HTTPException(status_code=404, detail=f"Bono '{ticker}' no encontrado en el maestro.")

    s_date = settlement_date or date.today()
    c_rate = float(bond.coupon_rate) if bond.coupon_rate is not None else 0.0
    cfs = generate_cashflows(clean_ticker, s_date, bond.maturity_date, coupon_rate=c_rate)

    return [
        CashFlowItemResponse(
            date=cf.date,
            days_from_settlement=cf.days_from_settlement,
            interest_rate=cf.interest_rate,
            coupon_amount=cf.coupon_amount,
            amortization_amount=cf.amortization_amount,
            total_cashflow=cf.total_cashflow,
            residual_capital=cf.residual_capital
        )
        for cf in cfs
    ]

@router.post("/calculator/valuation", response_model=ValuationResponse, tags=["Quant Analytics"])
def calculate_bond_valuation(
    request: ValuationRequest,
    db: Session = Depends(get_db)
):
    """Calcula Valor Técnico, Paridad, TIR/YTM (Newton-Raphson), Duration y TEM para un precio dado."""
    clean_ticker = request.ticker.upper()
    bond = db.execute(select(Bond).where(Bond.ticker == clean_ticker)).scalar_one_or_none()
    if not bond:
        raise HTTPException(status_code=404, detail=f"Bono '{request.ticker}' no encontrado.")

    s_date = request.settlement_date or date.today()
    c_rate = float(bond.coupon_rate) if bond.coupon_rate is not None else 0.0

    res_cap = calculate_residual_capital(clean_ticker, s_date)
    accrued = calculate_accrued_interest(clean_ticker, s_date, coupon_rate=c_rate)
    vt = calculate_technical_value(res_cap, accrued)
    parity = calculate_parity(request.price, vt)

    cfs = generate_cashflows(clean_ticker, s_date, bond.maturity_date, coupon_rate=c_rate)
    ytm = calculate_ytm(request.price, cfs)

    tem = None
    tna = None
    d_mac = None
    md = None

    if ytm is not None:
        tem = calculate_tem(ytm)
        tna = calculate_tna(tem)
        d_mac, md = calculate_duration_and_md(request.price, ytm, cfs)

    return ValuationResponse(
        ticker=clean_ticker,
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
        modified_duration=md
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
        # Valores de referencia de mercado por omisión
        r_fixed = r_fixed or 26.8
        r_cer = r_cer or 7.5

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
def get_law_spreads(db: Session = Depends(get_db)):
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
        snap_al = db.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.ticker == al)
            .order_by(PriceSnapshot.timestamp.desc())
        ).scalars().first()

        snap_gd = db.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.ticker == gd)
            .order_by(PriceSnapshot.timestamp.desc())
        ).scalars().first()

        p_al = float(snap_al.price_mep or snap_al.last_price) if snap_al else None
        p_gd = float(snap_gd.price_mep or snap_gd.last_price) if snap_gd else None
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
    sell_t = request.sell_ticker.upper()
    buy_t = request.buy_ticker.upper()

    snap_sell = db.execute(
        select(PriceSnapshot).where(PriceSnapshot.ticker == sell_t).order_by(PriceSnapshot.timestamp.desc())
    ).scalars().first()

    snap_buy = db.execute(
        select(PriceSnapshot).where(PriceSnapshot.ticker == buy_t).order_by(PriceSnapshot.timestamp.desc())
    ).scalars().first()

    p_sell = float(snap_sell.price_mep or snap_sell.last_price) if snap_sell else 54.49
    p_buy = float(snap_buy.price_mep or snap_buy.last_price) if snap_buy else 52.71
    ytm_sell = float(snap_sell.ytm_percentage) / 100.0 if snap_sell and snap_sell.ytm_percentage else 0.185
    ytm_buy = float(snap_buy.ytm_percentage) / 100.0 if snap_buy and snap_buy.ytm_percentage else 0.201
    md_sell = float(snap_sell.modified_duration) if snap_sell and snap_sell.modified_duration else 1.29
    md_buy = float(snap_buy.modified_duration) if snap_buy and snap_buy.modified_duration else 1.66

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
        summary_message=res.summary_message
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

@router.get("/arbitrage/command-center", tags=["Arbitrage Engine"])
def get_arbitrage_command_center(db: Session = Depends(get_db)):
    """Retorna la matriz de control y monitoreo en tiempo real con semáforos e indicadores clave."""
    return arbitrage_engine.get_arbitrage_command_center(db)

