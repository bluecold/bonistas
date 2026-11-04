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

logger = logging.getLogger(__name__)

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

    def seed_initial_bonds(self, db: Session) -> int:
        """Siembra el catálogo inicial de bonos si no están cargados."""
        count_created = 0
        for item in INITIAL_BONDS:
            ticker = item["ticker"]
            existing = db.execute(select(Bond).where(Bond.ticker == ticker)).scalar_one_or_none()
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
            logger.info(f"Se crearon {count_created} bonos iniciales en la base de datos.")
        return count_created

    async def ingest_market_data(self, db: Session) -> Dict[str, Any]:
        """
        Ejecuta el ciclo de ingesta completo:
        1. Cotizaciones de bonistas.com (bonds)
        2. Especies y tipos de cambio implícitos (fx)
        3. Dólares de referencia (DolarAPI)
        4. Variables macro
        """
        # Aseguramos catálogo sembrado
        self.seed_initial_bonds(db)

        # 1. Obtener datos externos
        bonds_data = await self.bonistas.fetch_bonds()
        fx_data = await self.bonistas.fetch_fx()
        dolar_quotes = await self.dolar_api.get_rates_dict()
        macro_data = await self.macro.fetch_macro_snapshot()

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
            if base_ticker.endswith("_PUT") or base_ticker.endswith("_TAM"):
                base_ticker = base_ticker.split("_")[0]

            # Buscar si existe el bono en el maestro
            bond = db.execute(select(Bond).where(Bond.ticker == base_ticker)).scalar_one_or_none()
            if not bond:
                # Si no está en el catálogo, inferir y registrar dinámicamente
                family = b_raw.get("bond_family", "") or ""
                law_code = b_raw.get("bond_law", "LA")
                law = "NY" if "LNY" in law_code or "NY" in law_code else "ARG"
                
                bond_type = "HARD_DOLLAR"
                if "CER" in family:
                    bond_type = "CER"
                elif "FIJA" in family or "CUPON-FIJO" in family:
                    bond_type = "TASA_FIJA"
                elif "DUAL" in family:
                    bond_type = "DUAL"
                elif "BOPREAL" in family:
                    bond_type = "BOPREAL"
                elif "DOLAR-LINKED" in family:
                    bond_type = "DOLLAR_LINKED"
                elif "TAMAR" in family or "BADLAR" in family:
                    bond_type = "TAMAR"

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

            # Extraer precios de las 3 especies
            price_ars = None
            price_mep = None
            price_ccl = None
            last_price = b_raw.get("last_price")

            # Cruzar con fx_map para obtener simultáneamente ARS, D y C
            fx_info = fx_map.get(f"{base_ticker}_{settlement}") or fx_map.get(f"{base_ticker}_24HS")
            if fx_info:
                price_ars = fx_info.get("price_ars")
                price_mep = fx_info.get("price_usd")
                price_ccl = fx_info.get("price_cable")
            else:
                # Si el ticker termina en D (especie MEP)
                if raw_ticker.endswith("D") and len(raw_ticker) in (5, 6):
                    price_mep = last_price
                elif raw_ticker.endswith("C") and len(raw_ticker) in (5, 6):
                    price_ccl = last_price
                elif bond.currency == "ARS":
                    price_ars = last_price

            # Conversión de métricas financieras
            fair_val = b_raw.get("fair_value")
            parity = b_raw.get("parity")
            tir = b_raw.get("tir")
            mtir = b_raw.get("mtir")
            tna = b_raw.get("tna")
            mod_dur = b_raw.get("modified_duration")
            vol = b_raw.get("volume")
            diff = b_raw.get("day_difference")

            # Crear snapshot
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

        for k, v in macro_data.items():
            existing_macro = db.execute(
                select(MacroIndicator).where(MacroIndicator.date == today, MacroIndicator.name == k)
            ).scalar_one_or_none()
            if existing_macro:
                existing_macro.value = v
            else:
                db.add(MacroIndicator(date=today, name=k, value=v, source="MacroConnector"))

        db.commit()
        logger.info(f"Ingesta finalizada exitosamente: {snapshots_created} snapshots registrados.")

        return {
            "timestamp": now.isoformat(),
            "snapshots_created": snapshots_created,
            "dolares": dolar_quotes,
            "macro": {k: float(v) for k, v in macro_data.items()}
        }

    def get_latest_quotes(self, db: Session, bond_type: Optional[str] = None) -> List[BondQuoteView]:
        """Obtiene las cotizaciones más recientes consolidadas para cada bono."""
        # Subconsulta del timestamp más reciente por ticker
        subq = (
            select(
                PriceSnapshot.ticker,
                func.max(PriceSnapshot.id).label("max_id")
            )
            .group_by(PriceSnapshot.ticker)
            .subquery()
        )

        query = (
            select(Bond, PriceSnapshot)
            .join(subq, Bond.ticker == subq.c.ticker)
            .join(PriceSnapshot, PriceSnapshot.id == subq.c.max_id)
        )

        if bond_type:
            query = query.where(Bond.bond_type == bond_type)

        results = db.execute(query).all()
        quotes = []
        for bond, snap in results:
            quotes.append(
                BondQuoteView(
                    ticker=bond.ticker,
                    name=bond.name,
                    bond_type=bond.bond_type,
                    law=bond.law,
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
