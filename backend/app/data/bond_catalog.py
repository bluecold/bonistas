"""
Catálogo maestro de bonos soberanos y letras de la República Argentina.
Contiene metadatos financieros, amortizaciones, legislación y cupones según la especificación v1.0.
"""

from datetime import date
from decimal import Decimal
from typing import List, Dict, Any

INITIAL_BONDS: List[Dict[str, Any]] = [
    # ==========================================
    # 1. HARD DOLLAR - LEY NUEVA YORK (Globales GD)
    # ==========================================
    {
        "ticker": "GD29",
        "name": "Global 2029 (Ley NY)",
        "isin": "US040114HX11",
        "currency": "USD",
        "law": "NY",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2029, 7, 9),
        "coupon_rate": Decimal("0.0100"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Global República Argentina USD 2029 Ley NY",
        "description": "Amortización en 10 cuotas semestrales iguales a partir de enero 2025. Cupones crecientes."
    },
    {
        "ticker": "GD30",
        "name": "Global 2030 (Ley NY)",
        "isin": "US040114HS26",
        "currency": "USD",
        "law": "NY",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2030, 7, 9),
        "coupon_rate": Decimal("0.0075"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Global República Argentina USD 2030 Ley NY",
        "description": "Amortización en 12 cuotas semestrales iguales a partir de julio 2024. Cupones step-up."
    },
    {
        "ticker": "GD35",
        "name": "Global 2035 (Ley NY)",
        "isin": "US040114HT09",
        "currency": "USD",
        "law": "NY",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2035, 7, 9),
        "coupon_rate": Decimal("0.04125"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Global República Argentina USD 2035 Ley NY",
        "description": "Amortización en 10 cuotas semestrales a partir de enero 2031."
    },
    {
        "ticker": "GD38",
        "name": "Global 2038 (Ley NY)",
        "isin": "US040114HU71",
        "currency": "USD",
        "law": "NY",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2038, 1, 9),
        "coupon_rate": Decimal("0.0425"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Global República Argentina USD 2038 Ley NY",
        "description": "Amortización semestral a partir de julio 2027. Cláusulas de indentura 2005/2016."
    },
    {
        "ticker": "GD41",
        "name": "Global 2041 (Ley NY)",
        "isin": "US040114HV54",
        "currency": "USD",
        "law": "NY",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2041, 7, 9),
        "coupon_rate": Decimal("0.0350"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Global República Argentina USD 2041 Ley NY",
        "description": "Amortización en 28 cuotas semestrales a partir de enero 2028."
    },
    {
        "ticker": "GD46",
        "name": "Global 2046 (Ley NY)",
        "isin": "US040114HW38",
        "currency": "USD",
        "law": "NY",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2046, 7, 9),
        "coupon_rate": Decimal("0.0350"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Global República Argentina USD 2046 Ley NY",
        "description": "Amortización en 40 cuotas semestrales a partir de enero 2027."
    },

    # ==========================================
    # 2. HARD DOLLAR - LEY ARGENTINA (Bonares AL / AE)
    # ==========================================
    {
        "ticker": "AL29",
        "name": "Bonar 2029 (Ley ARG)",
        "isin": "ARARGE3209Y4",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2029, 7, 9),
        "coupon_rate": Decimal("0.0100"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bonar República Argentina USD 2029 Ley Local",
        "description": "Gemelo local de GD29. Amortización semestral desde enero 2025."
    },
    {
        "ticker": "AL30",
        "name": "Bonar 2030 (Ley ARG)",
        "isin": "ARARGE3209S6",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2030, 7, 9),
        "coupon_rate": Decimal("0.0075"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bonar República Argentina USD 2030 Ley Local",
        "description": "Gemelo local de GD30. Bono de mayor liquidez del mercado local argentino."
    },
    {
        "ticker": "AL35",
        "name": "Bonar 2035 (Ley ARG)",
        "isin": "ARARGE3209T4",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2035, 7, 9),
        "coupon_rate": Decimal("0.04125"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bonar República Argentina USD 2035 Ley Local",
        "description": "Gemelo local de GD35. Tramo medio-largo de la curva en dólares."
    },
    {
        "ticker": "AE38",
        "name": "Bonar 2038 (Ley ARG)",
        "isin": "ARARGE3209U2",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2038, 1, 9),
        "coupon_rate": Decimal("0.0425"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bonar República Argentina USD 2038 Ley Local",
        "description": "Gemelo local de GD38. Estructura de indentura similar a reestructuraciones previas."
    },
    {
        "ticker": "AL41",
        "name": "Bonar 2041 (Ley ARG)",
        "isin": "ARARGE3209V0",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "HARD_DOLLAR",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2041, 7, 9),
        "coupon_rate": Decimal("0.0350"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bonar República Argentina USD 2041 Ley Local",
        "description": "Gemelo local de GD41. Tramo ultra-largo."
    },

    # ==========================================
    # 3. TASA FIJA Y CAPITALIZABLES (LECAPs y BONCAPs)
    # ==========================================
    {
        "ticker": "S13N6",
        "name": "LECAP Noviembre 2026",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "TASA_FIJA",
        "amortization_type": "BULLET",
        "start_date": date(2026, 5, 15),
        "maturity_date": date(2026, 11, 13),
        "coupon_rate": Decimal("0.0375"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Letra del Tesoro Capitalizable Noviembre 2026",
        "description": "Capitalización mensual a tasa fija nominal."
    },
    {
        "ticker": "S30N6",
        "name": "LECAP 30 Noviembre 2026",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "TASA_FIJA",
        "amortization_type": "BULLET",
        "start_date": date(2026, 5, 29),
        "maturity_date": date(2026, 11, 30),
        "coupon_rate": Decimal("0.0380"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Letra del Tesoro Capitalizable 30 Nov 2026",
        "description": "Capitalización mensual a tasa fija nominal."
    },
    {
        "ticker": "T15E7",
        "name": "BONCAP Enero 2027",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "TASA_FIJA",
        "amortization_type": "BULLET",
        "start_date": date(2025, 7, 15),
        "maturity_date": date(2027, 1, 15),
        "coupon_rate": Decimal("0.0390"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono Capitalizable en Pesos Enero 2027",
        "description": "Bono a tasa fija capitalizable de mediano plazo."
    },
    {
        "ticker": "T30A7",
        "name": "BONCAP Abril 2027",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "TASA_FIJA",
        "amortization_type": "BULLET",
        "start_date": date(2025, 10, 15),
        "maturity_date": date(2027, 4, 30),
        "coupon_rate": Decimal("0.0395"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono Capitalizable en Pesos Abril 2027",
        "description": "Bono representativo del tramo medio de tasa fija en pesos."
    },
    {
        "ticker": "TY30P",
        "name": "Bono Tasa Fija 2030 con PUT",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "TASA_FIJA",
        "amortization_type": "BULLET",
        "start_date": date(2025, 6, 4),
        "maturity_date": date(2030, 5, 30),
        "coupon_rate": Decimal("0.2950"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono del Tesoro en Pesos Cupón Fijo 29.50% vto 2030",
        "description": "Cupón semestral a TNA 29.50% con opción de rescate (PUT)."
    },

    # ==========================================
    # 4. BONOS AJUSTADOS POR CER (BONCER / LECER)
    # ==========================================
    {
        "ticker": "TX26",
        "name": "BONCER 2026 2.0%",
        "isin": "ARARGE3206S8",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "CER",
        "amortization_type": "BULLET",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2026, 11, 9),
        "coupon_rate": Decimal("0.0200"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono del Tesoro Ajustado por CER 2.0% 2026",
        "description": "Amortización íntegra al vencimiento ajustado por Coeficiente de Estabilización de Referencia (CER)."
    },
    {
        "ticker": "TZX27",
        "name": "BONCER Cero Cupón 2027",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "CER",
        "amortization_type": "BULLET",
        "start_date": date(2024, 2, 14),
        "maturity_date": date(2027, 6, 30),
        "coupon_rate": Decimal("0.0"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono del Tesoro CER TZX27 Cero Cupón",
        "description": "Bono cupón cero ajustado íntegramente por CER."
    },
    {
        "ticker": "TZX28",
        "name": "BONCER Cero Cupón 2028",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "CER",
        "amortization_type": "BULLET",
        "start_date": date(2024, 4, 15),
        "maturity_date": date(2028, 6, 30),
        "coupon_rate": Decimal("0.0"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono del Tesoro CER TZX28 Cero Cupón",
        "description": "Bono representativo del tramo intermedio de la curva real."
    },
    {
        "ticker": "TX31",
        "name": "BONCER 2031 2.5%",
        "isin": "ARARGE320703",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "CER",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2020, 9, 4),
        "maturity_date": date(2031, 11, 30),
        "coupon_rate": Decimal("0.0250"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono del Tesoro Ajustado por CER 2.5% 2031",
        "description": "Amortización en cuotas semestrales en el tramo largo de la curva CER."
    },
    {
        "ticker": "DICP",
        "name": "Bono Discount en Pesos CER",
        "isin": "ARARGE03E339",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "CER",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2005, 12, 31),
        "maturity_date": date(2033, 12, 31),
        "coupon_rate": Decimal("0.0583"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono Discount República Argentina en Pesos CER",
        "description": "Bono largo histórico de la reestructuración 2005. Alta convexidad y duración."
    },

    # ==========================================
    # 5. BONOS DUALES (CER / TAMAR)
    # ==========================================
    {
        "ticker": "TXMD8",
        "name": "Bono Dual Diciembre 2028 (CER / TAMAR)",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "DUAL",
        "amortization_type": "BULLET",
        "start_date": date(2025, 5, 30),
        "maturity_date": date(2028, 12, 15),
        "coupon_rate": Decimal("0.0"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono Dual TAMAR o CER Diciembre 2028",
        "description": "Paga el máximo rendimiento acumulado entre la tasa TAMAR mayorista y la inflación CER."
    },
    {
        "ticker": "TXMJ0",
        "name": "Bono Dual Junio 2030 (CER / TAMAR)",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "DUAL",
        "amortization_type": "BULLET",
        "start_date": date(2025, 6, 30),
        "maturity_date": date(2030, 6, 28),
        "coupon_rate": Decimal("0.0"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono Dual TAMAR o CER Junio 2030",
        "description": "Opción implícita de cobertura óptima ante incertidumbre de tasas o inflación."
    },

    # ==========================================
    # 6. BONOS BOPREAL (Deuda BCRA para Importadores)
    # ==========================================
    {
        "ticker": "BPA7D",
        "name": "BOPREAL Serie 1 Tramo A",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "BOPREAL",
        "amortization_type": "BULLET",
        "start_date": date(2024, 1, 15),
        "maturity_date": date(2027, 10, 31),
        "coupon_rate": Decimal("0.0500"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono para la Reconstrucción de una Argentina Libre Serie 1A",
        "description": "Emitido por el BCRA en USD, amortizable al vencimiento con opción de cancelación tributaria anticipada."
    },
    {
        "ticker": "BPB7D",
        "name": "BOPREAL Serie 1 Tramo B",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "BOPREAL",
        "amortization_type": "BULLET",
        "start_date": date(2024, 1, 15),
        "maturity_date": date(2027, 10, 31),
        "coupon_rate": Decimal("0.0500"),
        "base_nominal": Decimal("100.0"),
        "short_description": "BOPREAL Serie 1B",
        "description": "Serie 1 Tramo B amortizable al vencimiento."
    },
    {
        "ticker": "BPC7D",
        "name": "BOPREAL Serie 1 Tramo C",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "BOPREAL",
        "amortization_type": "BULLET",
        "start_date": date(2024, 1, 15),
        "maturity_date": date(2027, 10, 31),
        "coupon_rate": Decimal("0.0500"),
        "base_nominal": Decimal("100.0"),
        "short_description": "BOPREAL Serie 1C",
        "description": "Serie 1 Tramo C."
    },
    {
        "ticker": "BPA8D",
        "name": "BOPREAL Serie 3",
        "currency": "USD",
        "law": "ARG",
        "bond_type": "BOPREAL",
        "amortization_type": "SEMESTRAL",
        "start_date": date(2024, 3, 1),
        "maturity_date": date(2028, 10, 31),
        "coupon_rate": Decimal("0.0300"),
        "base_nominal": Decimal("100.0"),
        "short_description": "BOPREAL Serie 3 3.0% vto 2028",
        "description": "Serie 3 con cupones semestrales y amortización en tres cuotas consecutivas."
    },

    # ==========================================
    # 7. DÓLAR LINKED (Ajustables por TC Oficial A3500)
    # ==========================================
    {
        "ticker": "TZV27",
        "name": "Bono Dólar Linked Junio 2027",
        "currency": "ARS",
        "law": "ARG",
        "bond_type": "DOLLAR_LINKED",
        "amortization_type": "BULLET",
        "start_date": date(2024, 6, 30),
        "maturity_date": date(2027, 6, 30),
        "coupon_rate": Decimal("0.0"),
        "base_nominal": Decimal("100.0"),
        "short_description": "Bono Dólar Linked Cero Cupón Junio 2027",
        "description": "Ajustado según la evolución del Tipo de Cambio Oficial Mayorista BCRA A3500."
    }
]

