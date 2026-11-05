"""Mercados Argentina: parseo de cronogramas y consenso entre fuentes de flujos provinciales."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.market_view import build_market_view
from backend.app.data.bruno618_client import ProvincialSchedule, ScheduleRow
from backend.app.data.mercados_argentina_client import MercadosArgentinaError, parse_schedule
from backend.app.db.models import ReferenceBond
from backend.app.db.session import Base
from backend.app.services.reference_data_service import ReferenceDataService, schedules_agree

HTML = (Path(__file__).parent / "fixtures" / "mercadosargentina_sj035.html").read_text(encoding="utf-8")
TODAY = date(2026, 11, 5)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def page(*rows, moneda="USD cable (CCL)"):
    trs = "".join(f"<tr><td>{d}</td><td>{r}</td><td>{a}</td><td>{t}</td><td></td></tr>" for d, r, a, t in rows)
    return f"<table><tr><th>Moneda de pago</th><td>{moneda}</td></tr></table>Cronograma de Pagos<table>{trs}</table>"


# ---------------------------------------------------------------------------
# Parseo
# ---------------------------------------------------------------------------

def test_parse_real_page_san_juan():
    s = parse_schedule("SJO35", HTML, TODAY)
    assert s.currency == "USD" and len(s.rows) == 18
    assert s.rows[0] == ScheduleRow(date(2027, 4, 1), 4.78, 0.0, 4.78, 100.0)
    assert [r.amortization for r in s.rows if r.amortization] == [33.0, 33.0, 34.0]
    assert s.rows[-1].residual == 0.0


def test_parse_drops_past_payments_and_rebuilds_residual():
    html = page(("01/03/2026", "3,00", "50,00", "53,00"), ("01/03/2027", "1,50", "50,00", "51,50"))
    s = parse_schedule("X", html, TODAY)
    assert len(s.rows) == 1 and s.rows[0].residual == 0.0 and s.rows[0].amortization == 50.0


@pytest.mark.parametrize("html,msg", [
    ("<html>sin cronograma</html>", "no publica cronograma"),
    (page(("01/03/2027", "1,00", "100,00", "102,00")), "total"),
    (page(("01/03/2027", "1,00", "60,00", "61,00"), ("01/09/2027", "1,00", "60,00", "61,00")), "amortizaciones"),
    (page(("01/03/2025", "1,00", "100,00", "101,00")), "sin pagos futuros"),
    (page(("01/03/2027", "1,00", "100,00", "101,00"), moneda="—"), "moneda"),
])
def test_parse_rejects(html, msg):
    with pytest.raises(MercadosArgentinaError) as e:
        parse_schedule("X", html, TODAY)
    assert msg in str(e.value)


# ---------------------------------------------------------------------------
# Consenso
# ---------------------------------------------------------------------------

def test_schedules_agree_tolerances():
    a = [(date(2027, 3, 1), 6.13), (date(2027, 9, 1), 6.02)]
    assert schedules_agree(a, [(date(2027, 3, 2), 6.1301), (date(2027, 9, 1), 6.0214)])
    assert not schedules_agree(a, [(date(2027, 3, 22), 6.13), (date(2027, 9, 22), 6.02)])   # 21 días
    assert not schedules_agree(a, a[:1])


def sch(t, rows):
    return ProvincialSchedule(t, "USD", None, [ScheduleRow(*r) for r in rows])


BA_GOOD = [(date(2027, 3, 1), 2.85, 3.28, 6.13, 82.76), (date(2027, 9, 1), 2.74, 82.76, 85.50, 0.0)]
BA_BAD = [(date(2027, 3, 22), 2.85, 3.28, 6.13, 82.76), (date(2027, 9, 22), 2.74, 82.76, 85.50, 0.0)]


def test_majority_beats_wrong_dates(db):
    """BA37D real: CompararBonos y Mercados Argentina coinciden; Bruno618 tiene las fechas corridas 21 días."""
    db.add(ReferenceBond(ticker_base="BA37D", tipo="Provincial", currency="USD", species=["BA7DD"],
                         flows=[["2027-03-01", 6.13], ["2027-09-01", 85.5]], flows_source="COMPARARBONOS"))
    db.commit()
    res = ReferenceDataService.merge_provincial_schedules(
        db, {"BRUNO618": {"BA37D": sch("BA37D", BA_BAD)}, "MERCADOSARG": {"BA37D": sch("BA37D", BA_GOOD)}},
        today=TODAY)
    ref = db.get(ReferenceBond, "BA37D")
    assert res["verified"] == ["BA37D"] and res["disagree"]["BA37D"]["descartado"] == [["BRUNO618"]]
    assert ref.flows_source == "COMPARARBONOS" and ref.flows_verified is True
    assert ref.flows[0] == ["2027-03-01", 6.13]
    assert ref.flows_detail[0][2] == 3.28                       # detalle de la fuente que coincide


def test_two_secondaries_agree_is_verified(db):
    db.add(ReferenceBond(ticker_base="CO32", tipo="Provincial", currency="USD", species=["CO32D"], flows=[]))
    db.commit()
    rows = [(date(2027, 1, 2), 4.88, 0.0, 4.88, 100.0), (date(2032, 7, 2), 1.66, 100.0, 101.66, 0.0)]
    res = ReferenceDataService.merge_provincial_schedules(
        db, {"BRUNO618": {"CO32": sch("CO32", rows)}, "MERCADOSARG": {"CO32": sch("CO32", rows)}}, today=TODAY)
    ref = db.get(ReferenceBond, "CO32")
    assert res["verified"] == ["CO32"] and ref.flows_verified is True and ref.flows_source == "MERCADOSARG"
    assert ref.flows_check["fuentes_coinciden"] == ["BRUNO618", "MERCADOSARG"]


def test_only_one_source_adds_unverified(db):
    res = ReferenceDataService.merge_provincial_schedules(
        db, {"MERCADOSARG": {"SJO35": parse_schedule("SJO35", HTML, TODAY)}}, today=TODAY)
    ref = db.get(ReferenceBond, "SJO35")
    assert res["added"] == ["SJO35"] and res["unverified"] == ["SJO35"]
    assert ref.flows_verified is False and ref.species == ["SJO35", "SJO5D", "SJO5C"]


def test_tie_without_agreement_prefers_comparar(db):
    db.add(ReferenceBond(ticker_base="BB37D", tipo="Provincial", currency="USD", species=["BB7DD"],
                         flows=[["2027-03-01", 6.13], ["2027-09-01", 85.5]], flows_source="COMPARARBONOS"))
    db.commit()
    ReferenceDataService.merge_provincial_schedules(db, {"BRUNO618": {"BB37D": sch("BB37D", BA_BAD)}}, today=TODAY)
    ref = db.get(ReferenceBond, "BB37D")
    assert ref.flows_source == "COMPARARBONOS" and ref.flows_verified is False
    assert ref.flows[0] == ["2027-03-01", 6.13]


def test_tie_between_secondaries_prefers_mercados_argentina(db):
    other = [(date(2027, 3, 1), 2.50, 0.0, 2.50, 100.0), (date(2027, 9, 1), 2.50, 100.0, 102.50, 0.0)]
    mine = [(date(2027, 3, 1), 2.62, 0.0, 2.62, 100.0), (date(2027, 9, 1), 2.62, 100.0, 102.62, 0.0)]
    res = ReferenceDataService.merge_provincial_schedules(
        db, {"BRUNO618": {"BC37D": sch("BC37D", other)}, "MERCADOSARG": {"BC37D": sch("BC37D", mine)}}, today=TODAY)
    ref = db.get(ReferenceBond, "BC37D")
    assert ref.flows_source == "MERCADOSARG" and ref.flows_verified is False and res["unverified"] == ["BC37D"]
    assert ref.flows[0] == ["2027-03-01", 2.62]


def test_verified_secondary_flows_lift_coupon_guard(db):
    from backend.app.data.byma_client import BookRow
    from backend.app.services.market_book_service import MarketBookService
    db.add(ReferenceBond(ticker_base="CO32", tipo="Provincial", currency="USD", species=["CO32D"],
                         flows=[["2032-07-02", 35.66]], flows_source="BRUNO618", flows_verified=True))
    db.commit()
    svc = MarketBookService()
    svc.store_rows(db, [BookRow("CO32D", "CO32D", "MEP", "24HS", 104.0, 100, 106.0, 100, None, None, None,
                                None, None, None, None)], "BYMA")
    view = build_market_view(db, ("BYMA",), book_service=svc)
    assert "CO32D" not in view.unverified_bases


def test_refresh_reports_both_sources(client):
    r = client.post("/api/v1/reference/refresh").json()
    ps = r["provincial_schedules"]
    assert "SJO35" in ps["added"] and "CO32" in ps["unverified"] + ps["verified"]


def test_reference_without_secondary_schedules_is_stale(db):
    from datetime import datetime, timezone
    from backend.main import reference_is_stale
    db.add(ReferenceBond(ticker_base="CO32", tipo="Provincial", currency="USD", species=["CO32D"], flows=[],
                         fetched_at=datetime.now(timezone.utc)))
    db.commit()
    assert reference_is_stale(db)                     # del día, pero sin cronogramas secundarios
    db.get(ReferenceBond, "CO32").flows_source = "MERCADOSARG"
    db.commit()
    assert not reference_is_stale(db)
