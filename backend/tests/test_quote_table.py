from types import SimpleNamespace

from backend.app.services.ingestion_service import classify_family, species_currency
from backend.app.services.quote_table import consolidate


def test_classify_family():
    assert classify_family("ONS") == "ON"
    assert classify_family("ONS-CABLE") == "ON"
    assert classify_family("") is None                      # acciones / CEDEARs
    assert classify_family("BONO-USD-LPA") == "HARD_DOLLAR"
    assert classify_family("BONO-USD-LDNY") == "HARD_DOLLAR"
    assert classify_family("LETRAS-FIJO-USD") == "TASA_FIJA"
    assert classify_family("BOPREAL-CABLE") == "BOPREAL"
    assert classify_family("BONO-CER") == "CER"
    assert classify_family("DUAL-CER-TAMAR") == "DUAL"
    assert classify_family("DUAL-CER-TAMAR-USD") == "DUAL"
    assert classify_family("ALGO-NUEVO") == "OTRO"


def test_species_currency():
    assert species_currency("BONO-USD-LPA", "AN29") == "ARS"
    assert species_currency("BONO-USD-LDA", "AN29D") == "MEP"
    assert species_currency("BONO-USD-LCNY", "GD30C") == "CCL"
    assert species_currency("ONS", "YM34O") == "ARS"
    assert species_currency("ONS", "YM34D") == "MEP"
    assert species_currency("ONS-CABLE", "YM34C") == "CCL"
    assert species_currency("LETRAS-FIJO-USD", "SN6D") == "MEP"
    assert species_currency("BONO-CER", "TZXD6") == "ARS"


def q(ticker, ars=None, mep=None, ccl=None, last=None, bond_type="HARD_DOLLAR", mat=None, ytm=10.0):
    return {"ticker": ticker, "name": ticker, "bond_type": bond_type, "law": "ARG", "maturity_date": mat,
            "settlement_type": "24HS", "price_ars": ars, "price_mep": mep, "price_ccl": ccl,
            "last_price": last, "ytm_percentage": ytm}


def test_consolidate_merges_species_and_fills_ars():
    rows = consolidate([
        q("AN29", last=126310.0),                 # sin precios por moneda (bono nuevo)
        q("AN29D", mep=80.0, last=80.0),
        q("AN29C", ccl=75.74, last=75.74),
        q("YM34O", ars=169300.0, last=169300.0, bond_type="ON"),
        q("YM34D", mep=107.25, last=107.25, bond_type="ON"),
        q("XYZ1D", mep=99.0, last=99.0, bond_type="ON"),   # especie sin pesos: fila propia
    ])
    by = {r["ticker"]: r for r in rows}
    assert set(by) == {"AN29", "YM34O", "XYZ1D"}
    assert by["AN29"]["price_ars"] == 126310.0
    assert by["AN29"]["price_mep"] == 80.0 and by["AN29"]["price_ccl"] == 75.74
    assert by["AN29"]["species"] == ["AN29C", "AN29D"]
    assert by["YM34O"]["price_mep"] == 107.25
    assert by["XYZ1D"]["price_mep"] == 99.0 and by["XYZ1D"]["price_ars"] is None
    assert not by["AN29"]["live"]


def test_consolidate_overlays_bullmarket():
    live = {
        "AL30": SimpleNamespace(last=81030.0, bid=81000.0, ask=81070.0, trade_time="16:16:53"),
        "AL30D": SimpleNamespace(last=51.32, bid=51.3, ask=51.32, trade_time="16:16:53"),
        "AL30C": SimpleNamespace(last=None, bid=None, ask=None, trade_time=None),  # sin datos: bonistas
        "BPA7D": SimpleNamespace(last=101.2, bid=101.2, ask=101.5, trade_time="16:15:49"),
    }
    rows = consolidate([
        q("AL30", ars=81040.0, mep=51.31, ccl=48.338, last=80990.0),
        q("AL30D", mep=51.29, last=51.29),
        q("AL30C", ccl=48.328, last=48.328),
        q("BPOA7", ars=159760.0, last=159760.0, bond_type="BOPREAL"),
    ], live)
    by = {r["ticker"]: r for r in rows}
    al = by["AL30"]
    assert al["price_ars"] == 81030.0 and al["price_mep"] == 51.32 and al["price_ccl"] == 48.328
    assert al["price_sources"] == {"ARS": "BULLMARKET", "MEP": "BULLMARKET", "CCL": "BONISTAS"}
    assert al["live"] and al["live_detail"]["MEP"]["time"] == "16:16:53"
    assert al["live_detail"]["MEP"]["kind"] == "ULTIMO"
    assert by["BPOA7"]["price_mep"] == 101.2          # especie D de BOPREAL encontrada en Bull Market


def test_live_price_outlier_uses_mid():
    from backend.app.services.quote_table import live_price
    # GD30C real: último 51.05 fuera de las puntas 49.898 / 50.32
    assert live_price(SimpleNamespace(last=51.05, bid=49.898, ask=50.32)) == (50.109, "PUNTA_MEDIA")
    assert live_price(SimpleNamespace(last=None, bid=50.0, ask=50.9)) == (50.45, "PUNTA_MEDIA")
    assert live_price(SimpleNamespace(last=50.1, bid=49.9, ask=50.3)) == (50.1, "ULTIMO")
    assert live_price(SimpleNamespace(last=50.1, bid=None, ask=50.3)) == (50.1, "ULTIMO")
    assert live_price(SimpleNamespace(last=None, bid=None, ask=50.3)) == (None, None)


def test_consolidate_links_peso_bonds_by_maturity_and_drops_placeholders():
    from datetime import date
    rows = consolidate([
        q("T30A7", ars=139.3, last=139.3, bond_type="TASA_FIJA", mat=date(2027, 4, 30)),
        q("TA7D", mep=0.088, last=0.088, bond_type="TASA_FIJA", mat=date(2027, 4, 30)),
        q("TZXD8", ars=88.79, last=88.79, bond_type="CER", mat=date(2028, 12, 15)),
        q("T2D8D", mep=0.057, last=0.057, bond_type="CER", mat=date(2028, 12, 15)),
        q("TXMD8", ars=95.5, last=95.5, bond_type="DUAL", mat=date(2028, 12, 15)),
        q("TXD8D", mep=0.06, last=0.06, bond_type="DUAL", mat=date(2028, 12, 15)),
        q("TB27", ars=0.01, last=0.01, bond_type="TAMAR", ytm=0.0),        # relleno de bonistas
    ])
    by = {r["ticker"]: r for r in rows}
    assert set(by) == {"T30A7", "TZXD8", "TXMD8"}
    assert by["T30A7"]["price_mep"] == 0.088 and by["T30A7"]["species"] == ["TA7D"]
    assert by["TZXD8"]["species"] == ["T2D8D"] and by["TXMD8"]["species"] == ["TXD8D"]
