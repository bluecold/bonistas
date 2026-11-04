# Especificación Técnica y Funcional: Sistema de Trading y Arbitraje de Bonos Argentinos (v1.0)

Este documento establece la especificación formal de arquitectura, modelos de datos, motores algorítmicos y requerimientos funcionales para el desarrollo de la versión 1.0 del **Sistema de Monitoreo, Valuación y Arbitraje de Bonos Argentinos**. La especificación está diseñada para ser ejecutada directamente por **Antigravity** como agente desarrollador principal.

---

## 1. Resumen Ejecutivo y Visión del Producto

### 1.1 Propósito de la Aplicación
El objetivo principal del sistema es proporcionar un motor cuantitativo en tiempo real que identifique, notifique y catalogue oportunidades de arbitraje y valor relativo en el mercado de renta fija pública de la República Argentina. El sistema cubre títulos emitidos en dólares (*Hard Dollar* bajo ley local y ley Nueva York), títulos a tasa fija y capitalizables en pesos (LECAPs y BONCAPs), bonos ajustados por inflación (BONCER y LECER), bonos duales (CER/TAMAR) y títulos de deuda para importadores (BOPREAL).

### 1.2 Alcance del MVP (Versión 1.0)
La versión 1.0 se enfoca en los siguientes pilares operativos:
*   **Ingesta Automática de Precios**: Extracción continua de cotizaciones, precios de liquidación (24hs y Contado Inmediato), paridades y métricas financieras desde fuentes públicas y especializadas como Bonistas.com, DolarAPI e información oficial del BCRA/INDEC.
*   **Motor de Cálculo Cuantitativo**: Cálculo unificado de Paridad, Tasa Interna de Retorno (TIR/YTM), Tasa Efectiva Mensual (TEM), Tasa Nominal Anual (TNA), Modified Duration (MD), Valor Técnico (VT) y Tipos de Cambio Implícitos (Dólar MEP y Dólar Cable/CCL).
*   **Detección Algorítmica de Arbitrajes**: Ejecución de cuatro estrategias automatizadas:
    1.  *Spread de Legislación*: Desarbitrajes entre Bonos Ley Argentina (Bonares AL) y Ley Nueva York (Globales GD).
    2.  *Relative Value en Curva*: Desarbitrajes de convexidad y rendimiento entre títulos de duraciones similares o del mismo tramo de curva (ejemplo: GD29 vs AL30).
    3.  *Breakeven de Inflación*: Comparación de tasas entre curvas a Tasa Fija (LECAPs/BONCAPs) y ajustadas por CER (BONCER).
    4.  *Estrategia Dual*: Matriz de decisión y maximización de rendimiento para bonos Duales (TAMAR vs CER).
*   **Dashboard Interactivo**: Panel web para la visualización de curvas de rendimiento, matriz de desvíos estándar y panel de señales operativas con alertas en tiempo real.

---

## 2. Arquitectura General del Sistema y Stack Tecnológico

El sistema se concibe bajo una arquitectura modular desacoplada de tres capas: Ingesta/ETL, Motor Financiero-Algorítmico y Capa de Presentación/API.

### 2.1 Stack Tecnológico Recomendado
*   **Lenguaje Principal**: Python 3.12+ (aprovechando bibliotecas científicas y financieras avanzadas).
*   **Framework de API y Servidor Backend**: FastAPI para alta velocidad de procesamiento asíncrono y documentación OpenAPI automática.
*   **Procesamiento de Datos**: Pandas 2.2+ y NumPy 1.26+ para cálculos matriciales de curvas y vectores de flujo de fondos.
*   **Base de Datos**: PostgreSQL 16+ (o SQLite en entorno local de desarrollo) con SQLAlchemy 2.0 como ORM para almacenamiento temporal de cotizaciones históricas y registros de señales.
*   **Frontend / UI**: Dashboard dinámico desarrollado en React o mediante server-side rendering optimizado con FastHTML / TailwindCSS y gráficos interactivos con Plotly.js.
*   **Programador de Tareas**: Celery con Redis o APScheduler para el polling periódico de cotizaciones cada 15-30 segundos durante la Rueda Bursátil (11:00 a 17:00 hs ART).

### 2.2 Esquema de Capas del Sistema

```
 [ Fuentes de Datos ]
   ├── Bonistas.com (Scraper / Ingesta HTML-JSON)
   ├── DolarAPI / ArgentinaDatos (MEP, CCL, Oficial)
   └── BCRA / INDEC API (IPC, CER, Base Monetaria, TAMAR)
            │
            ▼
 [ Capa 1: Ingesta y Normalización (ETL Pipeline) ]
            │
            ▼
 [ Capa 2: Motor de Cálculo Financiero y Métricas ]
   ├── Calculador de Paridad, VT, TIR y Modified Duration
   ├── Matriz de Tipos de Cambio Implícitos (MEP / CCL)
   └── Calculador de Breakeven Inflacionario
            │
            ▼
 [ Capa 3: Motor Algorítmico de Arbitrajes ]
   ├── Evaluador de Spread de Legislación (AL vs GD)
   ├── Evaluador de Relative Value & Convexidad (GD29 vs AL30)
   ├── Evaluador Tasa Fija vs CER (LECAP vs BONCER)
   └── Evaluador de Bonos Duales (TAMAR vs CER)
            │
            ▼
 [ Capa 4: API FastAPI & Dashboard Web / Alertas ]
```

---

## 3. Módulo de Ingesta y Conectores de Datos

El módulo de ingesta debe capturar de manera robusta las tablas de cotizaciones y variables macroeconómicas.

### 3.1 Fuentes de Datos e Integración

1.  **Conector Bonistas.com (Fuente Primaria)**:
    *   **Método**: Scraper HTML analizado mediante BeautifulSoup4 / Playwright o consulta a endpoints JSON internos de la plataforma.
    *   **Frecuencia**: Polling cada 30 segundos durante horario bursátil.
    *   **Tablas Objetivo**:
        *   *Hard Dollar Ley NY*: GD29D, GD30D, GD35D, GD38D, GD41D, GD46D.
        *   *Hard Dollar Ley Argentina*: AL29D, AL30D, AL35D, AE38D, AL41D, AO27D, AO28D, AN29D, AO29D.
        *   *Tasa Fija y Letras*: T15E7, T30A7, T31Y7, T30J7, TY30P, S13N6, S30N6.
        *   *Bonos TAMAR (Floaters)*: TTD26_TAM, TMF27, TML27, TMG27, TMF28, TMG28.
        *   *Bonos Duales (CER / TAMAR)*: TXMJ8, TXMD8, TXMJ9, TXMD9, TXMJ0, TTD26.
        *   *Bonos CER y LECER*: TX26, TZXD6, TZXM7, TZX27, TX28, TZXO7, TZXD7, TZX28, TZXD8, TX31, DIP0, DICP, PAP0, PARP, CUAP, X30N6, TZXA7, TZXY7, TZXS7, TZXM8, TZXS8, TZXM9.
        *   *BOPREAL*: BPA7D, BPB7D, BPD7D, BPC7D, BPB8D, BPA8D.
        *   *Dólar Linked*: D31M7, D10Y7, TZV27, TZV28, TZVD8.
        *   *Dólares Financieros*: AL29, AL30, AL35, AE38, AL41, GD29, GD30, GD35, GD38, GD41 en sus tres especies (Pesos, Especie D - MEP, Especie C - Cable).

2.  **Conector Macro (BCRA / INDEC / DolarAPI)**:
    *   **Variables**: Inflación mensual IPC, valor diario del coeficiente CER, tasa TAMAR mayorista, Tipo de Cambio Oficial A3500 y cotizaciones alternativas.
    *   **Frecuencia**: Ejecución diaria a las 00:00 ART y actualización de IPC ante cada publicación del INDEC.

---

## 4. Modelo de Datos y Entidades de Dominio

La base de datos relacional debe estructurarse según las siguientes entidades clave:

```sql
-- Tabla de Títulos Públicos (Especie / Maestro de Bonos)
CREATE TABLE bonds (
    ticker VARCHAR(12) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    isin VARCHAR(12),
    currency VARCHAR(5) NOT NULL, -- 'USD', 'ARS'
    law VARCHAR(10) NOT NULL, -- 'ARG', 'NY'
    bond_type VARCHAR(20) NOT NULL, -- 'HARD_DOLLAR', 'CER', 'TASA_FIJA', 'DUAL', 'TAMAR', 'BOPREAL', 'DOLLAR_LINKED'
    amortization_type VARCHAR(20), -- 'BULLET', 'SEMESTRAL'
    maturity_date DATE NOT NULL,
    coupon_rate NUMERIC(6,4),
    base_nominal NUMERIC(12,2) DEFAULT 100.0
);

-- Snapshots de Cotizaciones en Tiempo Real
CREATE TABLE price_snapshots (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(12) REFERENCES bonds(ticker),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    settlement_type VARCHAR(5) NOT NULL, -- 'CI', '24HS'
    price_ars NUMERIC(14,4),
    price_mep NUMERIC(14,4), -- Especie D
    price_ccl NUMERIC(14,4), -- Especie C
    volume_millions NUMERIC(14,2),
    technical_value NUMERIC(14,4),
    parity_percentage NUMERIC(6,3),
    ytm_percentage NUMERIC(6,3), -- TIR
    tem_percentage NUMERIC(6,3), -- Tasa Efectiva Mensual
    tna_percentage NUMERIC(6,3), -- Tasa Nominal Anual
    modified_duration NUMERIC(6,3)
);

-- Registro de Señales de Arbitraje Generadas
CREATE TABLE arbitrage_signals (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    strategy_name VARCHAR(40) NOT NULL, -- 'LAW_PREMIUM', 'RELATIVE_VALUE_CURVE', 'BREAKEVEN_CER_FIXED', 'DUAL_TAMAR_CER'
    leg_sell_ticker VARCHAR(12) NOT NULL,
    leg_buy_ticker VARCHAR(12) NOT NULL,
    metric_name VARCHAR(30) NOT NULL, -- 'SPREAD_PRICE_RATIO', 'SPREAD_YIELD_BPS', 'BREAKEVEN_TEM'
    metric_value NUMERIC(10,4) NOT NULL,
    historical_mean NUMERIC(10,4),
    std_deviations NUMERIC(5,2),
    action_recommended VARCHAR(20) NOT NULL, -- 'ROTAR_A_NY', 'ROTAR_A_ARG', 'SWAP_DURACION', 'COMPRAR_CER', 'COMPRAR_TASA_FIJA'
    status VARCHAR(15) DEFAULT 'ACTIVE' -- 'ACTIVE', 'EXECUTED', 'EXPIRED'
);
```

---

## 5. Motor de Cálculo Financiero y Métricas de Renta Fija

El motor numérico implementará algoritmos estándar del mercado de capitales para la valuación de títulos públicos.

### 5.1 Fórmulas Matemáticas y Definiciones Cuantitativas

1.  **Valor Técnico (VT)**:
    Representa el valor residual del bono sumado a los intereses corridos devengados desde la última fecha de pago de cupón hasta la fecha de liquidación.
    $$VT = Capital\ Residual + Intereses\ Corridos$$

2.  **Paridad (%)**:
    Indica la relación porcentual entre el precio de mercado en su especie correspondiente ($P$) y el Valor Técnico ($VT$).
    $$Paridad (\%) = \left( \frac{P}{VT} \right) \times 100$$

3.  **Tasa Interna de Retorno (TIR / YTM)**:
    Es la tasa de descuento $r$ que iguala el precio sucio (*dirty price*) del bono $P$ con el valor presente de su flujo futuro de fondos (cupones de interés $C_t$ y amortizaciones de capital $A_t$):
    $$P = \sum_{t=1}^{N} \frac{C_t + A_t}{(1 + r)^{t_t}}$$

4.  **Modified Duration (MD)**:
    Mide la sensibilidad del precio del bono ante variaciones en la tasa de interés. Se calcula dividiendo la Duración de Macaulay ($D_{Mac}$) por el factor de capitalización de la TIR:
    $$D_{Mac} = \frac{\sum_{t=1}^{N} \frac{t \cdot (C_t + A_t)}{(1 + r)^t}}{P}, \quad MD = \frac{D_{Mac}}{1 + \frac{r}{k}}$$
    Donde $k$ es la frecuencia anual de pagos de cupón ($k=2$ para bonos semestrales).

5.  **Tipos de Cambio Implícitos (Dólar MEP y CCL)**:
    Para un mismo bono (ejemplo: AL30) cotizando en Pesos ($AL30$), Dólar MEP ($AL30D$) y Dólar Cable ($AL30C$):
    $$MEP_{implícito} = \frac{Precio_{ARS}}{Precio_{USD\_MEP}}, \quad CCL_{implícito} = \frac{Precio_{ARS}}{Precio_{USD\_CABLE}}$$

6.  **Breakeven de Inflación Implícito**:
    Dada la TIR de un bono a Tasa Fija ($TIR_{TF}$) y la TIR real de un bono ajustado por CER ($TIR_{CER}$) de idéntico vencimiento o duración equivalente:
    $$Breakeven_{Anual} = \left( \frac{1 + TIR_{TF}}{1 + TIR_{CER}} \right) - 1$$
    $$Breakeven_{Mensual} = (1 + Breakeven_{Anual})^{1/12} - 1$$

---

## 6. Motor Algorítmico de Arbitrajes y Reglas de Negocio

El núcleo analítico de la aplicación consta de cuatro sub-motores que evalúan el mercado de manera ininterrumpida.

### 6.1 Estrategia 1: Spread de Legislación (Law Premium AL vs. GD)
*   **Fundamentos Financieros**: Los bonos gemelos en dólares de la reestructuración 2020 comparten el mismo flujo de fondos pero difieren en su jurisdicción legal. Los Bonares (AL29, AL30, AL35, AE38, AL41) están bajo legislación local y tribunales de la República Argentina, mientras que los Globales (GD29, GD30, GD35, GD38, GD41, GD46) se rigen por la ley del Estado de Nueva York con Cláusulas de Acción Colectiva (CACs) internacionales.
*   **Métrica de Evaluación**:
    *   Spread de Precio Nominal Ratio: $Ratio = \frac{Precio_{GD}}{Precio_{AL}}$
    *   Spread de TIR (Yield Spread): $Spread_{TIR} = TIR_{AL} - TIR_{GD}$
*   **Reglas de Activación de Señales**:
    *   **Regla A (Rotación hacia Ley Nueva York)**: Si el spread de legislación en precio se comprime hacia valores cercanos al 0% (es decir, $Ratio \le 1.01$ o $Spread_{TIR} \le 20\text{ bps}$), indicando que el mercado no está cobrando prima por resguardo legal neoyorquino, la señal recomienda **Vender AL (Ley ARG) y Comprar GD (Ley NY)** (ejemplo: Swap de AL30D por GD30D, o AE38D por GD38D). Esto brinda mayor seguridad jurídica sin costo de rendimiento ni paridad.
    *   **Regla B (Rotación hacia Ley Argentina)**: Si el spread de legislación se ensancha por encima de su promedio histórico ajustado por volatilidad ($Ratio \ge 1.12 - 1.15$ o desvío estándar $+1.5\sigma$ a $+2.0\sigma$ sobre la media móvil de 252 días), la señal recomienda **Vender GD y Comprar AL**, anticipando una compresión de brecha hacia el promedio.

### 6.2 Estrategia 2: Relative Value & Duration Swap (Tramo Corto GD29 vs. AL30)
*   **Fundamentos Financieros**: Análisis de valor relativo en bonos del tramo corto de la curva hard dollar. Por ejemplo, la comparativa entre el Global 2029 (GD29) y el Bonar 2030 (AL30). Aunque el GD29 posee un cupón levemente superior, el AL30 ofrece mayor TIR y una superior convexidad con una Modified Duration prácticamente equivalente (~1.66 a 2.17 en AL30 vs 1.29 a 1.81 en GD29).
*   **Métrica de Evaluación**:
    *   Diferencial de TIR: $\Delta TIR = TIR_{AL30} - TIR_{GD29}$
    *   Z-Score de Rendimiento sobre media móvil de 252 días:
        $$Z = \frac{\Delta TIR_{actual} - \mu_{252}}{\sigma_{252}}$$
*   **Regla de Activación**:
    *   Cuando el spread de rendimientos entre AL30 y GD29 supere $+1.1\sigma$ (desvíos estándar por encima de la media histórica, correspondiente a diferenciales superiores a $\approx 130\text{ bps}$), el sistema activa la señal **"SELL GD29 & BUY AL30"**, aprovechando que la mayor convexidad del AL30 capturará mayores ganancias en escenarios alcistas de tasas (compresión de riesgo país) y amortiguará mejor las pérdidas en escenarios adversos.

### 6.3 Estrategia 3: Breakeven de Inflación y Rotación de Deuda en Pesos (LECAP/BONCAP vs. BONCER)
*   **Fundamentos Financieros**: Arbitraje de tasa nominal frente a tasa real en pesos. Los títulos a Tasa Fija/Capitalizables (LECAPs y BONCAPs como T15E7, T30A7, S30N6) pagan un rendimiento nominal fijo. Los bonos CER (BONCER como TZX27, TZX28, TZXM8, TX31) ajustan por inflación más una tasa real.
*   **Métrica de Evaluación**:
    *   Cálculo del Breakeven de Inflación mensual implícito ($Breakeven_{TEM}$).
    *   Comparación directa con la expectativa de inflación mensual del REM (Relevamiento de Expectativas de Mercado del BCRA) o modelos de proyección propios.
*   **Reglas de Activación**:
    *   **Señal CER**: Si la inflación proyectada mensual supera el $Breakeven_{TEM}$ de mercado (por ejemplo, proyectado $> 1.8\%$ mensual frente a un breakeven de $1.7\%$ o $16.5\%$ anual), la señal recomienda **Posicionarse en BONCER medio/largo** para capturar el ajuste por inflación más la tasa real (que en tramos medios paga entre $+6.6\%$ y $+8.5\%$ real).
    *   **Señal Tasa Fija**: Si la inflación proyectada es inferior al breakeven implícito, la señal recomienda **Posicionarse en Tasa Fija (LECAP/BONCAP)** en el tramo de mayor conveniencia (~110 días, como T30A7/S30N6 con TEMs de $\sim 1.94\%$), asegurando una tasa real positiva sin riesgo inflacionario.

### 6.4 Estrategia 4: Cobertura Sintética con Bonos Duales (TAMAR vs. CER)
*   **Fundamentos Financieros**: Los bonos duales en pesos (ejemplo: TXMD8, TXMD9, TXMJ0) garantizan en la liquidación de cada cupón o amortización el máximo retorno entre la tasa variable TAMAR (más un margen fijo) y el ajuste de inflación por CER (más un margen fijo).
*   **Métrica de Evaluación**:
    *   Spread de rinde TAMAR vs. rinde CER implícito en las patas del dual.
*   **Regla de Activación**:
    *   El sistema monitorea la relación entre la curva floater TAMAR (títulos como TTD26, TMF27, TMG28) y los BONCER. Ante escenarios de alta volatilidad de tasas de interés y dudas sobre el sendero de desinflación, el algoritmo clasifica a los bonos Duales TAMAR/CER como el **Activo de Cobertura Óptimo**, otorgando un piso de tasa fija/variable con opción implícita alcista si las tasas suben o si la inflación se acelera.

---

## 7. Interfaz de Usuario y Dashboard (UI/UX)

La aplicación web debe ser limpia, funcional y orientada a la toma de decisiones rápidas de trading.

### 7.1 Componentes Principales de la UI

1.  **Monitor de Cotizaciones y Matriz de Paridades**:
    *   Tabla en tiempo real ordenada por tipología de bono.
    *   Visualización de Especie Pesos, Dólar MEP (D), Dólar Cable (C), TIR, Paridad, Modified Duration, Valor Técnico y Tipos de Cambio implícitos (MEP y CCL).
    *   Highlight automático de desvíos significativos de precios en la rueda intradiaria.

2.  **Gráfico Interactivo de Curvas de Rendimiento (Yield Curves)**:
    *   Gráfico de dispersión X/Y (Plotly.js) donde el eje X representa la *Modified Duration* y el eje Y representa la *TIR (%)*.
    *   Visualización simultánea de la Curva Hard Dollar Ley ARG (Bonares AL), Curva Hard Dollar Ley NY (Globales GD), Curva Tasa Fija (LECAPs/BONCAPs) y Curva CER.
    *   Línea de tendencia suavizada (spline) para identificar de manera visual bonos por encima (baratos/rendimiento alto) o por debajo (caros/rendimiento bajo) de su curva teórica.

3.  **Panel de Señales de Arbitraje (Arbitrage Command Center)**:
    *   Matriz de oportunidades activas categorizadas por estrategia (*Law Premium*, *Relative Value*, *Breakeven Inflación*, *Duales*).
    *   Indicadores visuales tipo Semáforo (Verde = Arbitraje Claro, Amarillo = En Observación, Rojo = Sin Desviación).
    *   Detalle del trade: Bono a Vender, Bono a Comprar, Spread Actual vs. Media Histórica, Z-Score y Retorno Estimado del Arbitraje.

4.  **Simulador de Swaps y Calculadora de Retorno**:
    *   Calculadora donde el trader ingresa la cantidad nominal a vender de un bono (ej. 10.000 GD30D) y el sistema calcula la cantidad a comprar del bono destino (ej. AL30D), contemplando comisiones operativas ajustables, aranceles de BYMA y el impacto neto en la cartera.

---

## 8. Plan de Implementación y Roadmap v1.0 para Antigravity

Antigravity deberá estructurar el desarrollo de la solución en cuatro sprints consecutivos de una semana de duración cada uno (total: 4 semanas de desarrollo).

### 8.1 Plan de Sprints

```
 Sprint 1: Ingesta y Base de Datos
 ├── Implementar modelos SQLAlchemy (bonds, price_snapshots, arbitrage_signals)
 ├── Desarrollar Scraper/API Parser para Bonistas.com (Hard Dollar, CER, Tasa Fija, Duales)
 └── Desarrollar Conectores BCRA/INDEC/DolarAPI para variables macro

 Sprint 2: Motor Financiero Cuantitativo
 ├── Implementar biblioteca matemática para flujo de fondos de bonos argentinos
 ├── Desarrollar funciones de Paridad, Valor Técnico, TIR (YTM) y Modified Duration
 └── Implementar matriz de cálculo de Dólar MEP/CCL implícito y Breakeven de Inflación

 Sprint 3: Motor Algorítmico de Arbitrajes
 ├── Programar reglas de Spread de Legislación (AL vs GD) con Z-Scores de 252 días
 ├── Programar reglas de Relative Value y Convexidad (GD29 vs AL30)
 ├── Programar reglas de Breakeven Inflacionario (LECAP vs BONCER)
 └── Programar reglas de evaluación de Bonos Duales

 Sprint 4: Dashboard UI y Alertas en Tiempo Real
 ├── Construir Dashboard Web dinámico (FastAPI + React / FastHTML + TailwindCSS)
 ├── Integrar gráficos de Curvas de Rendimiento interactivos en Plotly.js
 ├── Implementar sistema de Alertas en tiempo real (Sockets / Notificaciones)
 └── Ejecutar suite de pruebas de integración con cotizaciones reales de mercado
```

### 8.2 Criterios de Aceptación (Definition of Done para v1.0)
1.  **Fiabilidad de Ingesta**: El sistema debe extraer e insertar en la base de datos las cotizaciones de todos los bonos soberanos listados sin fallos durante toda la rueda bursátil (6 horas continuas).
2.  **Precisión Matemática**: Los cálculos de TIR, Paridad, Modified Duration y Tipos de Cambio implícitos deben diferir en menos del $0.1\%$ respecto a los valores mostrados en pantallas profesionales y Bonistas.com.
3.  **Generación Correcta de Señales**: Ante un evento simulado o real de brecha por legislación entre AL30 y GD30 tendiente a 0%, el sistema debe emitir la señal de "Rotación a Ley NY" en menos de 2 segundos desde la ingesta del precio.
4.  **Usabilidad**: El dashboard debe renderizar completamente la matriz de cotizaciones y las curvas de rendimiento en menos de 1.5 segundos en navegadores estándar.
