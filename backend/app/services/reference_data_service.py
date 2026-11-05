"""
Datos de referencia diarios:
- CompararBonos: flujos futuros, valor técnico, pago final, etc. (tabla `reference_bonds`).
- Bruno618: cronogramas de provinciales en dólares que CompararBonos no publica (respaldo).
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
from backend.app.data.bruno618_client import Bruno618Client, ProvincialSchedule
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
        bruno: Optional[Bruno618Client] = None,
    ):
        self.comparar = comparar or CompararBonosClient()
        self.bruno = bruno or Bruno618Client()
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
                species=r.species, flows_source="COMPARARBONOS" if r.flows else None,
            ))
        db.commit()
        return len(refs)

    @staticmethod
    def merge_provincial_schedules(db: Session, schedules: Dict[str, ProvincialSchedule]) -> Dict[str, Any]:
        """
        Completa los provinciales en dólares con los cronogramas de Bruno618.
        - Si CompararBonos ya trae flujos para el bono, se respetan (Bruno618 es solo respaldo).
        - Si el bono existe sin flujos, se completan.
        - Si CompararBonos no lo tiene, se agrega como provincial (especies: ticker y ticker+D).
        """
        refs = list(db.execute(select(ReferenceBond)).scalars())
        by_symbol: Dict[str, ReferenceBond] = {}
        for r in refs:
            for t in [r.ticker_base, *(r.species or [])]:
                by_symbol.setdefault(t, r)
        added, filled, kept, skipped = [], [], [], []
        checks: Dict[str, Dict[str, Any]] = {}
        now = datetime.now(timezone.utc)
        for t, sch in schedules.items():
            if sch.currency != "USD":
                skipped.append(t)          # solo dólares: en pesos suelen tener ajuste o tasa variable
                continue
            flows = [[r.date.isoformat(), r.total] for r in sch.rows]
            detail = [[r.date.isoformat(), r.coupon, r.amortization, r.total, r.residual] for r in sch.rows]
            ref = by_symbol.get(t) or by_symbol.get(t + "D")
            if ref is not None and ref.flows:
                # Control cruzado contra CompararBonos, pago por pago (por posición)
                theirs = sorted((date.fromisoformat(d), float(v)) for d, v in ref.flows)
                ours = sorted((r.date, r.total) for r in sch.rows)
                n = min(len(theirs), len(ours))
                max_days = max((abs((theirs[i][0] - ours[i][0]).days) for i in range(n)), default=None)
                max_amt = max((abs(theirs[i][1] - ours[i][1]) for i in range(n)), default=None)
                ok = len(theirs) == len(ours) and (max_days or 0) <= 3 and (max_amt or 0) <= 0.05
                checks[t] = {"pagos_comparar": len(theirs), "pagos_bruno": len(ours),
                             "max_dias_diferencia": max_days,
                             "max_diferencia_monto": round(max_amt, 4) if max_amt is not None else None,
                             "coincide": ok}
                if not ok:
                    logger.warning(f"Bruno618 vs CompararBonos no coinciden en {t}: {checks[t]}")
                kept.append(t)
                continue
            if ref is None:
                ref = ReferenceBond(ticker_base=t, source="BRUNO618", fetched_at=now, tipo="Provincial",
                                    currency="USD", species=[t, t + "D"] if not t.endswith("D") else [t])
                db.add(ref)
                added.append(t)
            else:
                filled.append(ref.ticker_base)
            ref.flows = flows
            ref.flows_detail = detail
            ref.flows_source = "BRUNO618"
            ref.residual_capital = sch.rows[0].residual + sch.rows[0].amortization
        db.commit()
        return {"added": added, "filled": filled, "kept_comparar": kept, "skipped_ars": skipped,
                "cross_check": checks}

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

        if "reference_bonds" in result:
            try:
                schedules, errors = await self.bruno.fetch_schedules()
                merged = self.merge_provincial_schedules(db, schedules)
                result["provincial_schedules"] = dict(merged, errors=errors)
                if schedules:
                    source_health.success("BRUNO618", schedules=len(schedules), errors=len(errors),
                                          **{k: len(v) for k, v in merged.items() if k != "cross_check"})
                else:
                    source_health.failure("BRUNO618", f"sin cronogramas válidos ({len(errors)} errores)")
            except Exception as e:
                db.rollback()
                source_health.failure("BRUNO618", e)
                logger.error(f"Bruno618: {e}")
                result["provincial_error"] = str(e)

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
