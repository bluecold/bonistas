from datetime import date
from types import SimpleNamespace

from backend.app.arbitrage.fx_implied import (
    FxQuote, annotate_vs_reference, best_on_round_trips, implied_fx_quotes,
)
from backend.app.arbitrage.market_view import Book, Level, MarketView, combined_source
from backend.app.arbitrage.on_relative_value import analyze_ons, interpolate, profile_block, sovereign_fit
from backend.app.data.bullmarket_client import parse_stock_prices
from backend.app.services.trading_settings import TradingParams
from backend.tests.conftest import _load

PARAMS = TradingParams(commission_pct=0.11, min_net_profit_pct=0.4, trade_size_usd=500.0)


def _book(symbol, base, ccy, bid, ask, qty=1_000_000, source="BULLMARKET_ON", last=None):
    return Book(symbol, base, ccy, "24HS", [Level(bid, qty)] if bid else [], [Level(ask, qty)] if ask else [],
                last, None, None, source)


def _view(*books):
    v = MarketView(books={(b.symbol, b.settlement): b for b in books},
                   today=date(2026, 11, 6), next_bd=date(2026, 11, 11))
    v.mep_reference = 1580.0
    return v


# ---------------------------------------------------------------------------
# Punto 1: dólar a través de ON
# ---------------------------------------------------------------------------

def test_on_species_grouped_by_parent_ticker():
    rows = parse_stock_prices(_load("bullmarket_on_24hs.json")["result"], "2", use_parent=True)
    by = {r.symbol: r for r in rows}
    assert by["YM34D"].base_ticker == "YM34O" and by["YM34C"].base_ticker == "YM34O"
    assert by["YM34O"].base_ticker == "YM34O"
    # Sin use_parent (bonos) el sufijo no alcanza para deducir la especie en pesos
    assert {r.symbol: r for r in parse_stock_prices(_load("bullmarket_on_24hs.json")["result"], "2")}["YM34D"].base_ticker == "YM34D"


def test_bullmarket_on_counts_as_real_time():
    a = _book("YM34O", "YM34O", "ARS", 1, 2, source="BULLMARKET_ON")
    b = _book("AL30D", "AL30", "MEP", 1, 2, source="BULLMARKET")
    assert combined_source(a, b) == "BULLMARKET"


def test_on_cheaper_mep_and_round_trip_with_on():
    on = _view(_book("YM34O", "YM34O", "ARS", 168000, 168500), _book("YM34D", "YM34O", "MEP", 107.4, 107.5))
    bonds = _view(_book("AL30", "AL30", "ARS", 81000, 81050, source="BULLMARKET"),
                  _book("AL30D", "AL30", "MEP", 50.6, 50.62, source="BULLMARKET"))
    quotes = implied_fx_quotes(bonds, PARAMS) + implied_fx_quotes(on, PARAMS, instrument="ON")
    annotate_vs_reference(quotes)
    ym = next(q for q in quotes if q.base == "YM34O" and q.kind == "MEP")
    assert ym.instrument == "ON" and ym.buy_depth_ok
    assert ym.vs_reference_pct < -0.4                     # comprar MEP con la ON sale más barato
    trips = best_on_round_trips(quotes, PARAMS)
    t = next(t for t in trips if t.kind == "MEP" and t.settlement == "24HS")
    assert (t.buy_with, t.sell_with, t.instrument) == ("YM34O", "AL30", "ON")
    assert t.signal and t.net_pct >= 0.4 and t.source == "BULLMARKET"


def test_on_round_trip_requires_an_on_leg():
    q = lambda base, inst, buy, sell: FxQuote(base, "MEP", base, base + "D", "24HS", "24HS", buy, sell,
                                              True, True, 1000, instrument=inst)
    trips = best_on_round_trips([q("AL30", "BONO", 1500, 1490), q("GD30", "BONO", 1510, 1600)], PARAMS)
    assert trips == []


# ---------------------------------------------------------------------------
# Punto 2: valor relativo
# ---------------------------------------------------------------------------

def _bullet(maturity, coupon=7.0):
    """Cronograma simple: cupón semestral y amortización total al vencimiento (por 100 VN)."""
    rows, d = [], maturity
    dates = []
    while d > date(2026, 11, 11):
        dates.append(d)
        d = date(d.year - (1 if d.month <= 6 else 0), (d.month - 6 - 1) % 12 + 1, d.day)
    for x in sorted(dates):
        last = x == maturity
        rows.append(SimpleNamespace(date=x, coupon=coupon / 2, amortization=100.0 if last else 0.0,
                                    total=coupon / 2 + (100.0 if last else 0.0), residual=0.0 if last else 100.0))
    return SimpleNamespace(currency="USD", payment_currency="MEP", rows=rows)


def test_interpolate_and_sovereign_fit():
    assert interpolate([(1, 5), (3, 7)], 2) == 6
    assert interpolate([(1, 5), (3, 7)], 4.5, max_gap=1.0) is None
    assert interpolate([(1, 5), (3, 7)], 3.5, max_gap=1.0) == 7
    pts = [(1.0, 10.0), (2.0, 12.0), (4.0, 14.0)]
    assert abs(sovereign_fit(pts, 2.0) - 12.0) < 0.2
    assert sovereign_fit(pts, 8.0) is None                 # no extrapola


def test_issuer_spread_and_swap_idea():
    sch = {"AAA1O": _bullet(date(2029, 5, 15)), "AAA2O": _bullet(date(2029, 11, 15)),
           "AAA3O": _bullet(date(2030, 5, 15)), "BBB1O": _bullet(date(2028, 1, 10))}
    issuers = {"AAA1O": "Empresa A", "AAA2O": "Empresa A", "AAA3O": "Empresa A", "BBB1O": "Empresa B"}
    view = _view(
        _book("AAA1D", "AAA1O", "MEP", 100.9, 101.1),
        _book("AAA2D", "AAA2O", "MEP", 100.9, 101.1),
        _book("AAA3D", "AAA3O", "MEP", 95.4, 95.6),       # misma empresa, rinde mucho más: barata
        _book("BBB1D", "BBB1O", "MEP", 99.0, 99.2),
    )
    rows, ideas = analyze_ons(view, sch, issuers, {}, [(1.0, 10.0), (2.0, 12.0), (5.0, 14.0)], 0.11)
    by = {r.ticker: r for r in rows}
    assert by["AAA3O"].spread_vs_issuer_bps > 100 and by["AAA3O"].liquid
    assert by["BBB1O"].spread_vs_issuer_bps is None          # sin otras ON del emisor
    assert by["AAA1O"].spread_vs_sovereign_bps is not None
    assert ideas and ideas[0].buy == "AAA3O" and ideas[0].net_bps >= 50


def test_negative_tir_out_of_curves_and_swaps():
    sch = {"CCC1O": _bullet(date(2027, 5, 10)), "CCC2O": _bullet(date(2028, 5, 10))}
    view = _view(_book("CCC1D", "CCC1O", "MEP", 108.0, 108.2),   # muy sobre lo que paga: TIR < 0
                 _book("CCC2D", "CCC2O", "MEP", 100.0, 100.2))
    rows, ideas = analyze_ons(view, sch, {"CCC1O": "C", "CCC2O": "C"}, {}, [], 0.11)
    by = {r.ticker: r for r in rows}
    assert by["CCC1O"].tir_pct < 0 and any("negativa" in f for f in by["CCC1O"].flags)
    assert by["CCC2O"].spread_vs_issuer_bps is None and ideas == []


def test_on_relative_value_endpoint(client):
    res = client.get("/api/v1/arbitrage/on-relative-value")
    assert res.status_code == 200, res.text
    data = res.json()
    assert {"rows", "swap_ideas", "status", "schedules", "live"} <= set(data)
    assert data["status"]            # sin cronogramas descargados: explica por qué está vacío
    fx = client.get("/api/v1/arbitrage/fx-implied?kind=MEP").json()
    assert all("instrument" in q for q in fx["best_to_buy_usd"])


def test_on_full_name_picks_most_descriptive_species():
    from backend.app.services.market_book_service import MarketBookService, on_name_score
    from backend.app.services.quote_table import consolidate
    assert on_name_score("Mirgor. Clase IV. Tasa fija 8.25%. USD. Vto. 07-2027.") > \
        on_name_score("ON YPF - USD 8.25% - Vto 17/01/2034") > on_name_score("ON PAMPA ENERGIA S.A. Cl. XXIII V.16/12/34")
    svc = MarketBookService()
    svc._update_on_names(parse_stock_prices(_load("bullmarket_on_24hs.json")["result"], "2", use_parent=True))
    assert svc.on_names["MGCOO"] == "Pampa Energia. Clase XXIII. Tasa fija 7.875%. USD. Vto. 12-2034."
    assert svc.on_names["YM34O"].startswith("YPF S.A. Clase XXXIV") and svc.on_names["YM34D"] == svc.on_names["YM34O"]
    row = consolidate([{"ticker": "YM34O", "name": "YM34O", "bond_type": "ON", "price_ars": 1.0,
                        "ytm_percentage": 7.0}], {}, svc.on_names)[0]
    assert row["full_name"].startswith("YPF S.A.")


# ------------------------------------------------------------------ bloque de ON en la ficha
def test_profile_block_compares_against_issuer():
    sch = {"AAA1O": _bullet(date(2029, 5, 15)), "AAA2O": _bullet(date(2029, 11, 15)),
           "AAA3O": _bullet(date(2030, 5, 15))}
    issuers = {t: "Empresa A" for t in sch}
    view = _view(_book("AAA1D", "AAA1O", "MEP", 100.9, 101.1), _book("AAA2D", "AAA2O", "MEP", 100.9, 101.1),
                 _book("AAA3D", "AAA3O", "MEP", 95.4, 95.6))
    quotes = {"AAA3D": {"parity_percentage": 95.1, "volume_millions": 0.25},
              "AAA3O": {"parity_percentage": 95.3, "volume_millions": 1.5},
              "AAA1D": {"parity_percentage": 100.4, "volume_millions": None}}
    rows, _ = analyze_ons(view, sch, issuers, quotes, [(1.0, 10.0), (2.0, 12.0), (5.0, 14.0)], 0.11)
    block = profile_block("AAA3O", "Empresa A", rows, quotes)
    assert block["issuer"] == "Empresa A" and block["has_schedule"] and block["other_peers"] == 2
    assert block["spread_vs_issuer_bps"] > 100 and block["spread_vs_sovereign_bps"] is not None
    assert block["liquid"] is True and block["bid"] == 95.4 and block["ask"] == 95.6
    assert block["tir_buy_pct"] < block["tir_sell_pct"]      # comprar a la vendedora rinde menos
    assert block["volumes"] == [{"symbol": "AAA3O", "millions": 1.5}, {"symbol": "AAA3D", "millions": 0.25}]
    peers = block["peers"]
    assert [p["ticker"] for p in peers] == ["AAA1O", "AAA2O", "AAA3O"]          # por vencimiento
    assert [p["current"] for p in peers] == [False, False, True]
    assert peers[2]["parity_pct"] == 95.1 and peers[0]["parity_pct"] == 100.4   # especie D
    assert peers[1]["parity_pct"] is None


def test_profile_block_without_schedule_or_issuer():
    block = profile_block("ZZZ9O", None, [], {})
    assert block["has_schedule"] is False and block["peers"] == [] and block["other_peers"] == 0
    assert block["spread_vs_issuer_bps"] is None and block["liquid"] is None and block["flags"] == []


def test_profile_endpoint_includes_on_block(client):
    from backend.app.api import routes
    from backend.app.db.models import Bond
    from backend.app.db.session import SessionLocal

    db = SessionLocal()
    for t in ("YM34O", "YMCXO"):
        if db.get(Bond, t) is None:
            db.add(Bond(ticker=t, name=t, currency="USD", law="NY", bond_type="ON", maturity_date=date(2034, 1, 17)))
    db.commit()
    db.close()
    routes.ingestion_service.issuer_by_ticker.update({"YM34O": "YPF S.A.", "YMCXO": "YPF S.A."})
    before = routes.on_cashflow_service.prefetched_day

    res = client.get("/api/v1/bonds/YM34O/profile")
    assert res.status_code == 200, res.text
    on = res.json()["on"]
    assert on["issuer"] == "YPF S.A." and on["has_schedule"] and on["base"] == "YM34O"
    tickers = {p["ticker"]: p for p in on["peers"]}
    assert {"YM34O", "YMCXO"} <= set(tickers) and tickers["YM34O"]["current"]
    assert tickers["YMCXO"]["maturity"] == "2031-09-11"
    # Pedir las ON de un emisor no cuenta como la descarga diaria de todas las ON
    assert routes.on_cashflow_service.prefetched_day == before

    # Abrir la ficha por la especie D muestra el mismo bloque
    if client.get("/api/v1/bonds/YM34D/profile").status_code == 200:
        assert client.get("/api/v1/bonds/YM34D/profile").json()["on"]["base"] == "YM34O"

    # Los bonos no llevan bloque de ON
    assert client.get("/api/v1/bonds/AL30/profile").json()["on"] is None
