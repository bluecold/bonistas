"""
Tests de la etapa 4: conector de Bull Market en tiempo real.

- Parseo de la respuesta real (fixture recortado de temporal/json.txt, solo datos de mercado).
- Detección de sesión vencida (401/403, redirección, página HTML de login).
- Manejo de la cookie: normalización, guardado fuera del código, nunca expuesta por la API.
- Libros de 5 niveles, prioridad Bull Market > BYMA y descarte de puntas viejas.
- Confirmación de señales: TIEMPO_REAL / PARCIAL / DEMORA_20MIN según la fuente de las patas.

Ningún test sale a internet: el cliente se reemplaza en conftest o con httpx.MockTransport.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.arbitrage.ci_24hs import detect_ci_vs_24hs
from backend.app.arbitrage.engine import CONFIRMATION_BY_SOURCE, ArbitrageEngine
from backend.app.arbitrage.market_view import (
    Book, Level, MarketView, book_from_row, build_market_view, combined_source,
)
from backend.app.data import bullmarket_client as bmc
from backend.app.data.bullmarket_client import (
    BullMarketClient, BullMarketError, SessionExpiredError, classify_response, parse_stock_prices,
)
from backend.app.data.byma_client import BookRow
from backend.app.db.models import BookQuote
from backend.app.db.session import Base
from backend.app.services.bullmarket_session import (
    BullMarketSession, InvalidCookieError, normalize_cookie,
)
from backend.app.services.market_book_service import MarketBookService
from backend.app.services.trading_settings import TradingParams
from backend.tests.conftest import TEST_BM_COOKIE

# Guardado al importar (antes de que conftest reemplace el método por el simulado)
_REAL_FETCH_RAW = BullMarketClient.fetch_raw

FIXTURE = Path(__file__).parent / "fixtures" / "bullmarket_bonos_24hs.json"
PARAMS = TradingParams(commission_pct=0.11, min_net_profit_pct=0.40, trade_size_usd=500)


def bm_rows(term="2"):
    return [dict(r, term=term) for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["result"]]


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def session(tmp_path):
    return BullMarketSession(cookie_file=str(tmp_path / "secrets" / "bm.txt"), env_cookie="")


# ---------------------------------------------------------------------------
# Parseo
# ---------------------------------------------------------------------------

def test_parse_real_response_five_levels():
    rows = {(r.symbol, r.settlement): r for r in parse_stock_prices(bm_rows("2"))}
    ae38 = rows[("AE38", "24HS")]
    assert ae38.currency == "ARS" and ae38.base_ticker == "AE38"
    assert ae38.bid == 107910 and ae38.bid_qty == 2288 and ae38.ask == 107930
    assert [p for p, _ in ae38.bids] == [107910, 107900, 107860, 107850, 107820]
    assert len(ae38.asks) == 5 and ae38.asks[2] == (108690, 20000)
    assert ae38.last == 107910 and ae38.prev_close == 108010 and ae38.trades == 4396


def test_parse_currency_and_base_mapping():
    rows = {(r.symbol, r.settlement): r for r in parse_stock_prices(bm_rows("1"))}
    assert rows[("AL30D", "CI")].currency == "MEP" and rows[("AL30D", "CI")].base_ticker == "AL30"
    assert rows[("GD30C", "CI")].currency == "CCL" and rows[("GD30C", "CI")].base_ticker == "GD30"
    assert rows[("BPA7D", "CI")].base_ticker == "BPOA7"     # BOPREAL: especie en pesos con otro ticker
    assert rows[("AL30", "CI")].trade_time and len(rows[("AL30", "CI")].trade_time) == 8


def test_parse_side_without_offers():
    gd30c = next(r for r in parse_stock_prices(bm_rows()) if r.symbol == "GD30C")
    assert gd30c.bid is None and gd30c.bids == [] and gd30c.ask == 51.35


def test_parse_skips_unknown_term_and_garbage():
    rows = bm_rows()
    rows[0] = dict(rows[0], term="3")
    rows.append({"ticker": "", "currency": "ARS", "term": "2"})
    rows.append("basura")
    out = parse_stock_prices(rows)
    assert all(r.settlement in ("CI", "24HS") for r in out)
    assert "AE38" not in {r.symbol for r in out}


# ---------------------------------------------------------------------------
# Sesión vencida
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,ctype,body", [
    (401, "application/json", "{}"),
    (403, "text/html", "forbidden"),
    (302, "text/html", ""),
    (200, "text/html; charset=utf-8", "<!DOCTYPE html><html>Login</html>"),
    (200, "application/json", "  <html>login</html>"),
])
def test_classify_session_expired(status, ctype, body):
    with pytest.raises(SessionExpiredError):
        classify_response(status, ctype, body)


def test_classify_transient_error_is_not_expiry():
    with pytest.raises(BullMarketError) as e:
        classify_response(503, "text/plain", "busy")
    assert not isinstance(e.value, SessionExpiredError)
    classify_response(200, "application/json", '{"result": []}')   # no lanza


def _mock_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(bmc.httpx, "AsyncClient", factory)


async def test_real_fetch_sends_cookie_and_parses(monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["cookie"] = request.headers.get("cookie")
        seen["xrw"] = request.headers.get("x-requested-with")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"result": bm_rows(), "isBond": True})

    _mock_client(monkeypatch, handler)
    rows = await _REAL_FETCH_RAW(BullMarketClient(), "a=1; b=2", "1")
    assert len(rows) == len(bm_rows())
    assert seen["cookie"] == "a=1; b=2" and seen["xrw"] == "XMLHttpRequest"
    assert "term=1" in seen["url"] and "index=bonos" in seen["url"]


async def test_real_fetch_redirect_to_login_is_expiry(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(302, headers={"location": "/Home/Login"}))
    with pytest.raises(SessionExpiredError):
        await _REAL_FETCH_RAW(BullMarketClient(), "a=1", "2")


async def test_real_fetch_without_cookie_is_expiry():
    with pytest.raises(SessionExpiredError):
        await _REAL_FETCH_RAW(BullMarketClient(), "", "2")


# ---------------------------------------------------------------------------
# Cookie
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("a=1; b=2", "a=1; b=2"),
    ("cookie: a=1; b=2", "a=1; b=2"),
    ("Cookie: a=1;b=2\n", "a=1; b=2"),
    ("curl 'https://x' -H 'accept: */*' -H 'cookie: a=1; b=x%2Fy' --compressed", "a=1; b=x%2Fy"),
    ("curl 'https://x' -b 'a=1; b=2'", "a=1; b=2"),
    ("a=1\nb=2", "a=1; b=2"),
])
def test_normalize_cookie(raw, expected):
    assert normalize_cookie(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "sin pares", "=x", "a=1\x00b"])
def test_normalize_cookie_rejects(raw):
    with pytest.raises(InvalidCookieError):
        normalize_cookie(raw)


def test_session_store_and_clear(session):
    assert session.status == "NO_CONFIGURADA" and not session.should_poll
    session.set_cookie("cookie: a=1; b=2")
    assert session.cookie_file.read_text(encoding="utf-8") == "a=1; b=2"
    assert session.get_cookie() == "a=1; b=2" and session.status == "PENDIENTE" and session.should_poll
    d = session.to_dict()
    assert "a=1" not in json.dumps(d)     # el estado nunca incluye la cookie
    session.clear()
    assert not session.cookie_file.exists() and session.status == "NO_CONFIGURADA"


def test_session_env_fallback(tmp_path):
    s = BullMarketSession(cookie_file=str(tmp_path / "no_existe.txt"), env_cookie="x=1")
    assert s.get_cookie() == "x=1" and s.status == "PENDIENTE" and s.to_dict()["storage"] == ".env"


def test_session_expiry_notifies_once(session):
    session.set_cookie("a=1")
    assert session.mark_expired("HTTP 401") is True
    assert session.mark_expired("HTTP 401") is False
    assert session.status == "VENCIDA" and not session.should_poll
    session.set_cookie("a=2")                 # una cookie nueva reactiva la consulta
    assert session.should_poll and session.expired_at is None


# ---------------------------------------------------------------------------
# Ingesta y vista de mercado
# ---------------------------------------------------------------------------

async def test_ingest_without_cookie_does_not_poll(db_session, session):
    svc = MarketBookService(bm_session=session)
    assert await svc.ingest_bullmarket(db_session) == {"skipped": "NO_CONFIGURADA"}
    assert db_session.query(BookQuote).count() == 0


async def test_ingest_stores_depth_and_only_changes(db_session, session):
    session.set_cookie(TEST_BM_COOKIE)
    svc = MarketBookService(bm_session=session)
    res = await svc.ingest_bullmarket(db_session)
    assert session.status == "ACTIVA" and res["books"]["stored"] > 0
    q = db_session.execute(select(BookQuote).where(
        BookQuote.source == "BULLMARKET", BookQuote.symbol == "AE38", BookQuote.settlement == "CI")).scalar_one()
    assert len(q.depth["bids"]) == 5 and q.depth["asks"][0] == [107930, 790]
    assert ("AE38", "24HS") in svc.live["BULLMARKET"].keys

    again = await svc.ingest_bullmarket(db_session)
    assert again["books"]["stored"] == 0 and again["books"]["unchanged"] == res["books"]["stored"]


async def test_ingest_expired_cookie_stops_polling(db_session, session):
    session.set_cookie("cookie=vieja")
    svc = MarketBookService(bm_session=session)
    res = await svc.ingest_bullmarket(db_session)
    assert session.status == "VENCIDA" and svc.bm_just_expired and "error" in res
    assert await svc.ingest_bullmarket(db_session) == {"skipped": "VENCIDA"}
    assert not svc.bm_just_expired


def test_book_from_row_uses_depth():
    q = BookQuote(symbol="AL30D", base_ticker="AL30", currency="MEP", settlement="CI", bid=52.5, bid_qty=10,
                  ask=52.7, ask_qty=5, source="BULLMARKET",
                  depth={"bids": [[52.5, 10], [52.4, 100]], "asks": [[52.7, 5], [52.8, 50], ["x", 1]]})
    b = book_from_row(q)
    assert [l.price for l in b.bids] == [52.5, 52.4] and [l.price for l in b.asks] == [52.7, 52.8]
    q.depth = None
    assert len(book_from_row(q).bids) == 1


def _row(symbol, settlement, bid, ask, currency="MEP"):
    return BookRow(symbol=symbol, base_ticker=symbol.rstrip("DC") if currency != "ARS" else symbol,
                   currency=currency, settlement=settlement, bid=bid, bid_qty=1000, ask=ask, ask_qty=1000,
                   last=None, prev_close=None, volume_nominal=None, volume_amount=None, trades=None,
                   trade_time=None, maturity_date=None)


async def test_view_prefers_fresh_bullmarket_and_falls_back(db_session, session):
    session.set_cookie(TEST_BM_COOKIE)
    svc = MarketBookService(bm_session=session)
    svc.store_rows(db_session, [_row("AE38D", "24HS", 60.0, 61.0), _row("ZZ01D", "24HS", 10.0, 11.0)], "BYMA")
    await svc.ingest_bullmarket(db_session)

    view = build_market_view(db_session, ("BULLMARKET", "BYMA"), book_service=svc,
                             live_max_age={"BULLMARKET": 180})
    assert view.book("AE38D", "24HS").source == "BULLMARKET"
    assert view.book("ZZ01D", "24HS").source == "BYMA"           # solo en BYMA: se mantiene
    assert len(view.book("AE38", "24HS").bids) == 5

    # Última consulta OK hace 10 minutos (sesión vencida o caída): no se usan esas puntas
    svc.live["BULLMARKET"].fetched_at -= timedelta(minutes=10)
    view = build_market_view(db_session, ("BULLMARKET", "BYMA"), book_service=svc,
                             live_max_age={"BULLMARKET": 180})
    assert view.book("AE38D", "24HS").source == "BYMA"
    assert view.book("AE38", "24HS") is None


async def test_view_ignores_species_missing_from_last_snapshot(db_session, session):
    session.set_cookie(TEST_BM_COOKIE)
    svc = MarketBookService(bm_session=session)
    await svc.ingest_bullmarket(db_session)
    svc.live["BULLMARKET"].keys.discard(("AE38D", "24HS"))      # dejó de venir en la respuesta
    view = build_market_view(db_session, ("BULLMARKET", "BYMA"), book_service=svc,
                             live_max_age={"BULLMARKET": 180})
    assert view.book("AE38D", "24HS") is None and view.book("AL30D", "24HS") is not None


# ---------------------------------------------------------------------------
# Confirmación de señales
# ---------------------------------------------------------------------------

def _bk(settlement, bid, ask, source):
    return Book("XX27D", "XX27", "MEP", settlement, [Level(bid, 1e9)], [Level(ask, 1e9)],
                None, None, None, source)


def _ci_view(src_ci, src_24):
    books = {("XX27D", "CI"): _bk("CI", 101.0, 101.5, src_ci), ("XX27D", "24HS"): _bk("24HS", 99.5, 100.0, src_24)}
    return MarketView(books=books, today=date(2026, 11, 4), next_bd=date(2026, 11, 5), mep_reference=1585.0,
                      caucion_tna_pct=26.1, flows_by_base={"XX27": ("USD", [(date(2027, 6, 30), 100.0)])})


@pytest.mark.parametrize("src_ci,src_24,expected", [
    ("BULLMARKET", "BULLMARKET", "TIEMPO_REAL"),
    ("BULLMARKET", "BYMA", "PARCIAL"),
    ("BYMA", "BYMA", "DEMORA_20MIN"),
])
def test_ci_signal_confirmation(src_ci, src_24, expected):
    opps = [o for o in detect_ci_vs_24hs(_ci_view(src_ci, src_24), PARAMS) if o.signal]
    assert opps
    sigs = ArbitrageEngine._signals_from_ci(opps)
    assert {s.confirmation for s in sigs} == {expected}


def test_combined_source():
    a, b = _bk("CI", 1, 2, "BULLMARKET"), _bk("24HS", 1, 2, "BYMA")
    assert combined_source(a, a) == "BULLMARKET" and combined_source(a, b) == "MIXTO"
    assert combined_source(None) == "SIN_DATOS" and CONFIRMATION_BY_SOURCE["MIXTO"] == "PARCIAL"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_api_session_lifecycle(client):
    from backend.app.api.routes import bullmarket_session

    r = client.get("/api/v1/bullmarket/session")
    assert r.status_code == 200 and r.json()["status"] == "NO_CONFIGURADA"

    assert client.put("/api/v1/bullmarket/session", json={"cookie": "sin pares"}).status_code == 422

    r = client.put("/api/v1/bullmarket/session", json={"cookie": "cookie: " + TEST_BM_COOKIE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ACTIVA" and body["test"]["rows"] > 0
    assert "fixture" not in r.text                                   # la cookie no vuelve
    assert bullmarket_session.cookie_file.exists()

    status = client.get("/api/v1/status").json()
    assert status["bullmarket"]["status"] == "ACTIVA" and "fixture" not in json.dumps(status)
    assert status["sources"]["BULLMARKET"]["healthy"]

    books = client.get("/api/v1/books", params={"source": "BULLMARKET", "base_ticker": "AE38"}).json()
    ae38 = next(b for b in books if b["symbol"] == "AE38" and b["settlement"] == "24HS")
    assert len(ae38["depth"]["bids"]) == 5

    cc = client.get("/api/v1/arbitrage/command-center").json()
    assert cc["book_sources"]["counts"].get("BULLMARKET", 0) > 0

    r = client.put("/api/v1/bullmarket/session", json={"cookie": "a=vencida"})
    assert r.json()["status"] == "VENCIDA"

    r = client.delete("/api/v1/bullmarket/session")
    assert r.json()["status"] == "NO_CONFIGURADA" and not bullmarket_session.cookie_file.exists()
