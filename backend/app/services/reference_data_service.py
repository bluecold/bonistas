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
from backend.app.data.mercados_argentina_client import BYMA_SPECIES, MercadosArgentinaClient
from backend.app.data.comparar_bonos_client import CompararBonosClient, ReferenceBondData
from backend.app.data.macro_connectors import MacroDataConnector
from backend.app.db.models import MacroIndicator, ReferenceBond
from backend.app.schemas.macro import MacroIndicatorCreate
from backend.app.services.source_health import source_health

logger = logging.getLogger(__name__)


SOURCE_RANK = {"COMPARARBONOS": 3, "MERCADOSARG": 2, "BRUNO618": 1}


def schedules_agree(a: List[Tuple[date, float]], b: List[Tuple[date, float]],
                    max_days: int = 3, max_amount: float = 0.05) -> bool:
    """Mismos pagos, fechas a <= max_days y montos a <= max_amount (por 100 VN)."""
    if len(a) != len(b) or not a:
        return False
    a, b = sorted(a), sorted(b)
    return all(abs((x[0] - y[0]).days) <= max_days and abs(x[1] - y[1]) <= max_amount for x, y in zip(a, b))


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
        mercados: Optional[MercadosArgentinaClient] = None,
    ):
        self.comparar = comparar or CompararBonosClient()
        self.bruno = bruno or Bruno618Client()
        self.mercados = mercados or MercadosArgentinaClient()
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
    def merge_provincial_schedules(db: Session, secondary: Dict[str, Dict[str, ProvincialSchedule]],
                                   today: Optional[date] = None) -> Dict[str, Any]:
        """
        Cronogramas de provinciales en dólares por CONSENSO entre fuentes.

        Fuentes: CompararBonos (ya guardada en la tabla) y las secundarias de `secondary`
        ({"BRUNO618": {...}, "MERCADOSARG": {...}}). Para cada bono:
        - Dos o más fuentes que coinciden (mismos pagos, fechas a <= 3 días, montos a <= 0,05)
          => flujos VERIFICADOS. Si CompararBonos está entre las que coinciden, se usan los suyos.
        - Si las fuentes no coinciden, gana el grupo mayoritario; con empate, el que incluye CompararBonos.
        - Con una sola fuente => NO verificados (el detector CI vs 24hs no opera cerca de un pago).
        Solo bonos en dólares (en pesos suelen tener ajuste o tasa variable).
        """
        today = today or date.today()
        refs = list(db.execute(select(ReferenceBond)).scalars())
        by_symbol: Dict[str, ReferenceBond] = {}
        for r in refs:
            for t in [r.ticker_base, *(r.species or [])]:
                by_symbol.setdefault(t, r)

        tickers = sorted({t for sch in secondary.values() for t in sch})
        report: Dict[str, Any] = {"verified": [], "unverified": [], "disagree": {}, "added": [],
                                  "skipped_ars": []}
        now = datetime.now(timezone.utc)
        for t in tickers:
            ref = by_symbol.get(t) or by_symbol.get(t + "D")
            cands: List[Tuple[str, List[Tuple[date, float]], Optional[list]]] = []
            if ref is not None and ref.flows and ref.flows_source in (None, "COMPARARBONOS"):
                flows = [(d, a) for d, a in ReferenceDataService.flows_of(ref) if d > today]
                if flows:
                    cands.append(("COMPARARBONOS", flows, None))
            for src, schedules in secondary.items():
                sch = schedules.get(t)
                if sch is None:
                    continue
                if sch.currency != "USD":
                    report["skipped_ars"].append(f"{t}@{src}")
                    continue
                rows = [r for r in sch.rows if r.date > today]
                if rows:
                    cands.append((src, [(r.date, r.total) for r in rows],
                                  [[r.date.isoformat(), r.coupon, r.amortization, r.total, r.residual]
                                   for r in rows]))
            if not cands:
                continue

            groups: List[List[int]] = []
            for i, c in enumerate(cands):
                for g in groups:
                    if schedules_agree(cands[g[0]][1], c[1]):
                        g.append(i)
                        break
                else:
                    groups.append([i])
            # Mayoría; con empate, la fuente más confiable (CompararBonos > Mercados Argentina > Bruno618)
            groups.sort(key=lambda g: (len(g), max(SOURCE_RANK.get(cands[i][0], 0) for i in g)), reverse=True)
            best = groups[0]
            verified = len(best) >= 2
            names = [cands[i][0] for i in best]
            chosen = max((cands[i] for i in best), key=lambda c: SOURCE_RANK.get(c[0], 0))
            detail = next((cands[i][2] for i in best if cands[i][2]), None)
            if len(groups) > 1:
                report["disagree"][t] = {"usado": names,
                                         "descartado": [[cands[i][0] for i in g] for g in groups[1:]]}

            if ref is None:
                species = BYMA_SPECIES.get(t) or ([t, t + "D"] if not t.endswith("D") else [t])
                ref = ReferenceBond(ticker_base=t, source=chosen[0], fetched_at=now, tipo="Provincial",
                                    currency="USD", species=species)
                db.add(ref)
                by_symbol[t] = ref
                report["added"].append(t)
            if chosen[0] != "COMPARARBONOS":
                ref.flows = [[d.isoformat(), a] for d, a in chosen[1]]
            if detail:
                ref.flows_detail = detail
                ref.residual_capital = detail[0][4] + detail[0][2]
            ref.flows_source = chosen[0]
            ref.flows_verified = verified
            ref.flows_check = {"fuentes_coinciden": names, "verificado": verified,
                               "grupos": [[cands[i][0] for i in g] for g in groups]}
            report["verified" if verified else "unverified"].append(t)
        db.commit()
        return report

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
        # Feriados primero: afectan la liquidación de 24hs y el corte de cupón
        from backend.app.services import holiday_service
        result["holidays"] = await holiday_service.refresh(db)

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
            secondary: Dict[str, Dict[str, ProvincialSchedule]] = {}
            errors: Dict[str, Dict[str, str]] = {}
            fetchers = (("BRUNO618", lambda: self.bruno.fetch_schedules()),
                        ("MERCADOSARG", lambda: self.mercados.fetch_schedules(after=date.today())))
            for name, fetch in fetchers:
                try:
                    schedules, errs = await fetch()
                    secondary[name], errors[name] = schedules, errs
                    if schedules:
                        source_health.success(name, schedules=len(schedules), errors=len(errs))
                    else:
                        source_health.failure(name, f"sin cronogramas válidos ({len(errs)} errores)")
                except Exception as e:
                    source_health.failure(name, e)
                    logger.error(f"{name}: {e}")
                    errors[name] = {"*": str(e)[:200]}
            try:
                merged = self.merge_provincial_schedules(db, secondary)
                result["provincial_schedules"] = dict(merged, errors=errors)
                if merged["disagree"]:
                    logger.warning(f"Cronogramas provinciales con fuentes en desacuerdo: {merged['disagree']}")
            except Exception as e:
                db.rollback()
                logger.error(f"Consenso de cronogramas: {e}")
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
