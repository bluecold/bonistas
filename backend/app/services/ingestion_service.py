"""
Servicio central de ingesta, normalización y persistencia de cotizaciones y métricas de bonos argentinos.
"""

import logging
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc

from backend.app.db.models import Bond, PriceSnapshot, MacroIndicator
from backend.app.data.bond_catalog import INITIAL_BONDS
from backend.app.data.bonistas_client import BonistasClient
from backend.app.data.dolar_api_client import DolarApiClient
from backend.app.data.macro_connectors import MacroDataConnector
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.services.source_health import source_health

logger = logging.getLogger(__name__)


def _positive(value: Any) -> Optional[float]:
    """Devuelve el número si es un precio válido (> 0); None si falta o es 0/negativo."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# Tipos que no son bonos soberanos/subsoberanos en dólares
ON = "ON"                 # obligaciones negociables (deuda corporativa)
NOT_A_BOND = "NO_BONO"    # acciones / CEDEARs que bonistas.com mezcla en el listado
SCENARIO = "ESCENARIO"    # variantes de cálculo de un bono (TTD26_CAP, TXMD8_CER, ..._PUT, ..._TAM)
HIDDEN_TYPES = (NOT_A_BOND, SCENARIO)
_CATALOG_TICKERS = {b["ticker"] for b in INITIAL_BONDS}


def classify_family(family: str) -> Optional[str]:
    """
    Tipo de instrumento a partir de la familia de bonistas.com. None = no es un bono (acciones y
    CEDEARs vienen con familia vacía). Antes todo lo no reconocido caía en HARD_DOLLAR.
    """
    f = (family or "").strip().upper()
    if not f:
        return None
    if f.startswith("ONS"):
        return ON
    # Los duales (DUAL-CER-TAMAR...) contienen "CER" en la familia: van antes que CER
    if "DUAL" in f:
        return "DUAL"
    if "CER" in f:
        return "CER"
    if "FIJA" in f or "FIJO" in f:
        return "TASA_FIJA"
    if "BOPREAL" in f:
        return "BOPREAL"
    if "DOLAR-LINKED" in f:
        return "DOLLAR_LINKED"
    if "TAMAR" in f or "BADLAR" in f:
        return "TAMAR"
    if f.startswith("BONO-USD"):
        return "HARD_DOLLAR"
    return "OTRO"


def species_currency(family: str, ticker: str) -> str:
    """
    Moneda de la especie ("ARS", "MEP" o "CCL"). Familias de bonistas: BONO-USD-L{P,D,C}{A,NY}
    (pesos / MEP / cable), *-CABLE, *-PESOS; en ON y letras en dólares lo dice el sufijo D/C.
    """
    f = (family or "").strip().upper()
    t = (ticker or "").strip().upper()
    if "CABLE" in f or f.endswith(("-LCA", "-LCNY")):
        return "CCL"
    if f.endswith(("-LDA", "-LDNY")):
        return "MEP"
    if f.endswith(("-LPA", "-LPNY")) or "PESOS" in f:
        return "ARS"
    usd_family = f.startswith("ONS") or f.endswith("-USD") or f == "BOPREAL"
    if usd_family and len(t) >= 4 and t[-1] in ("D", "C"):
        return "MEP" if t[-1] == "D" else "CCL"
    return "ARS"


class IngestionService:
    def __init__(
        self,
        bonistas_client: Optional[BonistasClient] = None,
        dolar_client: Optional[DolarApiClient] = None,
        macro_connector: Optional[MacroDataConnector] = None
    ):
        self.bonistas = bonistas_client or BonistasClient()
        self.dolar_api = dolar_client or DolarApiClient()
        self.macro = macro_connector or MacroDataConnector()
        # Último snapshot guardado por (ticker, plazo) para no repetir filas idénticas.
        # Arranca vacía: tras un reinicio, el primer ciclo guarda una vez cada bono.
        self._last_snapshot: Dict[tuple, tuple] = {}
        # Emisor de cada ON (bonistas.com) para agrupar por empresa en el valor relativo
        self.issuer_by_ticker: Dict[str, str] = {}

    def seed_initial_bonds(self, db: Session) -> int:
        """Siembra el catálogo inicial de bonos si no están cargados."""
        count_created = 0
        for item in INITIAL_BONDS:
            ticker = item["ticker"]
            existing = db.execute(select(Bond).where(Bond.ticker == ticker)).scalar_one_or_none()
            if existing and (existing.maturity_date != item["maturity_date"] or existing.name != item["name"]):
                # Correcciones del catálogo (ej. vencimientos de TY30P, TXMD8, TZX27, BPA8D, TXMJ0)
                existing.maturity_date = item["maturity_date"]
                existing.name = item["name"]
                existing.short_description = item.get("short_description")
                count_created += 1
            if not existing:
                bond = Bond(
                    ticker=ticker,
                    name=item["name"],
                    isin=item.get("isin"),
                    currency=item["currency"],
                    law=item["law"],
                    bond_type=item["bond_type"],
                    amortization_type=item.get("amortization_type"),
                    start_date=item.get("start_date"),
                    maturity_date=item["maturity_date"],
                    coupon_rate=item.get("coupon_rate"),
                    base_nominal=item.get("base_nominal", Decimal("100.0")),
                    short_description=item.get("short_description"),
                    description=item.get("description"),
                )
                db.add(bond)
                count_created += 1
        
        if count_created > 0:
            db.commit()
            logger.info(f"Catálogo inicial: {count_created} bonos creados o actualizados.")
        return count_created

    async def ingest_market_data(self, db: Session) -> Dict[str, Any]:
        """
        Ciclo de ingesta de analítica de bonos (cada minuto, en horario de mercado):
        1. Cotizaciones y métricas de bonistas.com (TIR, MD, paridad, VT)
        2. Especies y tipos de cambio implícitos (fx)
        3. Dólares de referencia (DolarAPI)
        Los indicadores macro (IPC, CER, TAMAR, A3500) se actualizan una vez por día en
        ReferenceDataService. Solo se guarda un snapshot cuando cambió respecto del anterior.
        """
        # Aseguramos catálogo sembrado
        self.seed_initial_bonds(db)

        # 1. Obtener datos externos
        # La fuente de bonos es crítica: si falla, el ciclo falla.
        try:
            bonds_data = await self.bonistas.fetch_bonds()
        except Exception as e:
            source_health.failure("BONISTAS", e)
            raise
        # Las demás son complementarias: si fallan se registra y se sigue con lo disponible.
        warnings: List[str] = []
        fx_data: List[Dict[str, Any]] = []
        dolar_quotes: Dict[str, float] = {}
        try:
            fx_data = await self.bonistas.fetch_fx()
        except Exception as e:
            warnings.append(f"FX bonistas no disponible: {e}")
        try:
            dolar_quotes = await self.dolar_api.get_rates_dict()
            source_health.success("DOLARAPI", cotizaciones=len(dolar_quotes))
        except Exception as e:
            source_health.failure("DOLARAPI", e)
            warnings.append(f"DolarAPI no disponible: {e}")
        for w in warnings:
            logger.warning(w)

        # Indexar FX por ticker limpio (ej: AL30_24hs -> AL30)
        fx_map: Dict[str, Dict[str, Any]] = {}
        for fx in fx_data:
            t = fx.get("ticker", "")
            settlement = fx.get("settlement", "24hs")
            # Extraer ticker base (ej AL30 de AL30_24hs o AL30_CI)
            base_t = t.split("_")[0].upper()
            key = f"{base_t}_{settlement.upper()}"
            fx_map[key] = fx

        now = datetime.now(timezone.utc)
        snapshots_created = 0
        skipped_without_price = 0
        non_bonds = 0
        unchanged = 0
        scenario_variants = 0
        bonds_by_ticker: Dict[str, Bond] = {b.ticker: b for b in db.execute(select(Bond)).scalars()}

        # Mapeo de tickers y normalización
        for b_raw in bonds_data:
            raw_ticker = b_raw.get("ticker", "").strip()
            if not raw_ticker:
                continue

            # Extraer ticker base y plazo de liquidación
            settlement = b_raw.get("settlement", "24hs").upper()
            base_ticker = raw_ticker
            if base_ticker.endswith("_24hs") or base_ticker.endswith("_CI"):
                base_ticker = base_ticker.split("_")[0]
            # _PUT / _TAM / _CER / _CAP son el MISMO instrumento con la TIR calculada bajo otro
            # escenario (ejercicio del put, pata TAMAR o CER de un dual, capitalización). Se usa
            # solo el escenario base; si una versión anterior los registró, quedan ocultos.
            if "_" in base_ticker:
                scenario_variants += 1
                old = bonds_by_ticker.get(base_ticker)
                if old and old.bond_type != SCENARIO and old.ticker not in _CATALOG_TICKERS:
                    old.bond_type = SCENARIO
                continue

            family = b_raw.get("bond_family", "") or ""
            inferred_type = classify_family(family)
            if inferred_type == ON and b_raw.get("emisor"):
                self.issuer_by_ticker[base_ticker] = str(b_raw["emisor"]).strip()

            # Buscar si existe el bono en el maestro
            bond = bonds_by_ticker.get(base_ticker)
            if inferred_type is None:
                # Acciones / CEDEARs: no son bonos. Si ya se habían registrado, se marcan y no se
                # guardan más cotizaciones.
                non_bonds += 1
                if bond and bond.bond_type != NOT_A_BOND and bond.ticker not in _CATALOG_TICKERS:
                    bond.bond_type = NOT_A_BOND
                continue
            if bond and bond.ticker not in _CATALOG_TICKERS and bond.bond_type != inferred_type:
                # Los bonos fuera del catálogo siguen la familia de bonistas (corrige ON y acciones
                # que caían en HARD_DOLLAR, y duales que caían en CER)
                bond.bond_type = inferred_type
            if not bond:
                # Si no está en el catálogo, inferir y registrar dinámicamente
                law_code = b_raw.get("bond_law", "LA")
                law = "NY" if "LNY" in law_code or "NY" in law_code else "ARG"
                bond_type = inferred_type

                curr = "USD" if "USD" in family or law == "NY" else "ARS"
                end_date_str = b_raw.get("end_date")
                try:
                    mat_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else date(2030, 1, 1)
                except Exception:
                    mat_date = date(2030, 1, 1)

                bond = Bond(
                    ticker=base_ticker,
                    name=b_raw.get("bond_name") or base_ticker,
                    currency=curr,
                    law=law,
                    bond_type=bond_type,
                    maturity_date=mat_date,
                    coupon_rate=Decimal(str(b_raw.get("coupon") or 0.0)) / Decimal("100.0") if b_raw.get("coupon") else None,
                    short_description=b_raw.get("short_description")
                )
                db.add(bond)
                db.flush()
                bonds_by_ticker[base_ticker] = bond

            # Extraer precios de las 3 especies
            price_ars = None
            price_mep = None
            price_ccl = None
            last_price = _positive(b_raw.get("last_price"))

            # Cruzar con fx_map para obtener simultáneamente ARS, D y C
            fx_info = fx_map.get(f"{base_ticker}_{settlement}") or fx_map.get(f"{base_ticker}_24HS")
            if fx_info:
                price_ars = _positive(fx_info.get("price_ars"))
                price_mep = _positive(fx_info.get("price_usd"))
                price_ccl = _positive(fx_info.get("price_cable"))
            else:
                # Sin fila de FX (bonos nuevos como AN29/AO27, ON, letras): el último precio es el
                # de la propia especie, en la moneda que indica la familia.
                ccy = species_currency(family, base_ticker)
                if ccy == "MEP":
                    price_mep = last_price
                elif ccy == "CCL":
                    price_ccl = last_price
                else:
                    price_ars = last_price

            # Sin ningún precio válido no hay cotización: no se guarda un snapshot "en cero".
            # bonistas publica 0.01 con TIR 0 como relleno en especies sin operaciones (ej. TB27).
            placeholder = not b_raw.get("tir") and (last_price or 0) <= 0.01 and not fx_info
            if placeholder or not any((last_price, price_ars, price_mep, price_ccl)):
                skipped_without_price += 1
                continue

            # Conversión de métricas financieras
            fair_val = b_raw.get("fair_value")
            parity = b_raw.get("parity")
            tir = b_raw.get("tir")
            mtir = b_raw.get("mtir")
            tna = b_raw.get("tna")
            mod_dur = b_raw.get("modified_duration")
            vol = b_raw.get("volume")
            diff = b_raw.get("day_difference")

            # Solo se guarda si cambió algo respecto del último snapshot de ese bono y plazo
            fingerprint = (last_price, price_ars, price_mep, price_ccl, tir, mod_dur, vol, parity)
            cache_key = (bond.ticker, settlement)
            if self._last_snapshot.get(cache_key) == fingerprint:
                unchanged += 1
                continue
            self._last_snapshot[cache_key] = fingerprint

            snapshot = PriceSnapshot(
                ticker=bond.ticker,
                timestamp=now,
                settlement_type=settlement,
                price_ars=Decimal(str(price_ars)) if price_ars is not None else None,
                price_mep=Decimal(str(price_mep)) if price_mep is not None else None,
                price_ccl=Decimal(str(price_ccl)) if price_ccl is not None else None,
                last_price=Decimal(str(last_price)) if last_price is not None else None,
                day_difference=Decimal(str(diff)) if diff is not None else None,
                volume_millions=Decimal(str(vol)) if vol is not None else None,
                technical_value=Decimal(str(fair_val)) if fair_val is not None else None,
                parity_percentage=Decimal(str(round(parity * 100, 3))) if parity is not None else None,
                ytm_percentage=Decimal(str(round(tir * 100, 4))) if tir is not None else None,
                tem_percentage=Decimal(str(round(mtir * 100, 4))) if mtir is not None else None,
                tna_percentage=Decimal(str(round(tna * 100, 4))) if tna is not None else None,
                modified_duration=Decimal(str(round(mod_dur, 4))) if mod_dur is not None else None,
            )
            db.add(snapshot)
            snapshots_created += 1

        # 3. Guardar macroindicadores
        today = date.today()
        for k, v in dolar_quotes.items():
            name = f"DOLAR_{k.upper()}"
            existing_macro = db.execute(
                select(MacroIndicator).where(MacroIndicator.date == today, MacroIndicator.name == name)
            ).scalar_one_or_none()
            if existing_macro:
                existing_macro.value = Decimal(str(v))
            else:
                db.add(MacroIndicator(date=today, name=name, value=Decimal(str(v)), source="DolarAPI"))

        db.commit()
        logger.info(
            f"Ingesta finalizada: {snapshots_created} snapshots nuevos, {unchanged} sin cambios, "
            f"{skipped_without_price} filas sin precio descartadas."
        )
        source_health.success("BONISTAS", snapshots=snapshots_created, unchanged=unchanged)

        return {
            "timestamp": now.isoformat(),
            "snapshots_created": snapshots_created,
            "skipped_without_price": skipped_without_price,
            "unchanged": unchanged,
            "scenario_variants_skipped": scenario_variants,
            "non_bonds_skipped": non_bonds,
            "dolares": dolar_quotes,
            "warnings": warnings,
        }

    def get_latest_quotes(
        self,
        db: Session,
        bond_type: Optional[str] = None,
        settlement: str = "24HS"
    ) -> List[BondQuoteView]:
        """
        Cotizaciones más recientes de cada bono para UN plazo de liquidación (CI o 24HS).
        Nunca se mezclan plazos: comparar AL CI contra GD 24hs distorsiona cualquier ratio.
        """
        subq = (
            select(
                PriceSnapshot.ticker,
                func.max(PriceSnapshot.id).label("max_id")
            )
            .where(PriceSnapshot.settlement_type == settlement.upper())
            .group_by(PriceSnapshot.ticker)
            .subquery()
        )

        query = (
            select(Bond, PriceSnapshot)
            .join(subq, Bond.ticker == subq.c.ticker)
            .join(PriceSnapshot, PriceSnapshot.id == subq.c.max_id)
        )

        if bond_type:
            query = query.where(Bond.bond_type == bond_type.upper())
        else:
            query = query.where(Bond.bond_type.not_in(HIDDEN_TYPES))

        results = db.execute(query).all()
        quotes = []
        for bond, snap in results:
            quotes.append(
                BondQuoteView(
                    ticker=bond.ticker,
                    name=bond.name,
                    bond_type=bond.bond_type,
                    law=bond.law,
                    maturity_date=bond.maturity_date,
                    settlement_type=snap.settlement_type,
                    price_ars=float(snap.price_ars) if snap.price_ars is not None else None,
                    price_mep=float(snap.price_mep) if snap.price_mep is not None else None,
                    price_ccl=float(snap.price_ccl) if snap.price_ccl is not None else None,
                    last_price=float(snap.last_price) if snap.last_price is not None else None,
                    day_difference=float(snap.day_difference) if snap.day_difference is not None else None,
                    volume_millions=float(snap.volume_millions) if snap.volume_millions is not None else None,
                    technical_value=float(snap.technical_value) if snap.technical_value is not None else None,
                    parity_percentage=float(snap.parity_percentage) if snap.parity_percentage is not None else None,
                    ytm_percentage=float(snap.ytm_percentage) if snap.ytm_percentage is not None else None,
                    tem_percentage=float(snap.tem_percentage) if snap.tem_percentage is not None else None,
                    tna_percentage=float(snap.tna_percentage) if snap.tna_percentage is not None else None,
                    modified_duration=float(snap.modified_duration) if snap.modified_duration is not None else None,
                    timestamp=snap.timestamp
                )
            )
        return quotes
