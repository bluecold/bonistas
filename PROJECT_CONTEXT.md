# 🧠 Contexto Técnico y Memoria de Proyecto: Sistema de Trading y Arbitraje de Bonos Argentinos

> **Documento de Memoria y Contexto para Agentes de IA y Desarrolladores.**  
> Este archivo resume el propósito del proyecto, el estado actual de la implementación, las decisiones de diseño arquitectónicas y cuantitativas, las particularidades del mercado financiero argentino y la hoja de ruta para futuras ampliaciones.

---

## 1. Visión General del Proyecto

### 1.1 Objetivo
Desarrollar una plataforma cuantitativa en tiempo real para el mercado de capitales argentino, cuyo propósito es:
1. **Monitorear** cotizaciones, precios de liquidación (CI y 24hs), paridades y rendimientos de títulos públicos soberanos y subsoberanos.
2. **Valuar con precisión matemática profesional** títulos con flujos complejos (amortizaciones semestrales escalonadas, cupones step-up, capitalizables y ajustes por CER).
3. **Detectar y catalogar automáticamente oportunidades de arbitraje y valor relativo** entre diferentes curvas, legislaciones (Local vs. Nueva York), tasas fijas vs. reales y opciones implícitas de cobertura.
4. **Proporcionar un Command Center interactivo** con semáforos bursátiles y un simulador de rotación de cartera (*swaps*) con deducción de comisiones operativas.

---

## 2. Estado de Implementación (Lo que se hizo)

El desarrollo se ejecutó y validó al 100% en cuatro fases consecutivas:

### Fase 1: Arquitectura Base, Modelos y Pipeline de Ingesta
* **Entorno Virtual**: Python 3.13 en `.venv` con dependencias científicas (`fastapi`, `uvicorn`, `sqlalchemy 2.0`, `pydantic v2`, `httpx`, `scipy`, `numpy`, `pandas`, `apscheduler`, `pytest`).
* **Base de Datos Relacional**: Modelos en `backend/app/db/models.py` (`bonds`, `price_snapshots`, `arbitrage_signals`, `macro_indicators`).
* **Catálogo Maestro**: `backend/app/data/bond_catalog.py` sembrado con más de 20 activos representativos (Globales GD, Bonares AL, LECAPs/BONCAPs, BONCER, Duales, BOPREAL, Dólar Linked).
* **Conectores de Datos**:
  * `BonistasClient`: Conexión directa y resiliente con los endpoints internos JSON de `bonistas.com` (`/api/bonds`, `/api/fx/fx`, `/api/curves`).
  * `DolarApiClient`: Tipos de cambio en tiempo real vía `dolarapi.com` (Oficial, Bolsa/MEP, CCL, Mayorista A3500, Blue).
  * `MacroDataConnector`: Variables macroeconómicas (inflación IPC, CER, TAMAR).
* **Ingesta & Polling**: `IngestionService` orquestado con `APScheduler` ejecutando tareas en segundo plano cada 30 segundos.

### Fase 2: Motor Financiero Cuantitativo
* **Flujos de Fondos Reales (`backend/app/quant/cashflows.py`)**:
  * Modelado de las indenturas oficiales de la reestructuración 2020:
    * **AL30 / GD30**: Cupones step-up semestrales (9 ene y 9 jul) y amortizaciones escalonadas (4% jul-24, 4% ene-25, 8% jul-25, 8% ene-26, 12% jul-26, etc.).
    * **AL29 / GD29**: 10 cuotas semestrales iguales del 10% desde enero 2025.
    * **AL35 / GD35, AE38 / GD38, AL41 / GD41, GD46**, títulos Bullet y letras capitalizables.
* **Métricas de Renta Fija (`backend/app/quant/fixed_income.py`)**:
  * Intereses corridos devengados bajo convención **Actual/365** sobre capital residual vigente.
  * Capital residual exacto y Valor Técnico ($VT = \text{Residual} + \text{Intereses Corridos}$).
  * Paridad porcentual exacta ($P / VT \times 100$).
  * **Solucionador numérico de TIR / YTM**: Algoritmo analítico **Newton-Raphson** con gradiente exacto y fallback robusto a **Brentq (`scipy.optimize`)**.
  * Sensibilidad: Duración de Macaulay y **Modified Duration (MD)**.
  * Tasas equivalentes: Tasa Efectiva Mensual ($\text{TEM}$) y Tasa Nominal Anual ($\text{TNA}$).
* **Métricas de Arbitraje (`backend/app/quant/arbitrage_math.py`)**:
  * Tipos de cambio implícitos (MEP, CCL y Canje $C/D$).
  * Ecuación Fisher de Breakeven inflacionario mensual y anual entre tasa fija y CER.
  * Z-scores normalizados sobre ventanas históricas.

### Fase 3: Motor Algorítmico de Arbitrajes
* Implementación de las cuatro estrategias en `backend/app/arbitrage/strategies.py`:
  1. **Spread de Legislación (AL vs. GD)**:
     * Regla A (Ratio $\le 1.01$ o $\Delta \text{TIR} \le 20\text{ bps}$): `ROTAR_A_NY` (Free legal hedge).
     * Regla B (Ratio $\ge 1.12$ o $Z \ge +1.5\sigma$): `ROTAR_A_ARG` (Captura de brecha anormal).
  2. **Relative Value Tramo Corto (GD29 vs. AL30)**:
     * Señal `SWAP_DURACION` cuando $\text{TIR}_{AL30} - \text{TIR}_{GD29} \ge 130\text{ bps}$ ($Z \ge +1.1\sigma$).
  3. **Breakeven de Inflación (LECAPs vs. BONCER)**:
     * Comparación contra expectativa mensual de inflación (IPC/REM): `COMPRAR_CER` o `COMPRAR_TASA_FIJA`.
  4. **Cobertura con Bonos Duales (TAMAR vs. CER)**:
     * Detección de bonos duales subvaluados (paridad $\le 96\%$) con señal `COMPRAR_DUAL`.
* `ArbitrageEngine` (`backend/app/arbitrage/engine.py`): Concilia señales vivas, marca señales obsoletas como `EXPIRED`, persiste las activas en `arbitrage_signals` y genera el Command Center con semáforos bursátiles (Verde / Amarillo / Rojo).

### Fase 4: Dashboard Web, Simulador de Swaps & Resiliencia Offline
* **Dashboard SPA (`backend/app/static/index.html`)**:
  * Interfaz profesional bajo la skill `frontend-design` con estética oscura de terminal financiero (*Bloomberg / TradingView*), tipografía dual (*Plus Jakarta Sans* y *JetBrains Mono* con `tabular-nums`).
  * Pestañas: Monitor de Mercado con filtros y ordenamiento de columnas, Curvas de Rendimiento interactivas con Plotly y tooltips detallados, Arbitrage Command Center con semáforos, y Simulador de Swaps reactivo.
  * Modal interactivo para inspección del cronograma de flujos de fondos futuros (renta, amortización y flujo total).
  * Montado estáticamente en FastAPI (`/` y `/static`), requiriendo un único proceso para backend + frontend en el puerto `8050`.
* **Resiliencia Local y Zero-CDN Dependency**:
  * Para mitigar fallas de resolución DNS en ISPs locales (como caídas o bloqueos de `cdn.tailwindcss.com` que disparaban `ReferenceError: tailwind is not defined`), los assets esenciales (`tailwind.js` Play v3.4.17, `plotly.min.js` v2.35.2 y `lucide.min.js` v1.68.0) se alojan y sirven directamente desde `backend/app/static/vendor/`.
  * La configuración JavaScript y llamadas a librerías cuentan con comprobaciones condicionales (`if (typeof tailwind !== 'undefined')`, `renderIcons()`, `Plotly check`), y el bloque `<style>` incorpora variables CSS fallback para renderizado garantizado.
* **Simulador de Swaps (`backend/app/quant/swap_calculator.py`)**:
  * Endpoint `POST /api/v1/calculator/swap` y cálculo interactivo en vivo con nominales adquiridos, aranceles BYMA (0.04%), comisiones de broker (0.5%), ganancia/pérdida de TIR, efectivo resultante y breakeven temporal.
* **Suite de Pruebas**: 29 tests unitarios y de integración pasando al 100% (`backend/tests/`).

---

## 3. Decisiones Técnicas y Arquitectónicas Clave

1. **Stack Unificado Monolítico Liviano (FastAPI + SPA)**:
   * En lugar de obligar al usuario a correr dos procesos separados (Vite en un puerto y FastAPI en otro), FastAPI monta la SPA directamente en `/` y `/static`. Al ejecutar `python -m backend.main`, todo el sistema queda 100% operativo en una sola URL.
2. **Puerto por Defecto: `8050`**:
   * Se configuró el puerto `8050` (configurable mediante la variable de entorno `PORT`) para evitar colisiones con el puerto `8000`, frecuentemente utilizado por otros entornos de desarrollo.
3. **Consumo de APIs Internas de Bonistas.com**:
   * Se descubrió que Bonistas.com corre sobre Next.js y expone endpoints JSON (`/api/bonds`, `/api/fx/fx`, `/api/curves`). Se aprovechan estos endpoints directamente en lugar de recurrir a web scraping por HTML, otorgando velocidad y estabilidad ante cambios de diseño.
4. **Tratamiento de Claves Primarias en SQLite vs PostgreSQL**:
   * En SQLAlchemy con SQLite, las claves primarias autoincrementales deben ser declaradas como `Integer` (y no `BigInteger`) para que SQLite las enlace con el `ROWID` automático. Se corrigió esto en `models.py`.
5. **Cálculo de TIR Híbrido (Newton-Raphson + Brentq)**:
   * Newton-Raphson provee convergencia cuadrática instantánea ($< 5$ iteraciones) con su derivada analítica. Si el precio de mercado sufre una anomalía temporal o la tasa diverge, el fallback a `scipy.optimize.brentq` garantiza encontrar la raíz en el intervalo $[-0.80, 5.0]$ sin fallar.

---

## 4. Estructura de Archivos del Proyecto

```
bonistas/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py              # Endpoints REST (Health, Bonds, Quotes, Quant, Arbitrage, Swaps)
│   │   ├── arbitrage/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py              # Motor algorítmico y Command Center con semáforos
│   │   │   └── strategies.py          # Las 4 estrategias de arbitraje formalizadas
│   │   ├── data/
│   │   │   ├── __init__.py
│   │   │   ├── bond_catalog.py        # Maestro de bonos y letras argentinas
│   │   │   ├── bonistas_client.py     # Cliente HTTP hacia Bonistas.com
│   │   │   ├── dolar_api_client.py    # Cliente HTTP hacia DolarAPI
│   │   │   └── macro_connectors.py    # Cliente HTTP para IPC / CER / TAMAR
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── models.py              # Modelos SQLAlchemy (Bond, PriceSnapshot, ArbitrageSignal, MacroIndicator)
│   │   │   └── session.py             # Configuración de Engine y SessionLocal
│   │   ├── quant/
│   │   │   ├── __init__.py
│   │   │   ├── cashflows.py           # Vectores de flujos y cronogramas oficiales 2020
│   │   │   ├── fixed_income.py        # Valor Técnico, Paridad, TIR (Newton-Raphson/Brent), Duration, TEM, TNA
│   │   │   ├── arbitrage_math.py      # Ecuación Fisher (Breakeven), tipos de cambio implícitos, Z-score
│   │   │   └── swap_calculator.py     # Simulador de rotación de activos con comisiones BYMA y broker
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── bond.py                # Esquemas Pydantic para bonos
│   │   │   ├── snapshot.py            # Esquemas para snapshots y cotizaciones
│   │   │   ├── arbitrage.py           # Esquemas para señales de arbitraje
│   │   │   ├── macro.py               # Esquemas para tipos de cambio e IPC
│   │   │   └── valuation.py           # Esquemas para valuación cuantitativa y swaps
│   │   ├── static/
│   │   │   └── index.html             # Dashboard Web SPA interactivo (Plotly + TailwindCSS)
│   │   └── config.py                  # Variables de entorno y configuración general (Host, Puerto, URLs)
│   ├── tests/
│   │   ├── fixtures/                  # Muestras JSON de prueba offline
│   │   ├── test_api.py                # 11 tests de endpoints REST y servidor
│   │   ├── test_arbitrage.py          # 7 tests de las estrategias y motor de arbitraje
│   │   ├── test_ingestion.py          # 3 tests de la ingesta y persistencia
│   │   └── test_quant.py              # 8 tests de precisión financiera y resolución numérica
│   └── main.py                        # Punto de entrada FastAPI con lifespan y scheduler
├── .venv/                             # Entorno virtual Python 3.13
├── bonistas.db                        # Base de datos SQLite local pre-poblada con cotizaciones
├── especificacion-sistema-trading-bonos-argentinos.md # Documento de especificación de requerimientos v1.0
├── pytest.ini                         # Configuración de PyTest con pythonpath y asyncio
├── requirements.txt                   # Dependencias Python
├── README.md                          # Manual de usuario y ejecución
└── PROJECT_CONTEXT.md                 # Este documento de memoria técnica
```

---

## 5. Particularidades del Mercado Argentino Incorporadas

1. **Especies de Negociación**:
   * Cada título soberano cotiza simultáneamente en **Pesos** (ej. `AL30`), **Dólar MEP** (especie `AL30D`) y **Dólar Cable / CCL** (especie `AL30C`).
   * El sistema calcula y monitorea el arbitraje cambiario implícito y el spread de canje ($CCL / MEP - 1$).
2. **Ley Nueva York vs. Ley Local (*Law Premium*)**:
   * Los Bonares (AL) y Globales (GD) comparten el mismo cronograma de pagos, pero difieren en su jurisdicción legal. El spread de legislación fluctúa históricamente entre 2% y 15%. Cuando colapsa a $\le 1\%$, el sistema recomienda rotar a NY; cuando se ensancha a $\ge 12\%$, recomienda capturar la brecha rotando a AL.
3. **Amortizaciones Acumuladas en 2026**:
   * Títulos como AL30 y GD30 comenzaron a amortizar en julio de 2024. Hacia finales de 2026, el capital residual es de $64.00$ por cada 100 de valor nominal original. Todas las fórmulas de Valor Técnico y Paridad descuentan estrictamente las amortizaciones pasadas.
4. **Curvas de Tasa Fija vs. Curva CER**:
   * El sistema calcula en tiempo real la tasa mensual de equilibrio ($Breakeven_{\text{TEM}}$). Si la inflación esperada del REM/INDEC supera este breakeven, el algoritmo instruye comprar bonos ajustados por CER; de lo contrario, recomienda fijar tasa en LECAPs/BONCAPs.

---

## 6. Lo que Falta / Oportunidades para Próximas Versiones (v1.1+)

Si otro agente o desarrollador toma este proyecto, los siguientes puntos representan las extensiones naturales de mayor valor:

1. **WebSockets o Server-Sent Events (SSE)**:
   * En lugar del polling cada 15 segundos que realiza la SPA, implementar un canal WebSocket en FastAPI para emitir cotizaciones y señales con latencia cero a la UI.
2. **Alertas Externas Automatizadas (Telegram / Discord / WhatsApp)**:
   * Crear un conector de notificaciones para que cuando `ArbitrageEngine` emita una señal `ACTIVE` (ej. Rotar a NY por ratio $\le 1.01$), se despache una alerta push a un canal de traders.
3. **Ampliación a Obligaciones Negociables (ONs Corporativas)**:
   * Incorporar títulos corporativos hard dollar (YPF, Pampa Energía, Telecom, Vista) comparando sus curvas de rendimiento contra los soberanos para detectar arbitrajes de crédito privado.
4. **Calibración de Z-Scores con Series Históricas Extensas**:
   * Actualmente las medias y desvíos ($\mu, \sigma$) usan calibraciones estándar de mercado (5.5% para el law spread ratio, 180 bps para AL30 vs GD29). Conforme la base de datos acumule semanas de ruedas bursátiles en `price_snapshots`, se puede computar la media móvil rodante de 252 ruedas directamente desde SQL.
5. **Integración con APIs de Brokers Locales (Order Execution)**:
   * Conectar con APIs de brokers argentinos (ej. InvertirOnline, Balanz, PPI o interfaces FIX de BYMA) para permitir no solo la simulación del swap, sino la colocación con un solo clic de órdenes límite simultáneas para las dos patas del arbitraje.

### 6.1 Backlog acordado con el usuario para una versión futura (fuera del alcance de v1.1)

> Decisión del 2026-11-04: **la v1.1 se concentra exclusivamente en BONOS** (soberanos, subsoberanos, BCRA/BOPREAL, LECAP/BONCAP, CER, duales). Lo siguiente queda para después:

1. **Acciones Merval y Panel General**: arbitraje CI vs 24hs con las mismas reglas de puntas, costo (0,11% por operación) y ganancia neta mínima.
2. **CEDEARs**: arbitraje CI vs 24hs y, eventualmente, CCL implícito CEDEAR vs subyacente.
3. **Obligaciones Negociables (ONs)**: curvas corporativas vs soberanos (ver punto 3 de arriba).
4. **"Gangas"**: detector de caídas > 5% con volumen mínimo (> 4 operaciones), tal como hacía `temporal/MonitorMercado.ps1` (`Show-Gangas`).
5. Notificaciones por canales externos (Telegram, etc.): en v1.1 los avisos son solo **notificación de Windows + dashboard**.

El endpoint de Bull Market (`/Clients/MarketPrices/GetStockPrices`) ya soporta `index=merval`, `panel+general` y `cedears`, así que el conector de v1.1 debería quedar parametrizable por índice para reutilizarlo.

---

## 7. Instrucciones Operativas

### Ejecución del Servidor
```powershell
.\.venv\Scripts\python.exe -m backend.main
```
* **Dashboard**: `http://localhost:8050`
* **Swagger Docs**: `http://localhost:8050/docs`

### Ejecución de Pruebas
```powershell
.\.venv\Scripts\pytest.exe backend/tests/ -q
```
* Los tests usan una SQLite temporal (nunca `bonistas.db`) y datos de `backend/tests/fixtures/` (sin internet).
* Los tests marcados `@pytest.mark.network` consultan APIs reales: `$env:RUN_NETWORK_TESTS="1"` para incluirlos.

### Configuración vía Variables de Entorno (o archivo `.env`, no versionado)
* `PORT`: Puerto HTTP (por defecto `8050`).
* `HOST`: Dirección de escucha (por defecto `127.0.0.1`, solo esta PC; `0.0.0.0` para exponerlo en la red local).
* `RELOAD`: recarga automática de código para desarrollo (por defecto `false`).
* `DATABASE_URL`: Cadena de conexión SQLAlchemy (por defecto `sqlite:///./bonistas.db`, modo WAL).
* `POLLING_INTERVAL_SECONDS`: Intervalo de sincronización en segundos (por defecto `60`).
* `DISABLE_SCHEDULER` / `SKIP_STARTUP_INGESTION`: desactivan la ingesta automática (tests / desarrollo offline).
* `MARKET_HOURS_ONLY` (`true`): consultar cotizaciones solo en días hábiles y en horario de rueda (según BYMA), hasta 25 min después del cierre.
* `REFERENCE_REFRESH_HOUR` / `REFERENCE_REFRESH_MINUTE` (`10:15` ART): actualización diaria de CompararBonos + BCRA (L-V; también al iniciar si los datos no son del día).
* `COMMISSION_PCT` (`0.11`), `MIN_NET_PROFIT_PCT` (`0.40`), `TRADE_SIZE_USD` (`500`): parámetros operativos por defecto.
* `BULLMARKET_ENABLED` (`true`): usar Bull Market en tiempo real si hay sesión.
* `BULLMARKET_COOKIE_FILE` (`secrets/bullmarket_cookie.txt`): dónde se guarda la cookie que se pega en el dashboard (carpeta ignorada por git).
* `BULLMARKET_COOKIE`: alternativa en el `.env` (se usa si el archivo no existe). **Nunca** en el código.
* `BULLMARKET_MAX_AGE_SECONDS` (`180`): antigüedad máxima de la última consulta OK de Bull Market para usar sus puntas; si no, se vuelve a BYMA.
* `WINDOWS_NOTIFICATIONS` (`true`): notificaciones de escritorio de Windows (el panel de alertas funciona siempre; las preferencias finas se editan en el dashboard).

---

## 8. Registro de cambios v1.1

### Etapa 1 — Correcciones (2026-11-04)
* **Tickers**: `base_ticker()` quita solo el sufijo final D/C de bonos conocidos. Antes `"GD30".replace("D","")` daba `"G30"` y ningún Global encontraba su cronograma (se valuaban como bullet).
* **Cronogramas AL/GD 2020** reescritos y verificados contra los flujos de CompararBonos (residual y tasa implícita de cada pago coinciden): step-ups de AL30 (1,75% recién desde ene-28), AL35 (4,125 → 4,75 → 5%), AE38 (5%), AL41 (3,5% hasta jul-29), GD46 (44 cuotas desde ene-25).
* **Intereses corridos** de Bonares/Globales en **30/360** (VT AL30 05-nov-2026 = 64,1547, igual que el mercado). Genéricos: Actual/365 desde el último cupón real (antes, 30 días fijos).
* **Modified Duration** = Macaulay / (1 + TIR), consistente con la TIR efectiva anual. Nota: Bonistas informa Macaulay / (1 + TIR/2); es una diferencia de convención (~6%).
* **Valuación propia** solo para bonos con cronograma verificado; LECAP/CER/duales/etc. devuelven 422 en vez de números incorrectos (se incorporarán con CompararBonos en la etapa 2).
* **Simulador de swaps**: sin precios inventados (404 si falta cotización), ambas patas en la misma moneda (MEP o pesos, 422 si no hay común), costo por defecto 0,11% todo incluido.
* **Ratios AL/GD**: solo especie D contra especie D y mismo plazo; nunca se cae a `last_price` (que puede estar en pesos).
* **CI vs 24hs**: las cotizaciones se consultan por plazo (`?settlement=CI|24HS`), nunca mezcladas.
* **Ingesta**: descarta filas sin precio (antes se guardaban en 0), catálogo en memoria (sin N+1), fuentes secundarias tolerantes a fallas.
* **Macro**: no se persisten valores inventados (CER/TAMAR/A3500 fijos, IPC de respaldo); el IPC se guarda con su fecha real.
* **Estrategia Relative Value**: dispara solo con Z ≥ +1,1σ (antes el umbral de 130 bps estaba por debajo de la media y quedaba siempre activa).
* **Infra**: SQLite en WAL, scheduler con `max_instances=1`, CORS restringido, `HOST` por defecto local, polling 60 s.
* **Tests**: aislados de la base real y de internet; 83 tests (antes 29), ~5 s (antes ~60 s).
* **Limpieza de datos** en `bonistas.db` (respaldo en `bonistas.backup-2026-11-04.db`): 13.248 snapshots con precio 0 y 4 indicadores macro ficticios eliminados.

### Etapa 2 — Nuevas fuentes de datos (2026-11-04)

| Fuente | Módulo | Qué aporta | Frecuencia |
|---|---|---|---|
| BYMA Open Data (`/public-bonds`, POST, sin token) | `data/byma_client.py` | Mejor punta compradora/vendedora con cantidades, último, volumen y hora; CI (`settlementType=1`) y 24hs (`2`); especies ARS / MEP (`USD`) / CCL (`EXT`). **20 min de demora.** | 60 s en horario |
| BYMA cauciones | `data/byma_client.py` | Caución en pesos al plazo más corto → `macro_indicators.CAUCION_1D_TNA` (% TNA) | 60 s en horario |
| BYMA `market-time` | `services/market_calendar.py` | Día hábil y horario de rueda (no hace falta calendario de feriados propio) | 1 vez por día |
| CompararBonos (`/api/bonos`) | `data/comparar_bonos_client.py` | Flujos por 100 VN (CER ya ajustados), VT, pago final LECAP/BONCAP, especies → tabla `reference_bonds` | Diaria |
| API BCRA v4.0 | `data/bcra_client.py` | CER (id 30, el de hoy, no los publicados a futuro), TAMAR (44, TNA), A3500 (5) | Diaria |

* Nuevas tablas: `book_quotes` (puntas por fuente/especie/plazo, **solo se agrega una fila cuando algo cambia**) y `reference_bonds`.
* Los snapshots de Bonistas también se guardan solo cuando cambian.
* Valuación (`/calculator/valuation`) y flujos (`/bonds/{t}/cashflows`): cronograma propio verificado (AL/GD) o, si no hay, flujos de referencia de CompararBonos (LECAP, BONCAP, CER con TIR real, BOPREAL, tasa fija). Duales y dollar linked: 422 (no publican flujos proyectables). Plazo `CI`/`24HS` para la fecha de liquidación por defecto.
* Endpoints nuevos: `GET /books`, `GET /status` (horario + salud de fuentes), `GET /reference/{ticker}`, `POST /reference/refresh`. `POST /ingest` ahora incluye BYMA.
* **Bug corregido**: Bonistas publica variantes `_PUT` / `_TAM` (mismo instrumento, TIR bajo otro escenario); se fusionaban con el bono base y la TIR alternaba entre escenarios en cada ciclo (ej. BPOA8 9,3% ↔ 27,4%). Ahora se usa solo el escenario base.
* Dashboard: indicador real de estado de mercado y salud de fuentes (antes decía "Rueda en Vivo" siempre); el encabezado muestra el mayorista A3500 (antes mostraba el oficial minorista con la etiqueta "mayorista").
* Verificado con datos reales: TIR de S30N6 25,97%, T30A7 29,31%, TZX27 3,69% real, BPA7D 2,22% (iguales a las de referencia de mercado).

### Etapa 3 — Detectores sobre puntas (2026-11-04)

Parámetros (editables en el Command Center, tabla `user_settings`): costo por operación **0,11%**, ganancia neta mínima **0,40%**, tamaño **USD 500** (en especies en pesos se convierte con el MEP implícito del AL30).

| Detector | Módulo | Regla |
|---|---|---|
| **CI vs 24hs** (misma especie) | `arbitrage/ci_24hs.py` | A) vender CI a la compradora / comprar 24hs a la vendedora: `bruto = (bid_CI − F)/ask_24 − 1`. B) comprar CI / vender 24hs: `bruto = (bid_24 + F)/ask_CI − 1`, menos caución por los días entre liquidaciones. Neto = bruto − 2 × costo. |
| **Dólar implícito** | `arbitrage/fx_implied.py` | MEP/CCL ejecutable por bono (comprar y vender dólares, costos incluidos), todas las combinaciones de plazo; ida y vuelta entre bonos en el mismo plazo. |
| **Ratios** | `arbitrage/ratios.py` | AL/GD y pares de curva del monitor del trader (AE38/GD35, AE38/GD41, GD38/GD41, GD35/GD38), especie D, con puntas; z-score con serie diaria real. |

Reglas de seguridad (para evitar falsas alarmas):
* **Corte de cupón**: `F` = flujos con `hoy < fecha ≤ liquidación 24hs` (cronograma propio AL/GD o flujos de CompararBonos; para especies en pesos de bonos USD se convierte con el TC implícito). Sin cronograma conocido (`DESCONOCIDO`) **no se emite señal**.
* **Profundidad**: si la punta no cubre el tamaño configurado, no hay señal (se muestra igual en la tabla).
* **Z-scores**: las reglas puramente estadísticas (valor relativo AL30/GD29, rotar a ARG por z ≥ 1,5, semáforo amarillo) solo actúan con **≥ 20 ruedas de historia real**. Con calibración estática el z se muestra como dato informativo. Las reglas absolutas (ratio AL/GD ≤ 1,01 o ≥ 1,12) siguen activas.
* **Duales**: sin señal (paridad < 96% no es evidencia de subvaluación).
* **Breakeven**: par tasa fija / CER con la duration más parecida (antes, el primero de una lista fija).

Señales persistentes: clave `estrategia|venta|compra|acción`; mientras siga vigente es la misma fila (`first_seen`, `last_seen`, `net_profit_pct`, `confirmation` = `DEMORA_20MIN` con BYMA). Las señales v1.0 sin clave se expiran al primer ciclo. `db/migrations.py` agrega columnas nuevas a bases existentes sin tocar datos.

Endpoints: `GET /arbitrage/ci-24hs`, `GET /arbitrage/fx-implied?kind=MEP|CCL`, `GET /arbitrage/ratios`, `GET|PUT /settings/trading`. Dashboard: pestañas "CI vs 24hs" y "Dólar implícito", panel de parámetros, ratios de curva y tarjetas con ganancia neta / origen del dato / "activa desde".

### Etapa 4 — Bull Market en tiempo real (2026-11-05)

* `data/bullmarket_client.py`: `GET /Clients/MarketPrices/GetStockPrices?term=1|2&index=bonos` con la cookie de sesión del trader (5 niveles de puntas; `index` parametrizado para acciones/CEDEARs en el futuro). Sin login automático.
* Sesión vencida: HTTP 401/403, redirección 3xx (verificado: Bull Market responde **302** con una cookie inválida) o página HTML ⇒ `VENCIDA`; se deja de consultar hasta que se pegue una cookie nueva. Errores de red/5xx ⇒ `ERROR`, se reintenta.
* `services/bullmarket_session.py`: normaliza lo pegado (valor del encabezado `cookie`, con o sin prefijo, o "Copiar como cURL"), lo guarda en `secrets/` y **nunca** lo devuelve por la API ni lo registra en logs.
* Libros: `book_quotes.depth` (JSON con los 5 niveles; migración automática). `walk_book` recorre toda la profundidad para el tamaño configurado.
* Prioridad de fuentes: Bull Market > BYMA por especie/plazo, solo si la última consulta OK de Bull Market tiene < `BULLMARKET_MAX_AGE_SECONDS` y la especie vino en esa respuesta.
* Confirmación de señales según las patas: `TIEMPO_REAL` (todas Bull Market), `PARCIAL` (mezcla), `DEMORA_20MIN` (todas BYMA).
* Bull Market se consulta solo durante la rueda (5 min antes de la apertura hasta 2 min después del cierre); BYMA sigue con su ventana extendida por la demora.
* Endpoints: `GET|PUT|DELETE /bullmarket/session`; `/status` incluye `bullmarket`; `/books?source=BULLMARKET` devuelve `depth`; Command Center informa `book_sources`.
* Dashboard: panel "Bull Market · tiempo real" (pegar cookie, estado, instrucciones), estado en el encabezado y etiqueta "Parcial" en las señales.
* Tests: `test_stage4_bullmarket.py` (fixture recortado de una respuesta real, solo datos de mercado; nunca se usa la cookie real).

### Etapa 5 — Alertas y notificaciones (2026-11-05)

* `services/notifier.py`: toast nativo de Windows vía PowerShell (sin dependencias). Script fijo (`-EncodedCommand`); título/mensaje/URL por variables de entorno y escapados para XML ⇒ el texto de una alerta nunca se ejecuta. Clic en el aviso ⇒ abre el dashboard.
* `services/alert_service.py` + tabla `alerts` (historial del panel):
  * `OPORTUNIDAD`: señal nueva (solo cuando aparece). `CONFIRMADA`: una señal detectada con demora pasa a `TIEMPO_REAL` con Bull Market.
  * `SESION_VENCIDA` (una vez por vencimiento), `FUENTE_CAIDA` (BYMA / Bonistas / Bull Market con 3 fallas seguidas) y `FUENTE_OK`.
  * Anti-ruido: una señal que desaparece y reaparece no se vuelve a avisar por 15 min.
  * Preferencias (`user_settings.notifications`): notificaciones de Windows sí/no, solo confirmadas en tiempo real, avisos de fuentes.
* El motor expone `listeners` (se llaman tras cada evaluación, también en `/ingest` y `/arbitrage/evaluate`); un error en una alerta nunca corta la evaluación.
* Endpoints: `GET /alerts` (`unread_only`, `after_id`), `POST /alerts/read`, `POST /alerts/test`, `GET|PUT /settings/notifications`.
* Dashboard: campana con contador de no leídas, panel con historial y preferencias, avisos dentro de la página para alertas nuevas (consulta cada 20 s).
* Corrección: SQLite devolvía fechas sin zona horaria y el navegador las mostraba corridas 3 h ("activa desde", alertas). `db/types.py::UTCDateTime` devuelve siempre UTC con zona.
* Tests: `test_stage5_alerts.py`. Los tests nunca muestran notificaciones reales (`WINDOWS_NOTIFICATIONS=false` + `send` anulado en conftest).

### Curvas de rendimiento por familia (2026-11-05)

* `services/curves_service.py` + `GET /curves`: reemplaza el gráfico único (mezclaba 341 especies: ONs, provinciales y las tres especies de cada bono).
* Clasificación de CompararBonos (`tipo`): Soberanos USD (Bonares / Globales / BOPREAL), Tasa fija (LECAP/BONCAP/FIJA: TEM vs días), CER (solo TIR real), Provinciales USD, Dollar linked, TAMAR y duales, y Argentina vs región (soberanos LatAm + Treasuries). Las ONs no entran.
* Un punto por bono: TIR/MD de Bonistas de la especie preferida (D para USD); si no hay, CompararBonos; si tampoco, **TIR propia** con flujos de CompararBonos + precio medio de BYMA 24hs (precio sucio, liquidación T+1).
* Curva ajustada `y = a + b·ln(x) (+ c·ln(x)²` con ≥ 5 puntos, para captar la joroba soberana). Desvío = observado − ajustado en pb (positivo = relativamente barato).
* Región: spread vs Treasuries interpolado a la misma duration (riesgo país por tramo: Globales ~600–830 pb el 04/11).
* Exclusiones informadas: < 20 días al vencimiento, TIR fuera de [−30%, 80%], sin TIR ni flujos (hoy la mayoría de los provinciales: CompararBonos no publica sus flujos).
* Dashboard: selector por familia, etiquetas opcionales, tooltip completo, tabla de desvíos y lista de excluidos.

### Guía de uso en el dashboard (2026-11-05)

* Clic en el logo (badge "?") ⇒ modal con 6 secciones navegables: para qué sirve (con los parámetros actuales del usuario), primeros pasos, herramientas (con botón "Abrir →" a cada pestaña), cómo leer una señal, glosario y fuentes/límites (incluye el aviso de que no es asesoramiento financiero).
* Se abre sola en la primera visita (`localStorage.guideSeen`); se cierra con Esc, clic afuera o la X.

### Provinciales: cronogramas de Bruno618 (2026-11-05)

* `data/bruno618_client.py`: lee una vez por día (con la referencia de las 10:15) las fichas `bruno618.com/herramientas/flujo-de-fondos-renta-fija/<ticker>` de 18 provinciales (HTML renderizado en el servidor; robots.txt lo permite). Pausa de 0,7 s entre pedidos.
* Validaciones por bono: total = renta + amortización, residual encadenado, residual final 0, moneda explícita. Si falla, el bono se descarta con el motivo (no se usan datos dudosos).
* `ReferenceDataService.merge_provincial_schedules`: CompararBonos manda; Bruno618 solo completa los que no tienen flujos (10) o agrega los que faltan (6). Solo bonos en dólares. Nuevas columnas `reference_bonds.flows_source` y `flows_detail` (renta/amort/residual; la ficha de pagos los muestra).
* Control cruzado pago por pago donde hay dos fuentes: BB37D coincide (máx. 0,005 por 100 VN); **BA37D difiere 21 días en todas las fechas** (1/3 vs 22/3) con montos iguales: se mantiene CompararBonos y se registra el desvío.
* Resguardo: como las fechas de Bruno618 no están verificadas, en bonos con esa fuente el estado de cupón es DESCONOCIDO (sin señal CI vs 24hs) si hay un pago a ±30 días.
* Curvas: TIR propia con precio de la especie en dólares (MEP, luego cable) o, si solo cotiza en pesos, precio ARS ÷ MEP implícito del AL30. Validado contra CompararBonos: BA37D 14,56% vs 14,84%, BB37D 14,94% vs 15,04%.
* Corrección: la duration de CompararBonos es de **Macaulay**; ahora se convierte a modificada (afectaba Argentina vs región y bonos sin dato de Bonistas).
* Curva provincial: 2 → 13 bonos. Provincia de Buenos Aires (BA37D/BB37D/BC37D) en serie aparte, fuera del ajuste (otro escalón de riesgo).
* Sin precio en BYMA (excluidos con motivo): BP28, BPLD, BPLE, CO27D (en BYMA figura como CO2D7, en pesos), PUL26.

### Provinciales: consenso de tres fuentes y TIR en MEP / cable (2026-11-05)

* `data/mercados_argentina_client.py`: fichas `mercadosargentina.com.ar/activos/<ticker>` (robots.txt las permite; el sitio limita pedidos por IP: 1 s entre pedidos y corte ante HTTP 429). Lee la tabla "Cronograma de Pagos" (incluye pagos pasados: se conservan los futuros), valida total = renta + amortización, amortizaciones ≤ 100 y moneda de pago. Alias de tickers (SJO35 ↔ `sj035`) y especies BYMA de bonos nuevos (SJO35 → SJO5D/SJO5C).
* Consenso (`merge_provincial_schedules`): se agrupan las fuentes que coinciden (mismos pagos, fechas a ≤ 3 días, montos a ≤ 0,05 por 100 VN). Si dos o más coinciden, los flujos quedan **verificados** (`reference_bonds.flows_verified`; detalle en `flows_check`). Si no, gana la mayoría; con empate, CompararBonos > Mercados Argentina > Bruno618.
* Resultado real (05/11/2026): 12 verificados (BA37D, BB37D, BDC33, BDC36, CO32, CO35, ERF25, ERM33, NDT25, PMM29, PUA36, SFD34). Desacuerdos: BA37D (Bruno618 con fechas 21 días corridas, descartado por mayoría), BC37D (cupón 5,25% en Mercados Argentina vs 5% en Bruno618) y PUL26 (diferencias de hasta 0,09): sin verificar. SJO35 se agrega desde Mercados Argentina (sin verificar). NDG34 sigue sin cronograma en ninguna fuente.
* El resguardo de cupón (sin señal CI vs 24hs a ±30 días de un pago) aplica solo a flujos de fuente secundaria **no verificados**. En CI vs 24hs, las especies con cupón "¿?" bajaron de 94 a 75.
* Curvas `?dolar=MEP|CCL` y selector en el dashboard: con cable se usan especies C (derivadas de la D si hace falta) o precio en pesos ÷ CCL implícito del AL30. Para bonos en dólares, en modo cable se prioriza la TIR propia sobre la de CompararBonos (no informa en qué dólar está medida). Ejemplo: CO32 9,46% (MEP) vs 11,04% (cable; Mercados Argentina publica 10,78%).
* Dashboard: se corrigió una carrera al cambiar de curva mientras se recargaban los datos.

### Corrección del corte de cupón con datos reales de Bull Market (2026-11-05)

* Primer uso con Bull Market en vivo: señal falsa CI vs 24hs de **TX28 con +22,2% neto**. Causa: TX28 paga el lunes 9/11 y la liquidación 24hs del viernes 6/11 ya cotizaba ex-cupón (~$1.450) mientras CI (jueves 5/11) lo incluía (~$1.820).
* Regla corregida (`market_calendar.ex_date`): el corte es el **día hábil anterior a la fecha efectiva de pago**. Un flujo afecta CI vs 24hs si `hoy < ex_date(F) <= liquidación 24hs`.
* Resguardo por precio (`ci_24hs.py`): CompararBonos ya no lista un pago cortado para su propia liquidación, así que puede faltar en los flujos. Si la brecha bruta CI/24hs es ≥ 3% y ya existía al cierre anterior (≥ 50%), o si es ≥ 10%, el estado pasa a `CORTE_PROBABLE` y no hay señal (dashboard: "⚠ corte").
* Verificación de la conexión: 427 libros de Bull Market (156 con 5 niveles), mismas unidades que BYMA y mismo bono base en las 246 especies comparables. Con la demora de 20 min, BYMA mostraba puntas de pre-apertura (AL30D compradora 47,99 vs 52,40 en Bull Market).

### Feriados de mercado (MAE) en el calendario (2026-11-05)

* `data/mae_client.py`: `api.marketdata.mae.com.ar/api/mercado/feriados` (próximos feriados con país `ar`/`us` y fecha sin año: el año se infiere como la próxima ocurrencia).
* Tabla `market_holidays` (se conservan los pasados) y `services/holiday_service.py`: se descarga al iniciar si no es del día y en la actualización diaria de referencia; si MAE falla, se siguen usando los guardados.
* `market_calendar`: `is_business_day`, `next_business_day`, `previous_business_day` y `ex_date` saltean feriados de Argentina. Afecta liquidación 24hs, días de caución en CI vs 24hs y corte de cupón (pago en feriado ⇒ se paga el día hábil siguiente; corte = día hábil anterior).
* Feriados de EE.UU.: informativos (poco volumen en activos ligados al exterior; más relevante para CEDEARs).
* Ejemplo real: lunes 9/11/2026 feriado ⇒ el viernes 6/11, 24hs liquida el martes 10/11 (4 días de caución). Los "días no laborables con fin turístico" (ej. 7/12) se tratan como sin liquidación.
* `/status` informa `settlement_24hs` y los próximos feriados; el indicador del encabezado avisa un feriado dentro de 7 días y el tooltip los lista.

### Cronogramas de pago desde Bull Market (2026-11-05)

* `bullmarket_client.fetch_cashflows`: `POST /Clients/FixedIncome/GetProductsCashflowTablesAndSum` con `{"symbolQuantityList":[{"symbol":..,"quantity":100}]}` (montos por 100 VN; pedidos de a 40 bonos). Trae fecha, renta, amortización, total, residual, `isPastPayment`, `paymentsCurrency` (ARS/MEP/CCL) y ley. En CER, montos estimados con el CER vigente. Usa la sesión del panel; sesión vencida ⇒ mismo manejo que las cotizaciones.
* Una vez por día, la primera vez que la sesión está ACTIVA (ciclo de mercado, al guardar la cookie o manual): `ReferenceDataService.apply_bullmarket_cashflows`.
  * Bull Market entra al consenso de provinciales (ranking: CompararBonos 4 > Bull Market 3 > Mercados Argentina 2 > Bruno618 1).
  * `add_imminent_flows`: agrega a cualquier bono de la referencia los pagos con corte en los próximos 15 días que la fuente principal ya no lista (caso TX28). Se registra en `flows_check.pagos_proximos_bullmarket`.
* Resultado real: 79 cronogramas; 14 provinciales verificados (se suman BC37D, desempate MA + Bull Market contra Bruno618, y SJO35); NDG34 agregado (solo Bull Market, sin verificar); pagos próximos agregados: TX28 (9/11) y BAF27 (13/11). BDC33: Bull Market redondea amortizaciones 33/33/34 vs 33,33/33,33/33,34 (gana la mayoría; fechas iguales).
* La sesión se mantuvo activa más de 30 minutos con el polling de 60 s.

