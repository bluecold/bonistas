"""
Datos de referencia diarios:
- CompararBonos: flujos futuros, valor técnico, pago final, etc. (tabla `reference_bonds`).
- BCRA: CER, TAMAR y A3500 (tabla `macro_indicators`, con su fecha y fuente reales).
- Inflación IPC (ArgentinaDatos), vía MacroDataConnector.

Cada fuente es independiente: si una falla, las demás se guardan igual.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.data.bcra_client import BcraClient
from backend.app.data.comparar_bonos_client import CompararBonosClient, ReferenceBondData
from backend.app.data.macro_connectors import MacroDataConnector
from backend.app.db.models import MacroIndicator, ReferenceBond
from backend.app.schemas.macro import MacroIndicatorCreate
from backend.app.services.source_health import source_health

logger = logging.getLogger(__name__)


def _parse_date(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


class ReferenceDataService:
    def __init__(
        self,
        comparar: Optional[CompararBonosClient] = None,
        bcra: Optional[BcraClient] = None,
        macro: Optional[MacroDataConnector] = None,
    ):
        self.comparar = comparar or CompararBonosClient()
        self.bcra = bcra or BcraClient()
        self.macro = macro or MacroDataConnector()

    # ------------------------------------------------------------------ escritura
    @staticmethod
    def store_reference(db: Session, refs: Dict[str, ReferenceBondData], meta: Dict[str, Any]) -> int:
        """Reemplaza por completo la tabla de referencia con la foto del día."""
        now = datetime.now(timezone.utc)
        market_date = _parse_date(meta.get("fechaRueda"))
        settlement_date = _parse_date(meta.get("liquidacion"))
        db.execute(delete(ReferenceBond))
        for r in refs.values():
            db.add(ReferenceBond(
                ticker_base=r.ticker_base, source="COMPARARBONOS", fetched_at=now,
                market_date=market_date, settlement_date=settlement_date, tipo=r.tipo,
                currency=r.moneda, flows=[[d.isoformat(), amt] for d, amt in r.flows],
                technical_value=r.technical_value, residual_capital=r.residual_capital,
                final_payment=r.final_payment, yield_is_real=r.yield_is_real,
                flows_cer_adjusted=r.flows_cer_adjusted, ref_ytm_pct=r.ref_ytm_pct,
                ref_duration=r.ref_duration,
                payment_structure=(r.payment_structure or None) and r.payment_structure[:200],
                species=r.species,
            ))
        db.commit()
        return len(refs)

    @staticmethod
    def store_macro(db: Session, items: Dict[str, MacroIndicatorCreate]) -> int:
        for name, item in items.items():
            existing = db.execute(
                select(MacroIndicator).where(MacroIndicator.date == item.date, MacroIndicator.name == name)
            ).scalar_one_or_none()
            if existing:
                existing.value = item.value
                existing.source = item.source
            else:
                db.add(MacroIndicator(date=item.date, name=name, value=item.value, source=item.source))
        db.commit()
        return len(items)

    # ------------------------------------------------------------------ ingesta
    async def refresh(self, db: Session) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        try:
            refs, meta = await self.comparar.fetch_reference()
            result["reference_bonds"] = self.store_reference(db, refs, meta)
            result["market_date"] = meta.get("fechaRueda")
            source_health.success("COMPARARBONOS", bonds=len(refs), market_date=meta.get("fechaRueda"))
        except Exception as e:
            db.rollback()
            source_health.failure("COMPARARBONOS", e)
            logger.error(f"CompararBonos: {e}")
            result["reference_error"] = str(e)

        macro: Dict[str, MacroIndicatorCreate] = {}
        try:
            bcra = await self.bcra.fetch_latest()
            macro.update(bcra)
            if bcra:
                source_health.success("BCRA", variables=sorted(bcra))
            else:
                source_health.failure("BCRA", "sin datos")
        except Exception as e:
            source_health.failure("BCRA", e)
            logger.error(f"BCRA: {e}")
        try:
            macro.update(await self.macro.fetch_macro_snapshot())
        except Exception as e:
            logger.warning(f"IPC: {e}")
        try:
            result["macro"] = {k: float(v.value) for k, v in macro.items()}
            self.store_macro(db, macro)
        except Exception as e:
            db.rollback()
            result["macro_error"] = str(e)
        return result

    # ------------------------------------------------------------------ lectura
    @staticmethod
    def get_reference(db: Session, ticker: str) -> Optional[ReferenceBond]:
        """Busca por ticker base o por cualquiera de sus especies (AL30D -> AL30)."""
        t = ticker.strip().upper()
        ref = db.get(ReferenceBond, t)
        if ref is not None:
            return ref
        for r in db.execute(select(ReferenceBond)).scalars():
            if t in (r.species or []):
                return r
        return None

    @staticmethod
    def flows_of(ref: ReferenceBond) -> List[Tuple[date, float]]:
        return [(date.fromisoformat(d), float(a)) for d, a in (ref.flows or [])]
