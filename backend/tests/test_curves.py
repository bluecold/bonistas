"""Curvas de rendimiento por familia: clasificación, ajuste, exclusiones y TIR propia."""

import math
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.models import ReferenceBond
from backend.app.db.session import Base
from backend.app.schemas.snapshot import BondQuoteView
from backend.app.services.curves_service import (
    CurvePoint, CurveSeries, apply_fit, build_curves, interp, own_yield,
)

TODAY = date(2026, 11, 4)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def ref(t, tipo, ccy="USD", species=None, maturity="2030-07-09", real=False, ytm=None, md=None, flows=None):
    return ReferenceBond(ticker_base=t, tipo=tipo, currency=ccy, species=species or [t],
                         flows=flows if flows is not None else [[maturity, 100.0]],
                         yield_is_real=real, ref_ytm_pct=ytm, ref_duration=md, flows_cer_adjusted=False)


def q(t, ytm, md, tem=None, price_mep=None, price_ars=None):
    return BondQuoteView(ticker=t, name=t, bond_type="X", law="ARG", settlement_type="24HS",
                         ytm_percentage=ytm, modified_duration=md, tem_percentage=tem,
                         price_mep=price_mep, price_ars=price_ars)


def pt(x, y):
    return CurvePoint(ticker=f"B{x}", species="", x=x, y=y, ytm=y, md=x, tem=None, days=None,
                      maturity=None, price=None, parity=None, source="T")


def test_log_fit_recovers_curve_and_residuals():
    s = CurveSeries("s", "#fff", points=[pt(x, 10 + 2 * math.log(x)) for x in (0.5, 1, 2, 4)])
    s.points[2].y += 0.5                         # un bono rinde 50 pb más que la curva
    apply_fit(s)
    assert s.fit and s.points[2].residual_bps > 30
    assert max(abs(p.residual_bps) for i, p in enumerate(s.points) if i != 2) < 30


def test_quadratic_fit_captures_hump():
    ys = {0.9: 4, 1.3: 11.6, 1.6: 13.2, 1.8: 14.3, 2.5: 16, 3.8: 14.6, 4.8: 14.0, 5.0: 13.8}
    s = CurveSeries("s", "#fff", points=[pt(x, y) for x, y in ys.items()])
    apply_fit(s)
    assert s.points[-1].residual_bps is not None and abs(s.points[-1].residual_bps) < 100


def test_fit_needs_three_points():
    s = CurveSeries("s", "#fff", points=[pt(1, 10), pt(2, 11)])
    apply_fit(s)
    assert s.fit == [] and s.points[0].residual_bps is None


def test_interp():
    c = [(1, 4.0), (3, 5.0)]
    assert interp(c, 2) == pytest.approx(4.5) and interp(c, 0.5) == 4.0 and interp(c, 9) == 5.0


def test_own_yield_zero_coupon():
    settle = date(2026, 11, 5)
    ytm, md = own_yield([(date(2027, 11, 5), 100.0)], 90.0, settle)
    assert ytm == pytest.approx((100 / 90 - 1) * 100, rel=1e-3)
    assert md == pytest.approx(1 / (1 + ytm / 100), rel=1e-2)


def test_build_curves_groups_and_exclusions(db):
    db.add_all([
        ref("AL30", "Soberano", species=["AL30D", "AL30C", "AL30"]),
        ref("GD30", "Soberano", species=["GD30D", "GD30C", "GD30"]),
        ref("AL29", "Soberano", species=["AL29D", "AL29"], maturity="2029-07-09"),
        ref("GD29", "Soberano", species=["GD29D", "GD29"], maturity="2029-07-09"),
        ref("BPA7", "Soberano", species=["BPA7D", "BPOA7"], maturity="2027-10-31"),
        ref("S13N6", "LECAP", ccy="ARS", maturity="2026-11-13"),            # vence en 9 días
        ref("T30A7", "BONCAP", ccy="ARS", maturity="2027-04-30"),
        ref("TZX27", "CER", ccy="ARS", maturity="2027-06-30", real=True),
        ref("TX26", "CER", ccy="ARS", real=False),                           # TIR nominal: fuera de la curva real
        ref("CO32", "Provincial", species=["CO32D"], flows=[["2032-12-01", 110.0]]),
        ref("UST5Y_30", "Treasury", ytm=4.2, md=3.3),
        ref("UY_31", "International", ytm=5.5, md=3.8),
        ref("ON01", "ON"),                                                   # ON: ninguna curva
    ])
    db.commit()
    quotes = {
        "AL30D": q("AL30D", 13.2, 1.65, price_mep=52.5), "AL30": q("AL30", 13.2, 1.65),
        "GD30D": q("GD30D", 10.9, 1.69), "AL29D": q("AL29D", 11.6, 1.27), "GD29D": q("GD29D", 10.0, 1.29),
        "BPA7D": q("BPA7D", 2.2, 0.72), "S13N6": q("S13N6", 27.0, 0.02, tem=2.0),
        "T30A7": q("T30A7", 29.5, 0.37, tem=2.18), "TZX27": q("TZX27", 3.8, 0.62),
        "TX26": q("TX26", 30.0, 0.1),
    }
    groups = {g.id: g for g in build_curves(db, quotes, today=TODAY, book_prices={"CO32D": (80.0, "MEP")})}

    sob = {s.name: s for s in groups["SOBERANOS_USD"].series}
    assert [p.ticker for p in sob["Bonares (ley local)"].points] == ["AL29", "AL30"]   # un punto por bono
    assert sob["Bonares (ley local)"].points[1].species == "AL30D"                     # especie D
    assert [p.ticker for p in sob["Globales (ley NY)"].points] == ["GD29", "GD30"]
    assert [p.ticker for p in sob["BOPREAL (BCRA)"].points] == ["BPA7"]

    tf = groups["TASA_FIJA"]
    assert [p.ticker for p in tf.series[0].points] == ["T30A7"] and tf.series[0].points[0].y == 2.18
    assert tf.excluded[0]["ticker"] == "S13N6" and "días" in tf.excluded[0]["reason"]

    assert [p.ticker for p in groups["CER"].series[0].points] == ["TZX27"]

    prov = groups["PROVINCIALES_USD"].series[0].points[0]
    assert prov.source == "PROPIO" and prov.ytm and prov.ytm > 0                      # TIR propia con precio BYMA

    region = {s.name: s for s in groups["REGION"].series}
    gd30 = next(p for p in region["Argentina (Globales)"].points if p.ticker == "GD30")
    assert gd30.spread_ust_bps == round((10.9 - 4.2) * 100)
    assert region["Uruguay"].points[0].spread_ust_bps == round((5.5 - 4.2) * 100)
    assert not any(p.ticker == "ON01" for g in groups.values() for s in g.series for p in s.points)


def test_api_curves(client):
    r = client.get("/api/v1/curves")
    assert r.status_code == 200
    groups = r.json()["groups"]
    assert groups and all({"id", "series", "excluded", "x_label"} <= set(g) for g in groups)


def test_comparar_duration_is_converted_to_modified(db):
    db.add(ref("UY_31", "International", ytm=5.0, md=4.2))
    db.add(ref("UST5Y_30", "Treasury", ytm=4.0, md=3.12))
    db.commit()
    region = {s.name: s for s in next(g for g in build_curves(db, {}, today=TODAY) if g.id == "REGION").series}
    assert region["Uruguay"].points[0].md == pytest.approx(4.2 / 1.05, abs=1e-3)


def test_own_yield_uses_usd_price_or_converts_pesos(db):
    flows = [["2027-11-05", 10.0], ["2028-11-05", 110.0]]
    db.add_all([
        ref("PROVA", "Provincial", species=["PROVA", "PRVAD"], flows=flows),
        ref("PROVB", "Provincial", species=["PROVB"], flows=flows),
    ])
    db.commit()
    prices = {"PROVA": (160000.0, "ARS"), "PRVAD": (100.0, "MEP"), "PROVB": (158500.0, "ARS")}
    g = next(g for g in build_curves(db, {}, today=TODAY, book_prices=prices, mep_reference=1585.0)
             if g.id == "PROVINCIALES_USD")
    pts = {p.ticker: p for s in g.series for p in s.points}
    assert pts["PROVA"].species == "PRVAD" and pts["PROVA"].ytm == pytest.approx(10.0, abs=0.1)   # par
    assert pts["PROVB"].species == "PROVB ÷ MEP" and pts["PROVB"].ytm == pytest.approx(10.0, abs=0.1)


def test_flows_without_price_reason(db):
    db.add_all([
        ref("PROVC", "Provincial", species=["PROVC"], flows=[["2028-11-05", 110.0]]),
        ref("PROVD", "Provincial", species=["PROVD"], flows=[["2028-11-05", 110.0]]),
    ])
    db.commit()
    g = next(g for g in build_curves(db, {}, today=TODAY, book_prices={"PROVD": (95.0, "MEP")})
             if g.id == "PROVINCIALES_USD")
    assert [p.ticker for s in g.series for p in s.points] == ["PROVD"]
    assert g.excluded == [{"ticker": "PROVC", "reason": "sin precio en BYMA para calcular la TIR"}]
