# 🧠 Contexto Técnico y Memoria de Proyecto: Monitor de Arbitraje de Bonos Argentinos

> **Documento de memoria y contexto para agentes de IA y desarrolladores.**
> Resume el propósito, el estado actual (v1.1), las decisiones de diseño financieras y técnicas, las particularidades del mercado argentino y la hoja de ruta. El detalle cronológico de cada cambio está en la §8.
> Última actualización: 2026-11-05.

---

## 1. Visión general

### 1.1 Objetivo
Herramienta **personal** (corre en la PC del trader) para detectar **desarbitrajes ejecutables en bonos argentinos** y avisar a tiempo:
1. **CI vs 24hs** de la misma especie, descontando costos, caución y **corte de cupón**.
2. **Dólar implícito** (MEP / CCL) ejecutable por bono e **idas y vueltas** pesos ↔ dólares entre bonos.
3. **Ratios** AL/GD (ley local vs NY) y entre bonos de la curva.
4. **Valor relativo** sobre curvas por familia (desvío de cada bono contra su curva ajustada).

Avisa por **notificación de Windows** y en el **dashboard**. **No ejecuta órdenes** ni es asesoramiento financiero.

### 1.2 Perfil y parámetros del usuario
* Broker: **Bull Market**. Costo **0,11% por operación, todo incluido** (0,22% ida y vuelta).
* Ganancia neta mínima **0,40%** y tamaño **USD 500** (editables en el dashboard, tabla `user_settings`).
* Polling cada **60 s**, solo en horario de rueda.
* Alcance v1.1: **solo bonos** (soberanos, subsoberanos, BOPREAL, LECAP/BONCAP, CER, DL, TAMAR, duales). Acciones, CEDEARs, ONs y "gangas" quedan para después (§6.1).

---

## 2. Estado actual (v1.1)

### 2.1 Fuentes de datos
| Fuente | Módulo | Uso | Frecuencia / demora |
|---|---|---|---|
| BYMA Open Data | `data/byma_client.py` | Puntas CI/24hs (mejor punta y cantidad), cauciones, horario de mercado | Cada 60 s, 20 min de demora |
| Bull Market (sesión del usuario) | `data/bullmarket_client.py` | Puntas con **5 niveles** en tiempo real; **cronogramas de pago** de muchos bonos por pedido | Puntas cada 60 s en rueda; cronogramas 1 vez por día |
| Bonistas.com | `data/bonistas_client.py` | TIR, MD, paridad, valor técnico por especie | Cada 60 s |
| CompararBonos | `data/comparar_bonos_client.py` | Flujos, especies y clasificación (`tipo`) de cada bono, soberanos de la región y UST | Diario 10:15 ART |
| Bruno618 | `data/bruno618_client.py` | Cronogramas de 18 provinciales en USD | Diario |
| Mercados Argentina | `data/mercados_argentina_client.py` | Cronogramas de 16 provinciales (incl. SJO35) | Diario, 1 s entre pedidos |
| BCRA | `data/bcra_client.py` | CER (var. 30), TAMAR (44), A3500 (5) | Diario |
| MAE | `data/mae_client.py` | Próximos feriados (Argentina y EE.UU.) | Diario y al iniciar |
| DolarAPI / ArgentinaDatos | `data/dolar_api_client.py`, `macro_connectors.py` | MEP/CCL de referencia, IPC | Cada 60 s / diario |

Descartadas: Rava, PuenteNet, Screenermatic, Docta, AnálisisTécnico (token, login, 403 o captcha) y Nix Valores (API privada de broker, sin `robots.txt`, certificado TLS incompleto).

### 2.2 Detectores y señales (`backend/app/arbitrage/`)
* `market_view.py`: libros por especie/plazo con **prioridad Bull Market > BYMA** (solo si la última consulta OK de Bull Market tiene < 180 s y la especie vino en esa respuesta), referencia MEP (implícito AL30), caución 1 día y flujos por bono. `flow_between` suma los pagos que **cortan** entre las dos liquidaciones.
* `ci_24hs.py`: CI vs 24hs en las dos direcciones, recorriendo la profundidad del libro para el tamaño configurado. Resguardos: sin cronograma ⇒ sin señal; brecha ≥ 3% que ya existía al cierre anterior, o ≥ 10% ⇒ `CORTE_PROBABLE`, sin señal.
* `fx_implied.py`: TC de compra/venta de dólares por bono y mejor ida y vuelta (4 patas en el mismo plazo).
* `ratios.py`: AL/GD y pares de curva con puntas; z-score solo con ≥ 20 ruedas de historia real.
* `engine.py`: concilia señales persistentes (clave `estrategia|venta|compra|acción`), confirmación por fuente de las patas (`TIEMPO_REAL` / `PARCIAL` / `DEMORA_20MIN`), Command Center y listeners de alertas.
* `strategies.py`: prima de legislación (fallback Bonistas), valor relativo AL30/GD29 y breakeven tasa fija vs CER.

### 2.3 Referencia, cronogramas y calendario (`backend/app/services/`)
* `reference_data_service.py`: CompararBonos + BCRA + IPC; **consenso de cronogramas de provinciales** entre CompararBonos, Bull Market, Mercados Argentina y Bruno618 (verificado si ≥ 2 fuentes coinciden en fechas ±3 días y montos ±0,05; si no, mayoría; con empate, ranking CompararBonos > Bull Market > Mercados Argentina > Bruno618). Agrega **pagos próximos** (corte en ≤ 15 días) que la referencia no lista, desde Bull Market.
* `holiday_service.py` + `market_calendar.py`: feriados de Argentina en `next_business_day`, `previous_business_day` y `ex_date`.
* `curves_service.py`: curvas por familia con ajuste en ln(duration), desvío en pb, TIR propia (flujos + precio BYMA) y TIR en **MEP o cable**.
* `market_book_service.py` + `bullmarket_session.py`: ingesta de libros (solo guarda cambios) y sesión de Bull Market (cookie en `secrets/`, nunca expuesta).
* `alert_service.py` + `notifier.py`: alertas (oportunidad nueva, confirmada en tiempo real, sesión vencida, fuente caída/recuperada) y toast nativo de Windows vía PowerShell.

### 2.4 Dashboard (`backend/app/static/index.html`)
Pestañas: Monitor de cotizaciones, Curvas de rendimiento (por familia, MEP/cable, desvíos), Command Center (parámetros, Bull Market, señales, ratios), CI vs 24hs, Dólar implícito y Simulador de swaps. Campana de alertas con preferencias, indicador de mercado/fuentes/feriados y **guía de uso** (clic en el logo; se abre sola la primera vez). Assets locales en `static/vendor/` (sin CDN).

### 2.5 Calidad
* 250 tests (`backend/tests/`), offline: base temporal, fixtures recortados de respuestas reales, nunca la cookie real ni notificaciones reales.
* SQLite en WAL; migraciones mínimas (`db/migrations.py` agrega columnas faltantes); fechas siempre en UTC con zona (`db/types.py`).

---

## 3. Decisiones técnicas y financieras clave

1. **Monolito liviano**: FastAPI sirve la SPA en `/`; un solo proceso (`python -m backend.main`) en `127.0.0.1:8050`.
2. **Precios ejecutables, no teóricos**: los arbitrajes se calculan con puntas y profundidad, no con último precio. Bonistas no tiene puntas: sirve solo para analítica.
3. **Corte de cupón**: un pago con fecha F lo cobra quien liquida **antes** de `ex_date(F)` = día hábil anterior a la fecha efectiva de pago (si F cae en fin de semana o feriado, se paga el día hábil siguiente). Verificado con TX28 el 05/11/2026.
4. **Las fuentes pueden omitir un pago inminente** (CompararBonos excluye el pago ya cortado para su propia liquidación). Por eso: pagos próximos desde Bull Market + resguardo por brecha estructural.
5. **Datos de una sola fuente secundaria no verificada** ⇒ sin señal CI vs 24hs a ±30 días de un pago.
6. **Z-scores** solo con historia propia (≥ 20 ruedas); con calibración estática son informativos.
7. **TIR**: tasa efectiva anual, `MD = Macaulay / (1 + TIR)`. CompararBonos publica Macaulay: se convierte. Bonares/Globales 2020 con cronograma propio verificado y devengamiento 30/360.
8. **MEP vs cable**: bonos que pagan en cable rinden distinto medidos en MEP o en CCL (la diferencia es el canje); las curvas permiten elegir.
9. **Seguridad**: la cookie de Bull Market se pega solo en el dashboard y se guarda en `secrets/` (gitignored); no hay login automático; `temporal/`, `.env`, `secrets/` y `*.db` fuera de git. El texto de las notificaciones viaja por variables de entorno (nunca en el comando).
10. **Uso respetuoso de fuentes**: User-Agent identificable, una consulta por minuto en rueda, cronogramas una vez por día con pausas, corte ante HTTP 429.

---

## 4. Estructura de archivos

```
bonistas/
├── backend/
│   ├── main.py                          # FastAPI + APScheduler: ciclo de mercado (60 s), referencia diaria, arranque
│   ├── app/
│   │   ├── config.py                    # Settings (variables de entorno / .env)
│   │   ├── api/routes.py                # Endpoints REST e instancias compartidas de servicios
│   │   ├── arbitrage/                   # market_view, ci_24hs, fx_implied, ratios, engine, strategies
│   │   ├── data/                        # Clientes: byma, bullmarket, bonistas, comparar_bonos, bruno618,
│   │   │                                #   mercados_argentina, bcra, mae, dolar_api, macro_connectors, bond_catalog
│   │   ├── db/                          # models, session (WAL), migrations, types (UTCDateTime)
│   │   ├── quant/                       # cashflows (AL/GD 2020), fixed_income, arbitrage_math, swap_calculator
│   │   ├── schemas/                     # Pydantic
│   │   ├── services/                    # ingestion, market_book, reference_data, curves, market_calendar,
│   │   │                                #   holiday, bullmarket_session, alert, notifier, source_health, trading_settings
│   │   └── static/                      # index.html (dashboard) + vendor/ (tailwind, plotly, lucide)
│   └── tests/                           # 250 tests + fixtures/ (respuestas reales recortadas)
├── docs/screenshots/                    # Capturas del README
├── secrets/                             # Cookie de Bull Market (gitignored, se crea al pegarla)
├── temporal/                            # Scripts personales del usuario (gitignored: contiene cookies)
├── bonistas.db                          # Base local (gitignored)
├── especificacion-sistema-trading-bonos-argentinos.md
├── pytest.ini · requirements.txt · README.md · PROJECT_CONTEXT.md
```

Tablas: `bonds`, `price_snapshots` (Bonistas, solo cambios), `book_quotes` (BYMA/Bull Market, con `depth`), `reference_bonds` (flujos, `flows_source`, `flows_verified`, `flows_check`, `flows_detail`), `macro_indicators`, `arbitrage_signals`, `alerts`, `market_holidays`, `user_settings`.

---

## 5. Particularidades del mercado argentino incorporadas

1. **Especies**: cada bono cotiza en pesos (`AL30`), MEP (`AL30D`) y cable (`AL30C`). Excepciones de nombre: BOPREAL (`BPOA7` pesos ↔ `BPA7D`/`BPA7C`), algunos provinciales (`SJO35` ↔ `SJO5D`, `NDG34` ↔ `NDG4D`, `BA37D` pesos ↔ `BA7DD` MEP). Tickers parecidos pueden ser bonos distintos (`CO2D7` es Córdoba Clase 5 en pesos TAMAR, no `CO27D`).
2. **Liquidación**: CI = hoy; 24hs = próximo día hábil (saltea fines de semana y **feriados de Argentina**). La caución cubre los días corridos entre ambas.
3. **Corte de cupón**: día hábil anterior al pago efectivo (§3.3). Las brechas CI/24hs alrededor de un pago son el cupón, no un arbitraje.
4. **Ley local vs NY**: AL y GD tienen los mismos flujos; la prima NY oscila. Rotar a NY si el costo de pasar de AL a GD es ≤ 1%; a ARG si el ratio es ≥ 1,12 (o z ≥ 1,5 con historia).
5. **Canje**: CCL/MEP − 1; afecta la TIR de los bonos que pagan en cable.
6. **Amortizaciones**: AL30/GD30 tienen 64% de residual a fines de 2026; VT y paridad sobre capital residual. Precios por 100 VN original, "sucios" (con corrido).
7. **Provincia de Buenos Aires** cotiza en otro escalón de riesgo: serie aparte en la curva provincial.
8. **Días no laborables con fin turístico** (ej. 7/12) se tratan como sin liquidación (pendiente de confirmar con el usuario).

---

## 6. Pendientes y próximas versiones

* **Tabla comparativa de Bull Market** (`/Clients/ComparativeTables/bonos`): TIR CI/24hs, paridad y VT de todos los bonos cada 5 min; podría reemplazar a Bonistas. Falta identificar la llamada de datos.
* **Provinciales sin precio en BYMA**: BP28, BPLD, BPLE, CO27D, PUL26 (no cotizan).
* **Confirmar** el tratamiento de los días no laborables con fin turístico.
* **Historia propia**: a partir de ~20 ruedas de uso, los z-scores pasan a ser accionables.
* WebSockets/SSE en lugar del polling del dashboard.

### 6.1 Backlog acordado para una versión futura (fuera de v1.1)

> Decisión del 2026-11-04: **la v1.1 se concentra en BONOS**.

1. **Acciones Merval y Panel General**: CI vs 24hs con las mismas reglas de puntas, costo y ganancia mínima.
2. **CEDEARs**: CI vs 24hs y CCL implícito CEDEAR vs subyacente (los feriados de EE.UU. ya se registran).
3. **Obligaciones Negociables**: curvas corporativas vs soberanos.
4. **"Gangas"**: caídas > 5% con volumen mínimo (> 4 operaciones), como `temporal/MonitorMercado.ps1` (`Show-Gangas`).
5. **Canales externos** (Telegram, etc.): en v1.1 solo Windows + dashboard.

El endpoint de Bull Market `GetStockPrices` acepta `index=merval`, `panel+general` y `cedears`: el conector ya está parametrizado por índice.

---

## 7. Instrucciones operativas

### Ejecución
```powershell
.\.venv\Scripts\python.exe -m backend.main
```
* Dashboard: `http://127.0.0.1:8050` · API: `/docs`.
* Al iniciar: migra la base, carga feriados (los descarga si no son del día), descarga la referencia si no es del día o quedó incompleta, y corre un ciclo de mercado.
* Bull Market: pegar el encabezado `cookie` completo en Command Center → "Bull Market · tiempo real". Con la sesión activa, el ciclo consulta puntas cada 60 s y, una vez por día, los cronogramas de pago.

### Tests
```powershell
.\.venv\Scripts\pytest.exe backend/tests/ -q
```
* Base temporal y fixtures (sin internet). `@pytest.mark.network` solo con `$env:RUN_NETWORK_TESTS="1"`.

### Variables de entorno (o `.env`, no versionado)
* `PORT` (`8050`), `HOST` (`127.0.0.1`; `0.0.0.0` para la red local), `RELOAD` (`false`).
* `DATABASE_URL` (`sqlite:///./bonistas.db`, WAL).
* `POLLING_INTERVAL_SECONDS` (`60`), `MARKET_HOURS_ONLY` (`true`: días hábiles y horario de rueda según BYMA, +25 min por la demora), `FIXED_INCOME_OPEN`/`FIXED_INCOME_CLOSE` (`10:30`/`17:00`: horario de renta fija y caución; acota el de BYMA porque, cuando EE.UU. cambia de horario, acciones y CEDEARs operan hasta las 18:00 pero bonos y caución siguen cerrando a las 17:00).
* `REFERENCE_REFRESH_HOUR` / `REFERENCE_REFRESH_MINUTE` (`10:15` ART, L-V).
* `DISABLE_SCHEDULER` / `SKIP_STARTUP_INGESTION` (tests / desarrollo offline).
* `COMMISSION_PCT` (`0.11`), `MIN_NET_PROFIT_PCT` (`0.40`), `TRADE_SIZE_USD` (`500`): valores por defecto de los parámetros.
* `BULLMARKET_ENABLED` (`true`), `BULLMARKET_COOKIE_FILE` (`secrets/bullmarket_cookie.txt`), `BULLMARKET_COOKIE` (alternativa en `.env`, nunca en el código), `BULLMARKET_MAX_AGE_SECONDS` (`180`).
* `WINDOWS_NOTIFICATIONS` (`true`; las preferencias finas se editan en el dashboard).

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

