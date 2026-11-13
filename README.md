# 📈 Bonistas Monitor: arbitraje de bonos argentinos

Monitor local para detectar **desarbitrajes en bonos soberanos argentinos**, con puntas reales, costos incluidos y profundidad del libro. Detecta:

- diferencias entre **Contado Inmediato y 24hs** de la misma especie, con el **corte de cupón** descontado;
- el **dólar MEP / CCL implícito ejecutable** de cada bono y las idas y vueltas pesos ↔ dólares entre bonos;
- desvíos en los **ratios AL/GD** (ley local vs. Nueva York) y entre bonos de la curva;
- **obligaciones negociables** que rinden de más o de menos contra las otras ON de su emisor.

Además tiene una **ficha por bono** (contexto, sensibilidad a la TIR e historia de precio, TIR y paridad) y un **simulador de swaps** que calcula con las puntas, como el broker.

Cuando aparece una oportunidad que supera la ganancia neta mínima, avisa con una **notificación de Windows** y en el **dashboard**.

> ⚠️ Herramienta personal de análisis. **No es asesoramiento financiero** y no ejecuta órdenes: siempre confirmá precios en tu broker antes de operar.

![Monitor de cotizaciones](docs/screenshots/monitor.jpg)

---

## ✨ Funcionalidades

| | |
|---|---|
| **CI vs 24hs** | Para cada especie con puntas en ambos plazos calcula las dos direcciones. **Vender CI / comprar 24hs:** `(compradora CI − cupón) / vendedora 24hs − 1`. **Comprar CI / vender 24hs:** `(compradora 24hs + cupón) / vendedora CI − 1`, menos la caución por los días entre liquidaciones. A las dos les resta el costo de las dos operaciones. El **corte de cupón** es el día hábil anterior al pago: si el corte cae entre las dos liquidaciones, el pago se descuenta. Sin cronograma conocido **no se emite señal**, y una brecha enorme o que ya existía al cierre anterior se marca **"⚠ corte"** (probable pago no informado), nunca como oportunidad. |
| **Dólar implícito** | TC de compra y de venta de dólares con cada bono (pesos ↔ D/C), con puntas y costos, en todas las combinaciones de plazo. Muestra la mejor ida y vuelta entre bonos. |
| **Ratios** | AL/GD y pares de curva (AE38/GD35, GD38/GD41, …), con los nominales que se obtienen al rotar ya descontados los costos. El z-score se calcula con la historia diaria real: las reglas estadísticas solo actúan con ≥ 20 ruedas. |
| **Cronogramas** | Flujos de cada bono por **consenso** entre CompararBonos, Bull Market, Mercados Argentina y Bruno618: un cronograma queda *verificado* cuando dos fuentes coinciden. Además, una vez por día se agregan los **pagos próximos** que la referencia no lista (por ejemplo, un cupón que vence en días). |
| **Calendario** | **Feriados** de Argentina (MAE) en la liquidación de 24hs, los días de caución y el corte de cupón. Los de EE.UU. se informan. |
| **Profundidad** | Recorre el libro hasta cubrir el **tamaño de operación** configurado (USD 500 por defecto). Si la punta no alcanza, no hay señal. |
| **Tiempo real** | Puntas de **BYMA Open Data**, con 20 min de demora, y, opcionalmente, de **Bull Market** en tiempo real con 5 niveles, usando la sesión del propio usuario. Cada señal indica de dónde salieron sus precios: *confirmada en tiempo real*, *parcial* o *demora 20 min*. |
| **Alertas** | Notificación de Windows y panel en el dashboard para oportunidades nuevas, oportunidades confirmadas en tiempo real, sesión vencida y fuentes caídas, con un período de silencio contra las puntas que oscilan. |
| **Curvas** | Por familia: soberanos USD (Bonares vs Globales y BOPREAL), tasa fija (TEM vs. días), CER (TIR real), provinciales, dollar linked y TAMAR/duales. Cada una tiene su curva ajustada y el **desvío de cada bono en puntos básicos** (cuánto rinde de más o de menos que sus vecinos). Incluye **Argentina vs. región** con el spread contra Treasuries por tramo. La TIR de los bonos en dólares se puede ver **en MEP o en cable**. |
| **Ficha del bono** | Tocando el ticker en el monitor: tipo, ley, moneda de pago, emisión, vencimiento, cupón vigente, precio y cierre anterior, TIR, duration, paridad, valor técnico, residual, intereses corridos, próximo pago con su **corte de cupón**, posición contra los últimos 365 días (percentil), **sensibilidad del precio a la TIR** (±1/2/3, +5 y +10 puntos) y gráficos de **precio, TIR, paridad y ratio contra su par** (con la banda del motor), de 3 meses a toda la historia. La historia revalúa cada cierre diario con los flujos que el bono tenía por delante ese día. |
| **ON: valor relativo** | TIR y duration de cada ON en dólares con precio y cronograma de Bull Market, desvío contra las otras ON de su emisor y contra la curva soberana, e ideas de canje dentro del mismo emisor netas de costos. Informativo, sin alertas. |
| **Simulador de swaps** | Nominales que se obtienen al rotar de un bono a otro y cambio de TIR y duration. Calcula como el broker: **vende a la punta compradora y compra a la vendedora**, recorriendo el libro para la cantidad indicada (Bull Market en tiempo real; si no, BYMA con demora; sin puntas, el último operado con aviso). Muestra los precios usados y su fuente. Se abre directo desde una señal o desde la ficha. |
| **Analítica** | TIR, duration modificada, valor técnico, paridad y breakeven de inflación (tasa fija vs. CER). |
| **Parámetros** | Costo por operación (0,11% todo incluido), ganancia neta mínima (0,40%) y tamaño de operación, **editables desde el dashboard**. |

---

## 🖼️ Capturas

### Curvas de rendimiento por familia
Un punto por bono, con la curva ajustada (punteada). En la tabla lateral, el desvío de cada bono contra su curva.

![Curva soberana](docs/screenshots/curva-soberanos.jpg)

| Desvío contra la curva | Tasa fija (TEM vs. días) |
|---|---|
| ![Desvíos](docs/screenshots/curva-desvios.jpg) | ![Tasa fija](docs/screenshots/curva-tasa-fija.jpg) |

**Provinciales en dólares**: TIR propia con flujos **verificados por consenso** entre CompararBonos, Bruno618 y Mercados Argentina, y precios de BYMA. Provincia de Buenos Aires va en su propia serie. Para los bonos en dólares, la TIR se puede ver **en dólar MEP o en dólar cable**: la diferencia entre las dos es el canje.

![Provinciales](docs/screenshots/curva-provinciales.jpg)

**Argentina vs región**: Globales argentinos contra soberanos de Latinoamérica y la curva de Treasuries (riesgo país por tramo).

![Argentina vs región](docs/screenshots/curva-region.jpg)

### Contado Inmediato vs 24hs
Escáner de todas las especies con puntas en ambos plazos: bruto, costos, caución, ajuste por cupón y neto.

![CI vs 24hs](docs/screenshots/ci-vs-24hs.jpg)

### Dólar implícito ejecutable
Qué bono conviene para comprar o vender dólares MEP / cable, y si una ida y vuelta entre dos bonos deja ganancia después de costos.

![Dólar implícito](docs/screenshots/dolar-implicito.jpg)

### Arbitrajes
Parámetros operativos, conexión con Bull Market en tiempo real, señales activas (con botón para llevarlas al simulador) y matriz de prima de legislación AL/GD.

![Arbitrajes](docs/screenshots/arbitrajes.jpg)

### Ratios entre bonos de la curva
Cada par con su banda propia (21 ruedas ± 1,5 desvíos). Tocando una fila se ve la lectura completa: qué rotar, cuánto deja volver a la media y cómo le fue a la banda en ese par el último año.

![Ratios](docs/screenshots/ratios.jpg)

### Ficha del bono
Se abre tocando el ticker en el monitor. Contexto, métricas al precio actual, próximo pago y corte de cupón, posición contra el último año y sensibilidad del precio a la TIR.

![Ficha del bono](docs/screenshots/ficha.jpg)

Historia de precio, TIR, paridad y ratio contra su par, con los cortes de cupón marcados, y el flujo de fondos pendiente.

![Historia en la ficha](docs/screenshots/ficha-historia.jpg)

### ON: valor relativo
Ideas de canje entre obligaciones negociables del mismo emisor y tabla de TIR, duration y desvío contra el emisor y el soberano.

![ON valor relativo](docs/screenshots/on-valor-relativo.jpg)

### Alertas
Historial de avisos y preferencias de notificación: notificaciones de Windows, solo confirmadas en tiempo real y aviso de fuentes caídas.

![Alertas](docs/screenshots/alertas.jpg)

### Guía de uso integrada
Con el botón **?** del encabezado se abre una guía con el objetivo de la app, los primeros pasos, qué hace cada herramienta, cómo leer una señal, un glosario y las fuentes y límites. Se muestra sola la primera vez.

![Guía de uso](docs/screenshots/guia.jpg)

### Simulador de swaps
Precios ejecutables para la cantidad indicada, con su fuente, y el resultado en nominales y en porcentaje.

![Simulador de swaps](docs/screenshots/simulador-swaps.jpg)

> Capturas del 12/11/2026 con la rueda abierta y Bull Market en tiempo real.

---

## 🚀 Instalación

Requisitos: **Python 3.11+**. Las notificaciones de escritorio requieren Windows 10/11; el resto funciona en cualquier sistema operativo.

```powershell
git clone https://github.com/bluecold/bonistas.git
cd bonistas
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m backend.main
```

Abrí **http://127.0.0.1:8050**. La documentación de la API está en `/docs`.

Al iniciar, el servidor:
1. crea o migra la base SQLite (`bonistas.db`) sin perder datos;
2. carga los feriados de mercado (MAE);
3. descarga los datos de referencia del día: flujos y clasificación de CompararBonos, cronogramas de provinciales (Bruno618 y Mercados Argentina), CER/TAMAR/A3500 del BCRA;
4. consulta las cotizaciones y evalúa las estrategias.

Después repite el ciclo **cada 60 segundos, solo en el horario de renta fija (10:30 a 17:00)**. La referencia se actualiza todos los días hábiles a las 10:15.

### Bull Market en tiempo real (opcional)
1. Iniciá sesión en Bull Market en el navegador y abrí *Cotizaciones → Bonos*.
2. F12 → **Red** → buscá la petición `GetStockPrices` → copiá el encabezado `cookie` (o "Copiar como cURL").
3. Pegalo en el panel **Bull Market · tiempo real** de la pestaña Arbitrajes y tocá **Guardar y probar**. Tiene que ser el encabezado completo (`nombre=valor; nombre2=valor2; …`), no el valor de una sola cookie.

Con la sesión activa, la app consulta las puntas cada minuto durante la rueda y, una vez por día, los **cronogramas de pago** de todos los bonos. En la práctica, el polling mantiene viva la sesión.

La cookie se guarda **solo en tu PC** (`secrets/bullmarket_cookie.txt`, ignorado por git) y la API nunca la devuelve. **Pegala únicamente en ese panel**: no la compartas en chats, issues ni capturas. El sistema **no inicia sesión por vos** ni usa tu usuario o contraseña. Cuando la sesión vence, avisa y sigue funcionando con BYMA.

---

## ⚙️ Configuración

Todas las opciones se pueden definir con variables de entorno o en un archivo `.env` (no versionado):

| Variable | Default | Descripción |
|---|---|---|
| `PORT` / `HOST` | `8050` / `127.0.0.1` | Por defecto solo escucha en esta PC. |
| `POLLING_INTERVAL_SECONDS` | `60` | Frecuencia del ciclo de mercado. |
| `MARKET_HOURS_ONLY` | `true` | Solo consulta en días hábiles y en horario de rueda (según BYMA). |
| `FIXED_INCOME_OPEN` / `FIXED_INCOME_CLOSE` | `10:30` / `17:00` | Horario de renta fija y caución. Acota el que informa BYMA, que puede ser el de acciones y CEDEARs (hasta las 18:00 cuando EE.UU. cambia de horario). |
| `COMMISSION_PCT` | `0.11` | Costo por operación, todo incluido (también editable en el dashboard). |
| `MIN_NET_PROFIT_PCT` | `0.40` | Ganancia neta mínima para emitir una señal. |
| `TRADE_SIZE_USD` | `500` | Tamaño de operación para evaluar la profundidad. |
| `BULLMARKET_ENABLED` | `true` | Usar Bull Market si hay sesión. |
| `WINDOWS_NOTIFICATIONS` | `true` | Notificaciones de escritorio. |
| `DATABASE_URL` | `sqlite:///./bonistas.db` | Base de datos (SQLite en modo WAL). |

Lista completa en [PROJECT_CONTEXT.md §7](PROJECT_CONTEXT.md).

---

## 🗂️ Fuentes de datos

| Fuente | Uso | Demora |
|---|---|---|
| [BYMA Open Data](https://open.bymadata.com.ar) | Puntas CI/24hs de todos los bonos, cauciones, horario de mercado | 20 min |
| Bull Market (sesión del usuario) | Puntas con 5 niveles de profundidad; cronogramas de pago | Tiempo real / diario |
| [Bonistas.com](https://bonistas.com) | TIR, duration, paridad, valor técnico | — |
| [Bonistas.com · próximos pagos](https://bonistas.com/proximos-pagos) | Cronogramas de más de cien ON sin sesión de Bull Market; pagos con corte inminente | Diario |
| [CompararBonos](https://compararbonos.com.ar) | Flujos de fondos y especies de cada bono | Diario |
| [Bruno618](https://bruno618.com/herramientas/flujo-de-fondos-renta-fija) | Cronogramas de provinciales en dólares | Diario |
| [Mercados Argentina](https://mercadosargentina.com.ar/renta-fija/titulos) | Cronogramas de provinciales (verificación por consenso) | Diario |
| [API del BCRA](https://www.bcra.gob.ar) | CER (también su serie histórica, para la TIR histórica de los CER en la ficha), TAMAR, A3500 | Diario |
| [MAE Market Data](https://api.marketdata.mae.com.ar/api/mercado/feriados) | Feriados de mercado (Argentina y EE.UU.) | Diario |
| [Rava](https://www.rava.com) | Cierres diarios históricos de los bonos con ratio: soberanos en dólares, CER cupón cero, DICP/DIP0, TX31 y AO28/AO29/AN29 (bandas de los ratios entre bonos); y de cualquier bono al abrir su ficha | Diario |
| [DolarAPI](https://dolarapi.com) | Dólar MEP, CCL, oficial | — |

Las cotizaciones se consultan una vez por minuto en horario de rueda, y solo se guarda un registro nuevo cuando el dato cambió. Las fuentes de referencia y cronogramas se consultan una vez por día, de a una página por vez y con pausas.

---

## 🏛️ Arquitectura

```
backend/
├── main.py                     # FastAPI + APScheduler (ciclo de mercado y referencia diaria)
└── app/
    ├── api/routes.py           # Endpoints REST
    ├── arbitrage/
    │   ├── market_view.py      # Libros por especie/plazo, prioridad de fuentes, cupones entre liquidaciones
    │   ├── ci_24hs.py          # Detector CI vs 24hs
    │   ├── fx_implied.py       # Dólar implícito e ida y vuelta
    │   ├── ratios.py           # Ratios AL/GD y de curva, bandas con historia de Rava
    │   ├── on_relative_value.py # ON: TIR contra su emisor y el soberano, ideas de canje
    │   └── engine.py           # Orquestación, señales persistentes, Command Center
    ├── data/                   # Clientes: BYMA, Bull Market, Bonistas, CompararBonos, Bruno618,
    │                           #   Mercados Argentina, BCRA, MAE, DolarAPI, Rava
    ├── quant/                  # Flujos, TIR, duration, valor técnico, swaps
    ├── services/               # Ingesta, libros, referencia y consenso de cronogramas, curvas,
    │                           #   calendario y feriados, sesión Bull Market, alertas, notificador,
    │                           #   historia diaria (Rava/BCRA), ficha del bono (bond_profile_service),
    │                           #   precios ejecutables del simulador (swap_pricing), cronogramas de ON
    ├── db/                     # Modelos SQLAlchemy y migraciones mínimas
    └── static/index.html       # Dashboard (Tailwind + Plotly)
```

---

## 🧪 Tests

```powershell
.\.venv\Scripts\pytest backend/tests -q
```

333 tests. Corren **sin internet y sin tocar `bonistas.db`**: usan una base temporal y respuestas reales recortadas como fixtures. Nunca usan la cookie real ni muestran notificaciones. Los tests que consultan APIs reales están marcados `network` y solo corren con `RUN_NETWORK_TESTS=1`.

---

## 🛣️ Próximas versiones

Acciones y Merval, CEDEARs, detector de "gangas" y alertas por Telegram. Ver [PROJECT_CONTEXT.md §6.1](PROJECT_CONTEXT.md).

Para el detalle de las decisiones financieras y técnicas, y el registro de cambios de la v1.1, ver [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).
