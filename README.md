# 📈 Sistema Cuantitativo de Monitoreo, Valuación y Arbitraje de Bonos Argentinos (v1.0)

Plataforma financiera de alto rendimiento en tiempo real para el análisis, valuación y detección automática de oportunidades de arbitraje en el mercado de renta fija soberana y subsoberana de la República Argentina.

Desarrollado bajo las especificaciones técnicas formales de [especificacion-sistema-trading-bonos-argentinos.md](file:///d:/Mis%20Cosas/test/bonistas/especificacion-sistema-trading-bonos-argentinos.md).  
Para una explicación exhaustiva de arquitectura, decisiones cuantitativas y memoria de desarrollo para agentes de IA, consultar [PROJECT_CONTEXT.md](file:///d:/Mis%20Cosas/test/bonistas/PROJECT_CONTEXT.md).

---

## 🚀 Inicio Rápido (Quickstart)

### 1. Iniciar el Servidor y Dashboard Web
El backend (FastAPI + APScheduler) y el Frontend Web interactivo (TailwindCSS + Plotly.js) se ejecutan conjuntamente en un único proceso:

```bash
.\.venv\Scripts\python.exe -m backend.main
```

Una vez iniciado:
* **Dashboard Web Principal**: Abrir [http://localhost:8050](http://localhost:8050) en el navegador.
* **Documentación Interactiva Swagger / OpenAPI**: [http://localhost:8050/docs](http://localhost:8050/docs)
* **Especificación ReDoc**: [http://localhost:8050/redoc](http://localhost:8050/redoc)

> *(El puerto por defecto es `8050` para evitar conflictos con otras aplicaciones en el puerto 8000. Puedes cambiarlo libremente definiendo la variable de entorno `PORT`)*.

### 2. Ejecutar la Suite Completa de Pruebas Automatizadas
```bash
.\.venv\Scripts\pytest.exe backend/tests/ -v
```
*(83 pruebas, offline y sobre una base temporal: no tocan `bonistas.db` ni necesitan internet)*

---

## 🏛️ Arquitectura del Sistema

```
bonistas/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes.py              # Endpoints REST (Bonds, Quotes, Quant, Arbitrage, Swaps)
│   │   ├── arbitrage/
│   │   │   ├── engine.py              # Motor algorítmico y Command Center con semáforos
│   │   │   └── strategies.py          # Implementación de las 4 estrategias de arbitraje
│   │   ├── quant/
│   │   │   ├── cashflows.py           # Vectores de flujos de fondos (AL30, GD30, step-ups, bullets)
│   │   │   ├── fixed_income.py        # Valor Técnico, Paridad, TIR/YTM (Newton-Raphson), Duration
│   │   │   ├── arbitrage_math.py      # Ecuación Fisher (Breakeven), tipos de cambio implícitos, Z-score
│   │   │   └── swap_calculator.py     # Simulador de rotaciones con aranceles BYMA y comisión broker
│   │   ├── data/
│   │   │   ├── bond_catalog.py        # Maestro de bonos argentinos (Hard Dollar, CER, Tasa Fija, Duales)
│   │   │   ├── bonistas_client.py     # Conector en tiempo real con Bonistas.com
│   │   │   ├── dolar_api_client.py    # Conector en tiempo real con DolarAPI (MEP, CCL, Oficial, Blue)
│   │   │   └── macro_connectors.py    # Variables macroeconómicas (IPC, CER, TAMAR)
│   │   ├── db/
│   │   │   ├── models.py              # Modelos SQLAlchemy (bonds, price_snapshots, arbitrage_signals)
│   │   │   └── session.py             # Conexión y sesión de base de datos
│   │   ├── schemas/                   # Modelos Pydantic v2 para validación y serialización
│   │   └── static/
│   │       └── index.html             # Dashboard Web SPA interactivo (Plotly + TailwindCSS)
│   └── main.py                        # Servidor FastAPI con APScheduler y lifespan
├── backend/tests/                     # Test suite exhaustiva
└── requirements.txt                   # Dependencias del proyecto
```

---

## 🧠 Núcleo Cuantitativo & Algoritmos

### 1. Cronogramas y Flujos de Fondos Reales
* Modelado exacto de los prospectos de emisión de la reestructuración 2020:
  * **AL30 / GD30**: Amortizaciones escalonadas semestrales (4% en 2024, 4% en ene-25, 8% en jul-25, 8% en ene-26, 12% en jul-26, etc.) y cupones step-up.
  * **AL29 / GD29**: 10 cuotas del 10% semestral desde enero 2025.
  * **AL35 / GD35**, **AE38 / GD38**, **AL41 / GD41 / GD46**, títulos a **Tasa Fija** (LECAPs/BONCAPs), bonos **CER** y **Duales**.
* **Intereses Corridos**: Devengamiento continuo **Actual/365** sobre el capital residual vigente.
* **Valor Técnico y Paridad**: Coincidencia matemática exacta con las pantallas profesionales bursátiles.
* **TIR / YTM Numérica**: Resuelta en milisegundos mediante el algoritmo **Newton-Raphson** con gradiente analítico y fallback garantizado a **Brentq (`scipy.optimize`)**.

---

### 2. Las 4 Estrategias de Arbitraje Automatizadas

| Estrategia | Activos Involucrados | Regla de Activación | Acción Recomendada |
| :--- | :--- | :--- | :--- |
| **1. Spread de Legislación** | Bonares AL vs Globales GD | Ratio $\le 1.01$ o $\Delta \text{TIR} \le 20\text{ bps}$ | `ROTAR_A_NY` (Cobertura legal gratis) |
| | | Ratio $\ge 1.12$ o $Z \ge +1.5\sigma$ | `ROTAR_A_ARG` (Captura de brecha anormal) |
| **2. Relative Value Tramo Corto** | GD29 vs AL30 | Spread $\text{TIR}_{AL30} - \text{TIR}_{GD29} \ge 130\text{ bps}$ ($Z \ge +1.1\sigma$) | `SWAP_DURACION` (Mayor convexidad y rinde en AL30) |
| **3. Breakeven de Inflación** | LECAP/BONCAP vs BONCER | Inflación proyectada $>$ $Breakeven_{\text{TEM}} + 0.15\%$ | `COMPRAR_CER` (Ajuste CER + tasa real) |
| | | Inflación proyectada $<$ $Breakeven_{\text{TEM}} - 0.15\%$ | `COMPRAR_TASA_FIJA` (Fijar tasa real positiva) |
| **4. Cobertura con Bonos Duales** | TXMD8, TXMJ0 vs TAMAR/CER | Paridad del Bono Dual $\le 96\%$ | `COMPRAR_DUAL` (Opción implícita asimétrica) |

---

## 🖥️ Interfaz Web y Dashboard

1. **Monitor en Tiempo Real**: Tablas completas con filtrado por tipología de activo, cálculo simultáneo de especies (Pesos, MEP, Cable) y tipos de cambio implícitos.
2. **Curvas de Rendimiento Interactivas (Plotly.js)**: Gráfico de dispersión *Modified Duration vs. TIR (%)* con tooltip hover detallado y diferenciación visual de bonos según jurisdicción.
3. **Arbitrage Command Center**: Semáforos bursátiles (Verde / Amarillo / Rojo) y tarjetas de ejecución de trades con justificación cuantitativa y Z-score.
4. **Simulador de Swaps**: Calculadora donde el trader ingresa nominales a vender y el sistema computa los nominales a recibir del bono destino, descontando el costo por operación (por defecto 0,11% todo incluido). Ambas patas se valúan en la misma moneda (MEP o pesos).

