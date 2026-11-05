"""Cronogramas de provinciales desde Bruno618: parseo, validaciones, integración y resguardos."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.market_view import Book, Level, MarketView, build_market_view
from backend.app.data.bruno618_client import Bruno618Error, ProvincialSchedule, ScheduleRow, parse_schedule
from backend.app.db.models import ReferenceBond
from backend.app.db.session import Base
from backend.app.services.reference_data_service import ReferenceDataService

HTML = (Path(__file__).parent / "fixtures" / "bruno618_co32.html").read_text(encoding="utf-8")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def row(html_date, renta, amort, total, residual):
    return (f'<tr><td><time dateTime="{html_date}">x</time></td><td>{renta}</td><td>{amort}</td>'
            f'<td>{total}</td><td>{residual}</td></tr>')


def page(*rows, moneda="Dólares (USD)"):
    return f"<dl><dt>Moneda de pago</dt><dd>{moneda}</dd></dl><table><tbody>{''.join(rows)}</tbody></table>"


# ---------------------------------------------------------------------------
# Parseo y validaciones
# ---------------------------------------------------------------------------

def test_parse_real_page():
    s = parse_schedule("CO32", HTML)
    assert s.currency == "USD" and s.data_date == "05/11/2026" and len(s.rows) == 12
    assert s.rows[0] == ScheduleRow(date(2027, 1, 2), 4.88, 0.0, 4.88, 100.0)
    assert s.rows[-1].date == date(2032, 7, 2) and s.rows[-1].residual == 0.0
    assert sum(r.amortization for r in s.rows) == pytest.approx(100.0)
    assert sum(t for _, t in s.flows) == pytest.approx(148.9)


def test_parse_partially_amortized():
    s = parse_schedule("X", page(row("2027-04-27", "1,85", "7,69", "9,54", "46,14"),
                                 row("2027-10-27", "1,50", "46,14", "47,64", "0,00")))
    assert s.rows[0].residual + s.rows[0].amortization == pytest.approx(53.83)


@pytest.mark.parametrize("html,msg", [
    ("<html>sin tabla</html>", "no se encontró la tabla"),
    (page(row("2027-01-01", "1,00", "50,00", "52,00", "50,00"), row("2028-01-01", "1,00", "50,00", "51,00", "0,00")),
     "total"),
    (page(row("2027-01-01", "1,00", "50,00", "51,00", "50,00"), row("2028-01-01", "1,00", "40,00", "41,00", "0,00")),
     "residual inconsistente"),
    (page(row("2027-01-01", "1,00", "50,00", "51,00", "50,00")), "no amortiza"),
    (page(row("2027-01-01", "1,00", "100,00", "101,00", "0,00"), moneda=""), "moneda"),
])
def test_parse_rejects_bad_pages(html, msg):
    with pytest.raises(Bruno618Error) as e:
        parse_schedule("X", html)
    assert msg in str(e.value)


def test_parse_pesos_currency():
    s = parse_schedule("X", page(row("2027-01-01", "1,00", "100,00", "101,00", "0,00"), moneda="Pesos (ARS)"))
    assert s.currency == "ARS"


# ---------------------------------------------------------------------------
# Integración con los datos de referencia
# ---------------------------------------------------------------------------

def sched(t, rows, ccy="USD"):
    return ProvincialSchedule(t, ccy, "05/11/2026", [ScheduleRow(*r) for r in rows])


def test_merge_single_secondary_source_is_unverified(db):
    db.add(ReferenceBond(ticker_base="CO32", tipo="Provincial", currency="USD", species=["CO32D"], flows=[]))
    db.commit()
    res = ReferenceDataService.merge_provincial_schedules(db, {
        "BRUNO618": {"CO32": parse_schedule("CO32", HTML),
                     "ERM33": sched("ERM33", [(date(2027, 3, 4), 2.0, 100.0, 102.0, 0.0)]),
                     "PESOS": sched("PESOS", [(date(2027, 1, 1), 1.0, 100.0, 101.0, 0.0)], ccy="ARS")},
    }, today=date(2026, 11, 5))
    assert sorted(res["unverified"]) == ["CO32", "ERM33"] and res["added"] == ["ERM33"]
    assert res["skipped_ars"] == ["PESOS@BRUNO618"]
    co32 = db.get(ReferenceBond, "CO32")
    assert co32.flows_source == "BRUNO618" and co32.flows_verified is False
    assert co32.flows[0] == ["2027-01-02", 4.88] and co32.flows_detail[0] == ["2027-01-02", 4.88, 0.0, 4.88, 100.0]
    erm = db.get(ReferenceBond, "ERM33")
    assert erm.tipo == "Provincial" and erm.species == ["ERM33", "ERM33D"]


# ---------------------------------------------------------------------------
# Resguardo: fechas no verificadas no disparan señales cerca de un pago
# ---------------------------------------------------------------------------

def test_unverified_flows_near_payment_are_unknown():
    flows = {"CO32": ("USD", [(date(2027, 1, 2), 4.88), (date(2027, 7, 2), 4.88)])}
    v = MarketView(books={}, today=date(2026, 12, 31), next_bd=date(2027, 1, 4), flows_by_base=dict(flows),
                   unverified_bases={"CO32"})
    assert v.flow_between("CO32", "MEP", v.today, v.next_bd) == (0.0, "DESCONOCIDO")
    far = MarketView(books={}, today=date(2027, 3, 10), next_bd=date(2027, 3, 11), flows_by_base=dict(flows),
                     unverified_bases={"CO32"})
    assert far.flow_between("CO32", "MEP", far.today, far.next_bd) == (0.0, "SIN_PAGOS")
    verified = MarketView(books={}, today=date(2026, 12, 31), next_bd=date(2027, 1, 4), flows_by_base=dict(flows))
    assert verified.flow_between("CO32", "MEP", verified.today, verified.next_bd) == (4.88, "AJUSTADO")


def test_market_view_marks_bruno_flows_unverified(db):
    from backend.app.data.byma_client import BookRow
    from backend.app.services.market_book_service import MarketBookService
    db.add(ReferenceBond(ticker_base="CO32", tipo="Provincial", currency="USD", species=["CO32D"],
                         flows=[["2032-07-02", 35.66]], flows_source="BRUNO618"))
    db.commit()
    svc = MarketBookService()
    svc.store_rows(db, [BookRow("CO32D", "CO32D", "MEP", "24HS", 104.0, 100, 106.0, 100, None, None, None,
                                None, None, None, None)], "BYMA")
    view = build_market_view(db, ("BYMA",), book_service=svc)
    assert "CO32D" in view.unverified_bases and "CO32D" in view.flows_by_base


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_api_cashflows_detail_from_bruno(client):
    r = client.get("/api/v1/bonds/CO32D/cashflows")
    assert r.status_code == 200, r.text
    first = r.json()[0]
    assert first["source"] == "BRUNO618" and first["coupon_amount"] == 4.88 and first["residual_capital"] == 100.0
