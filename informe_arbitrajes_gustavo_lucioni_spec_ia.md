# Especificación Técnica de Estrategias de Arbitraje en Renta Fija Argentina según el Marco Operativo de Gustavo Lucioni

El mercado argentino de renta fija presenta fragmentaciones estructurales derivadas coexistentes de distintas jurisdicciones legales, monedas de denominación y liquidación, cláusulas de ajuste indexado, regímenes de amortización y restricciones microestructurales de liquidez. El análisis sistemático del canal de YouTube de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni), complementado con los reportes periódicos elaborados junto a [Mercap Abbaco](https://mercapsoftware.com/author/mercap/) y las planillas operativas de seguimiento en tiempo real ([Arbitraje Ratios](https://docs.google.com/spreadsheets/d/1W2kTK4n10-fKWYRJmoffOnxdaibkL-7I5wduSHVlGvI/edit?usp=drivesdk&ouid=103928833983870106232) y [Copia de Arbitraje Ratios](https://docs.google.com/spreadsheets/d/13p_RLsTPMxfkBnbe7awyfw2cQGyAglh6O96Yhw0Y9dM/edit?usp=drivesdk&ouid=103928833983870106232)), permite codificar un catálogo exhaustivo de estrategias de arbitraje, rotación táctica y valor relativo entre bonos soberanos, títulos subsoberanos (provinciales), Obligaciones Negociables (ONs) corporativas, letras del Tesoro y activos de renta variable.

El presente documento estructura la totalidad de las reglas de detección, los universos de instrumentos, las ecuaciones financieras subyacentes y las condiciones de borde microestructurales de modo que un sistema de inteligencia artificial orientado al desarrollo de software pueda auditar un motor de alertas preexistente, identificar módulos faltantes e implementar los algoritmos de detección correspondientes.

## Taxonomía General de Estrategias de Arbitraje y Rotación Detectadas

A diferencia del arbitraje espacial clásico sin riesgo propio de mercados altamente eficientes, el marco operativo desarrollado en los análisis de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni) abarca tanto arbitrajes puros de flujo idéntico como arbitrajes estadísticos de reversión a la media sobre ratios de precios, desarbitrajes de pendiente en curvas de tasas internas de retorno (TIR), rotaciones de convexidad por simulación de sensibilidad cruzada y arbitrajes microestructurales sobre la caja de puntas (*order book*).

La revisión integral del corpus audiovisual y documental arroja diez familias diferenciadas de arbitraje que un motor de alertas completo debe monitorear de forma simultánea:

1. **Arbitraje de Legislación y Jurisdicción en Soberanos Hard Dollar (Spread Ley Nueva York vs. Ley Argentina):** Explotación de desvíos estadísticos en el ratio de precios o diferencial de TIR entre títulos soberanos con idéntico flujo de fondos pero distinta ley aplicable (`GD30` vs. `AL30`, `GD38` vs. `AE38`, `GD41` vs. `AL41`, `GD35` vs. `AL35`, `GD29` vs. `AL29`), según se documenta en [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) y [¿TX31 o DICP? (2026) Gus Lucioni](http://www.youtube.com/watch?v=UtqZ3XpyJHE).
2. **Arbitraje Intra-Curva CER por Anomalía de Duration, Cupón y Ventana de Pass-Through:** Detección de inversiones o compresiones anómalas de tasa real entre bonos ajustados por inflación de distinto plazo o estructura (`TX31` vs. `DICP`, `TZXS8` vs. `TZX28`, `TZXS7` vs. `TZXS8`, `TZXO7` vs. `TZXS7`, `TZXS8` vs. `TZXM9`, `TX26` vs. `TX28` y `DICP` vs. `DIP0`), desarrolladas en [¿TX31 o DICP? (2026) Gus Lucioni](http://www.youtube.com/watch?v=UtqZ3XpyJHE), [¿TZXS8 o TZX28? (2026) Gus Lucioni](http://www.youtube.com/watch?v=NKLjxmYOK4Q) y [Nuevo Bono TZXO7 (2026) Gus Lucioni](http://www.youtube.com/watch?v=xjvXqUOxTLM).
3. **Arbitraje Cross-Asset Soberano entre Tasa Real en Pesos (CER) y Tasa en Dólares (Hard Dollar):** Rotación direccional entre las curvas CER y Hard Dollar para tramos equivalentes de *Modified Duration* (`PARP` vs. `GD41`/`AL41`, `DICP` vs. `AE38`/`GD38`, `TX31` vs. `AL30`/`GD30`) cuando se invierte la relación teórica $\text{TIR}_{\text{CER}} < \text{TIR}_{\text{HD}}$, analizada en [Rotar de HD a CER ¿Sigue siendo Oportunidad? (2025) Gus Lucioni](http://www.youtube.com/watch?v=GGXMEcxL7yY) y [¿Momento de rotar Bonos CER a Bonos en USD? (2026) Gus Lucioni](http://www.youtube.com/watch?v=_GG5fkS0xi8).
4. **Arbitraje Intra-Curva Soberana Hard Dollar por Flujo Acumulado, Frecuencia de Pago e Indenture:** Rotaciones tácticas pre-corte de cupón (`GD41` hacia `AE38`), arbitraje de velocidad de recupero de capital (`GD46` vs. `GD41` vs. `AE38`) y arbitraje de frecuencia mensual vs. semestral frente al riesgo electoral (`AO29` vs. `AN29` vs. `AO28` vs. `AO27`), expuestos en [¿Tengo un Bono en USD favorito? (2025) Gus Lucioni](http://www.youtube.com/watch?v=ok2pA7OZer8), [Cartera de Cashflow ¿AE38 o GD46? (2026) Gus Lucioni](http://www.youtube.com/watch?v=wyUa64aHGcQ) y [¿AO29 o AN29? (2026) Gus Lucioni](http://www.youtube.com/watch?v=iI_l2kb973c).
5. **Arbitraje por Simulación de Sensibilidad Cruzada (Upside/Downside Asimétrico):** Selección algorítmica del bono con mayor relación beneficio/riesgo ante compresión hacia la tasa objetivo de *rollover* soberano ($7,5\%\text{–}9,0\%$) frente a la regresión hacia la TIR máxima de estrés histórico de cada serie (`AL41`, `GD41`, `GD46`, `AE38`, `BB37D`, `BA37D`, `PARP`, `TZX27`), detallada en [¿Se viene el Rebote? (2026) Gus Lucioni](http://www.youtube.com/watch?v=xbpulrQpAB4), [AE38 quedo Relegado Nuevamente (2025) Gus Lucioni](http://www.youtube.com/watch?v=Wuz2yBw8ECk) y [On de YPF + Simulación Globales y Bonos de PBA (2025) Gus Lucioni](http://www.youtube.com/watch?v=szbHhfNKLuw).
6. **Arbitraje Corporativo Intra-Grupo Empresario e Intra-Emisor en Obligaciones Negociables:** Captura de nominales a costo cero o incremento de TIR entre ONs del mismo grupo económico o emisor con idéntico mes de pago (`MR36O` de GEMSA vs. `LECH0` de Albanesi; `YMCJO` de YPF vs. `YFCJO` de YPF Luz; `YM39D` bullet vs. `YM34D` amortizable; `YM37D` vs. `AO27` y `OZC3O`), documentada en [¿Oportunidad? Pasar de MR36O a LECH0](https://mercapsoftware.com/oportunidad-pasar-de-mr36o-a-lech0/), [¿Oportunidad para rotar de YMCJO a YFCJO? (2025) Gus Lucioni](http://www.youtube.com/watch?v=1c7nQR6f3V4) y [ON de Cresud para Cashflow (2025) Gus Lucioni](http://www.youtube.com/watch?v=PT6FDlf28ro).
7. **Arbitraje de Valor Relativo entre Subsoberanos, Soberanos y BOPREAL (Factor de Capital Residual y Regalías):** Comparación de rendimiento operativo y paridad entre bonos provinciales garantizados o con bajo valor residual (`BNA6D`, `NDT25`, `NDG4D`, `BDC33`, `CO35`, `SJO5D`, `ERF25D`, `PUA36D`) frente a soberanos (`AL29D`, `AO27`) y BOPREAL (`BPY26`, `BPOC7`), así como la evaluación matemática de rechazo o aceptación de canjes voluntarios (`ERF25`), presentada en [Bonos de la Provincia de Neuquén (2025) Gus Lucioni](http://www.youtube.com/watch?v=M426ASSqlww), [Alternativas al BPY26 (2025) Gus Lucioni](http://www.youtube.com/watch?v=0bdFQ0eRES0) y [Canje en ERF25 (2026) Gus Lucioni](http://www.youtube.com/watch?v=KPtQ2ROAtyo).
8. **Arbitraje entre Tasas en Pesos (Tasa Fija / LECAPs vs. TAMAR / BADLAR vs. Duales TAMAR-CER):** Explotación de la opcionalidad implícita en bonos duales (`TXMD8`, `TXMJ8`/`TMJ8`) frente a flotantes puros (`PR17` BADLAR, `PBA27` TAMAR, `TML27`, `TMF27`) y tasa fija (`T30A7`, `T31Y7`, `S17A6`, `T13F6`), desarrollada en [Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM), [Los nuevos Bonos PBA 27 y 28 (2026) Gus Lucioni](http://www.youtube.com/watch?v=nQd8O7IoLxE) y [PR17 Alternativa en Pesos (2026) Gus Lucioni](http://www.youtube.com/watch?v=_oSDzanYRJk).
9. **Arbitraje Internacional y de Costo de Oportunidad Libre de Riesgo Local (ONs Tier-1 vs. US Treasuries `TLT` y Soberanos de Brasil `BR45`):** Desarme de posiciones corporativas locales cuando sus TIR comprimen por debajo de $5,0\%\text{–}6,0\%$ y rotación hacia `TLT`, `BR45` o liquidez hasta que las ONs Ley Nueva York (`VSCXO`, `PLC7D`, `MGCRD`, `IRCFO`) superen nuevamente el umbral del $7,0\%$ de TIR, según se expone en [¿Permanecer Líquido es Opción? (2026) Gus Lucioni](http://www.youtube.com/watch?v=Rh3t_OTUbwg), [Bonos del Tesoro (2026) Gus Lucioni](http://www.youtube.com/watch?v=25uYIk7URNs) y [VSCXO ¿Vale la pena ir tan largo? (2026) Gus Lucioni](http://www.youtube.com/watch?v=xC4tFjouZhU).
10. **Arbitraje Microestructural de Caja de Puntas, Dólar Implícito (MEP/CCL Ida y Vuelta), Conversión de Renta Cable y Ratio Merval/CER:** Ejecución sobre puntas reales (`Bid`/`Ask`) en lugar de último operado (`Last`), captura del canje Cable-MEP al cobrar cupones en especie 7000 y rotación macro entre bonos CER e índice Merval/acciones (`GGAL`), según se detalla en [¿Como saber si estoy pagando caro o barato?](http://www.youtube.com/watch?v=sUSsj5h9Nxw), [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) y [Copia de Arbitraje Ratios](https://docs.google.com/spreadsheets/d/13p_RLsTPMxfkBnbe7awyfw2cQGyAglh6O96Yhw0Y9dM/edit?usp=drivesdk&ouid=103928833983870106232).

| ID Familia | Categoría de Arbitraje | Activos / Pares Representativos | Métrica Primaria de Disparo | Horizonte Típico | Fuente Principal Verificada |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FAM-01** | Spread de Legislación (Ley NY vs. Ley ARG) | `GD30`/`AL30`, `GD38`/`AE38`, `GD41`/`AL41`, `GD35`/`AL35`, `GD29`/`AL29` | Ratio de precios vs. $MM_{21} \pm 1,5\sigma$ y $\Delta\text{TIR}$ | Intradiario a Swing (1–20 ruedas) | [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) / [Arbitraje Ratios](https://docs.google.com/spreadsheets/d/1W2kTK4n10-fKWYRJmoffOnxdaibkL-7I5wduSHVlGvI/edit?usp=drivesdk&ouid=103928833983870106232) |
| **FAM-02** | Desarbitraje Intra-Curva CER | `TX31`/`DICP`, `TZXS8`/`TZX28`, `TZXS7`/`TZXS8`, `TZXO7`/`TZXS7`, `DICP`/`DIP0` | $\Delta\text{TIR}$ ajustado por *Modified Duration* y paridad | Táctico ( días a semanas) | [¿TX31 o DICP?](http://www.youtube.com/watch?v=UtqZ3XpyJHE) / [¿TZXS8 o TZX28?](http://www.youtube.com/watch?v=NKLjxmYOK4Q) |
| **FAM-03** | Cross-Asset Soberano (CER vs. Hard Dollar) | `PARP`/`GD41`, `DICP`/`AE38`, `TX31`/`AL30` | Cruce $\text{TIR}_{\text{CER}} > \text{TIR}_{\text{HD}}$ o $\Delta\text{TIR} > 250\text{ bps}$ | Posicional (1 a 6 meses) | [Rotar de HD a CER](http://www.youtube.com/watch?v=GGXMEcxL7yY) / [¿Momento de rotar CER a USD?](http://www.youtube.com/watch?v=_GG5fkS0xi8) |
| **FAM-04** | Intra-Curva Hard Dollar (Flujo y Frecuencia) | `GD41`/`AE38`, `GD46`/`GD41`, `AO29`/`AN29`, `AO28`/`AO29` | Recupero de USD por lámina, cupón corriente y pago mensual | Táctico / Pre-corte de cupón | [¿Tengo un Bono en USD favorito?](http://www.youtube.com/watch?v=ok2pA7OZer8) / [¿AO29 o AN29?](http://www.youtube.com/watch?v=iI_l2kb973c) |
| **FAM-05** | Sensibilidad Cruzada y Asimetría de Curva | `AL41`, `GD41`, `GD46`, `AE38`, `BB37D`, `BA37D`, `PARP` vs. `TZX27` | Ratio $\frac{\text{Upside}(\text{TIR}_{\text{obj}})}{\text{Downside}(\text{TIR}_{\text{max}})}$ con TIR cruzada | Swing / Ciclo electoral | [¿Se viene el Rebote?](http://www.youtube.com/watch?v=xbpulrQpAB4) / [On de YPF + Simulación PBA](http://www.youtube.com/watch?v=szbHhfNKLuw) |
| **FAM-06** | Corporativo Intra-Grupo e Intra-Emisor (ONs) | `MR36O`/`LECH0`, `YMCJO`/`YFCJO`, `YM39D`/`YM34D`, `YM37D`/`AO27` | Ganancia de VN a costo cero o $\Delta\text{TIR} \ge 50\text{–}100\text{ bps}$ | Táctico / Cash-flow | [Pasar de MR36O a LECH0](https://mercapsoftware.com/oportunidad-pasar-de-mr36o-a-lech0/) / [Rotar de YMCJO a YFCJO](http://www.youtube.com/watch?v=1c7nQR6f3V4) |
| **FAM-07** | Subsoberanos vs. Soberanos y Residual | `BNA6D`, `NDT25`/`AL29D`, `ERF25D`, `CO35`, `BDC33`, `SJO5D`, `PUA36D` | Valor residual $< 55\%$, paridad $< 100\%$ y $\Delta\text{TIR}$ vs. Soberano | Mediano plazo / Eventos de canje | [Bonos de Neuquén](http://www.youtube.com/watch?v=M426ASSqlww) / [Canje en ERF25](http://www.youtube.com/watch?v=KPtQ2ROAtyo) |
| **FAM-08** | Tasas en Pesos (Tasa Fija vs. TAMAR vs. Dual) | `PBA27`/`T30A7`/`TML27`, `TXMD8`/`TXMJ8` vs. `PR17`, `T13F6`/`TZXM6` | Opcionalidad Dual gratuita ($\text{TIR}_{\text{Dual-TAMAR}} \ge \text{TIR}_{\text{BADLAR}}$) | Corto a mediano plazo | [Curva de Bonos duales](http://www.youtube.com/watch?v=W82Ml-x-axM) / [Nuevos Bonos PBA 27 y 28](http://www.youtube.com/watch?v=nQd8O7IoLxE) |
| **FAM-09** | Arbitraje Internacional / Umbral del 7% Cable | `VSCXO`, `PLC7D`, `MGCRD`, `IRCFO` vs. `TLT`, `BR45`, FCI USD | $\text{TIR}_{\text{ON Ley NY}} \ge 7,0\%$ vs. $\text{TIR}_{\text{ON}} \le \text{UST } 10\text{Y}$ | Posicional / Armado de renta | [¿Permanecer Líquido es Opción?](http://www.youtube.com/watch?v=Rh3t_OTUbwg) / [Cashflow USD Cable > 7%](http://www.youtube.com/watch?v=KoLLc-AHGG0) |
| **FAM-10** | Microestructura, MEP Ida/Vuelta y Canje Cable | Caja de puntas (`Bid`/`Ask`), `GD30`/`AL30`/`LEDE`, `Merval/CER` | TIR de punta vendedora, $\text{MEP}_{\text{Ida}} < \text{MEP}_{\text{Vuelta}}$, $\text{Canje CCL/MEP}$ | Intradiario / Ejecución inmediata | [¿Como saber si estoy pagando caro o barato?](http://www.youtube.com/watch?v=sUSsj5h9Nxw) / [Copia de Arbitraje Ratios](https://docs.google.com/spreadsheets/d/13p_RLsTPMxfkBnbe7awyfw2cQGyAglh6O96Yhw0Y9dM/edit?usp=drivesdk&ouid=103928833983870106232) |

## Universo de Instrumentos Más Usuales y Caracterización Operativa

Para que la aplicación de alertas procese correctamente las señales sin generar falsos positivos, su base de datos maestra de instrumentos (*security master*) debe parametrizar cada papel con los atributos exactos que determinan su comportamiento en los análisis del canal: moneda de emisión, moneda de pago (Dólar MEP especie 10.000 vs. Dólar Cable especie 7.000 vs. Pesos), legislación, tipo de indentura (*Indenture 2005* vs. *Indenture 2016*), modalidad de amortización (*bullet* vs. amortizable en cuotas), lámina mínima operable y meses de pago de renta.

### Bonos Soberanos en Dólares (Hard Dollar) y BOPREAL

El núcleo del trading de ratios y de las simulaciones de compresión de riesgo país se concentra en las series emitidas en la reestructuración de 2020 (Bonares bajo Ley Argentina y Globales bajo Ley Nueva York), complementadas por las nuevas emisiones del Tesoro con pago mensual (`AO27`, `AO28`, `AO29`, `AN29`) y los bonos del BCRA (`BPY26`, `BPOC7`, `BPOB7`).

| Ticker Base (ARS / MEP / Cable) | Legislación y Moneda de Pago | Estructura de Cupón y Amortización | Particularidades Críticas en el Algoritmo de Lucioni | Fuentes Verificadas |
| :--- | :--- | :--- | :--- | :--- |
| `AL29` / `AL29D` / `AL29C` | Ley Argentina (USD MEP) | Cupón 1,00% semestral (ene/jul); amortiza en cuotas desde 2025 hasta jul-2029 | Baja sensibilidad (*duration* corta); usado para arbitrar contra subsoberanos cortos como `NDT25` cuando cotiza con fuerte descuento respecto a `GD29` | [Bonos de la Provincia de Neuquén (2025)](http://www.youtube.com/watch?v=M426ASSqlww) |
| `GD29` / `GD29D` / `GD29C` | Ley Nueva York (USD Cable, Indenture 2016) | Cupón 1,00% semestral (ene/jul); idéntico flujo que `AL29` | Par de referencia para ratio `GD29/AL29`; menor potencial de suba ante compresión de TIR que el tramo largo | [GD41 ¿El Mejor de los Globales? (2025)](http://www.youtube.com/watch?v=8yXP9CoAPGE) |
| `AL30` / `AL30D` / `AL30C` | Ley Argentina (USD MEP) | Cupón 0,75% (sube a 1,75%); amortiza semestralmente hasta jul-2030 | Principal vehículo de liquidez local para dólar MEP y par central del arbitraje intradiario `GD30/AL30`; suele mostrar fortaleza relativa cuando hay demanda de MEP | [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) / [Arbitraje Ratios](https://docs.google.com/spreadsheets/d/1W2kTK4n10-fKWYRJmoffOnxdaibkL-7I5wduSHVlGvI/edit?usp=drivesdk&ouid=103928833983870106232) |
| `GD30` / `GD30D` / `GD30C` | Ley Nueva York (USD Cable, Indenture 2016) | Idéntico flujo y fechas de pago (ene/jul) que `AL30` | Referencia central de CCL y par de arbitraje intradiario contra `AL30` mediante Bandas de Bollinger ($MM_{21} \pm 1,5\sigma$) | [Arbitraje Ratios](https://docs.google.com/spreadsheets/d/1W2kTK4n10-fKWYRJmoffOnxdaibkL-7I5wduSHVlGvI/edit?usp=drivesdk&ouid=103928833983870106232) |
| `AL35` / `AL35D` / `GD35` / `GD35D` | Ley ARG (`AL35`) / Ley NY (`GD35`, Indenture 2016) | Cupón bajo (4,125% / 4,75%); empieza a devolver capital recién en 2031 hasta 2035 | Lucioni los descarta para carteras de *cash-flow* por su bajo cupón corriente (<2,5% semestral sobre paridad) y lejano inicio de amortización, pero opera su ratio de legislación | [¿Tengo un Bono en USD favorito? (2025)](http://www.youtube.com/watch?v=ok2pA7OZer8) / [¿TX31 o DICP? (2026)](http://www.youtube.com/watch?v=UtqZ3XpyJHE) |
| `AE38` / `AE38D` / `AE38C` | Ley Argentina (USD MEP, ex-DICA) | Cupón alto (5,00% anual); amortiza en 22 cuotas de 4,54% desde jul-2027 hasta ene-2038 | Uno de los dos favoritos de Lucioni junto a `GD41`: ofrece el menor *downside* en escenarios bajistas, mayor cupón corriente y amortiza 6 meses antes que el 41 | [¿Tengo un Bono en USD favorito? (2025)](http://www.youtube.com/watch?v=ok2pA7OZer8) / [AE38 quedo Relegado Nuevamente (2025)](http://www.youtube.com/watch?v=Wuz2yBw8ECk) |
| `GD38` / `GD38D` / `GD38C` | Ley Nueva York (USD Cable, **Indenture 2005**) | Idéntico flujo que `AE38` (cupón 5,00%, amortiza desde jul-2027) | Cuenta con protección legal reforzada (*Indenture 2005*); suele cotizar caro respecto a `AE38` (hasta 200–400 bps menos de TIR), habilitando rotaciones hacia `AE38` cuando el ratio supera 1,03 | [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) / [¿TX31 o DICP? (2026)](http://www.youtube.com/watch?v=UtqZ3XpyJHE) |
| `AL41` / `AL41D` / `GD41` / `GD41D` | Ley ARG (`AL41`) / Ley NY (`GD41`, **Indenture 2005**) | Cupón 3,50% anual ( subiendo a 4,875%); amortiza en 28 cuotas de 3,57% desde ene-2028 | Mayor *upside* de toda la curva en simulaciones de compresión hacia 7%–10% de TIR; `GD41` combina máxima convexidad con protección *Indenture 2005* | [GD41 ¿El Mejor de los Globales? (2025)](http://www.youtube.com/watch?v=8yXP9CoAPGE) / [Bonos Hard Dólar: ¿Cuáles tienen mayor Potencial de Suba?](http://www.youtube.com/watch?v=RpRWXd7hXXo) |
| `GD46` / `GD46D` / `GD46C` | Ley Nueva York (USD Cable, Indenture 2016) | Sin par ley local; ya amortiza cuotas semestrales de 2,27% desde 2025 (paga ~USD 8/año por lámina) | Emisión pequeña e ilíquida; compite con `GD41` en *upside* cuando queda rezagado y con `AE38` en flujo continuo por estar ya devolviendo capital | [Cartera de Cashflow ¿AE38 o GD46? (2026)](http://www.youtube.com/watch?v=wyUa64aHGcQ) / [¿Se viene el Rebote? (2026)](http://www.youtube.com/watch?v=xbpulrQpAB4) |
| `AO27` / `AO28` / `AO29` | Ley Argentina (USD MEP) | Cupón del 5,0% al 6,0% anual con **pago mensual** (0,5% mensual en `AO29`); amortización *bullet* en octubre de 2027, 2028 y 2029 | `AO27` carece de riesgo electoral presidencial (vence oct-2027); `AO28` y `AO29` asumen riesgo electoral, por lo que `AO29` domina a `AO28` y `AN29` gracias a su flujo mensual | [¿AO29 o AN29? (2026)](http://www.youtube.com/watch?v=iI_l2kb973c) / [AO29 nuevo Bono soberano en USD con renta mensual](http://www.youtube.com/watch?v=3rScqsNVfT4) |
| `AN29` / `AN29D` | Ley Argentina (USD MEP) | Cupón 6,5% anual con **pago semestral** (mayo/noviembre); vence nov-2029 | Rinde apenas por encima de `AO29`, pero pierde en el arbitraje de flujo porque recién paga en mayo y noviembre frente al cobro mensual de `AO29` | [¿AO29 o AN29? (2026)](http://www.youtube.com/watch?v=iI_l2kb973c) |
| `BPY26` / `BPOC7` / `BPOB7` | BCRA (USD MEP / Canje) | BOPREAL Serie 3 (`BPY26` vence mayo 2026) y Serie 1 (`BPOC7`, `BPOB7` vencen oct-2027) | Baja volatilidad y lámina mínima de 100 VN; cuando `BPY26` comprime su TIR a niveles mínimos, se arbitra hacia ONs cortas de YPF (`YM37D`) o subsoberanos cortos (`BNA6D`) | [Alternativas al BPY26 (2025)](http://www.youtube.com/watch?v=0bdFQ0eRES0) / [Bopreal BPOC7 se suma a la cartera](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1824503750836103219) |

### Bonos Soberanos en Pesos (Curva CER, Tasa Fija, TAMAR, BADLAR y Duales)

En el segmento en moneda local, el benchmark explícito que define [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni) en [PLC7D arriba de 7% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=J2CDL8nu9fs) es la inflación (coeficiente CER), utilizando los títulos a tasa fija o TAMAR únicamente en ventanas tácticas de apreciación o estabilidad cambiaria preelectoral.

| Ticker | Cláusula de Ajuste | Vencimiento y Estructura de Flujo | Rol Operativo y Regla de Arbitraje | Fuentes Verificadas |
| :--- | :--- | :--- | :--- | :--- |
| `DICP` / `DIP0` | CER (Inflación) | Vencen 31/12/2033; cupón 5,83% anual (jun/dic) + amortización semestral de 5% del capital | Ambos tienen exactamente el mismo flujo de fondos; `DIP0` rinde ~100 bps más de TIR pero es altamente ilíquido. `DICP` es el eje de rotación contra `TX31` y contra `AE38` | [Sumamos Bonos en pesos a la Cartera de Cashflow (2025)](http://www.youtube.com/watch?v=CzfEpVxJ0_E) / [¿TX31 o DICP? (2026)](http://www.youtube.com/watch?v=UtqZ3XpyJHE) |
| `TX31` | CER (Inflación) | Vence nov-2031; cupón 2,5% anual (may/nov) + amortización en 10 cuotas semestrales del 10% desde mayo-2027 | Menor *duration* ($MD \approx 2,62$) que `DICP` ($MD \approx 3,08$). Si $\text{TIR}_{\text{TX31}} > \text{TIR}_{\text{DICP}}$, existe desarbitraje a favor de `TX31`; si sus TIR se igualan, se rota 50% a `DICP` | [¿TX31 o DICP? (2026)](http://www.youtube.com/watch?v=UtqZ3XpyJHE) / [PLC7D arriba de 7% de TIR (2026)](http://www.youtube.com/watch?v=J2CDL8nu9fs) |
| `PARP` / `CUAP` | CER (Inflación) | Vencen en 2038 (`PARP`) y 2041 (`CUAP`); baja tasa de cupón y alta convexidad | Instrumentos de máxima sensibilidad para capturar compresión de tasa real desde $>11\%\text{–}12\%$ hacia $6\%\text{–}7,5\%$ de TIR; se arbitran contra `GD41` y contra CER cortos (`TZX27`) | [PARP abajo de 8% de TIR (2026)](http://www.youtube.com/watch?v=KTQlxbVUPJI) / [ON de Cresud para Cashflow (2025)](http://www.youtube.com/watch?v=PT6FDlf28ro) |
| `TZX28` / `TZXS8` / `TZXM9` | CER (Cupón Cero) | Vencen 30/06/2028 (`TZX28`), 30/09/2028 (`TZXS8`) y 31/03/2029 (`TZXM9`); sin riesgo de reinversión | Eje de arbitraje de tramo medio CER: `TZXS8` vs. `TZX28` (3 meses de diferencia, umbral de 100 bps de spread para comprar `TZXS8` y 25 bps para volver a `TZX28`) y `TZXM9` cuando supera 9%–10% de TIR | [¿TZXS8 o TZX28? (2026)](http://www.youtube.com/watch?v=NKLjxmYOK4Q) / [Nuevo Bono de Chubut (2026)](http://www.youtube.com/watch?v=-PXxoj8HZFU) / [TZXM9 arriba de 9% de TIR](http://www.youtube.com/watch?v=6b-217uVgoM) |
| `TZXM7` / `TZXA7` / `TZX27` / `TZXS7` / `TZXO7` | CER (Cupón Cero) | Vencen entre marzo y octubre de 2027 (antes o sobre las elecciones presidenciales) | Arbitraje de prima electoral (`TZXS7` vs. `TZXS8` y `TZXO7` vs. `TZXS7`); si rinden $< 2,5\%\text{–}2,8\%$ real, pierden contra Plazo Fijo UVA por impacto de comisiones | [Nuevo Bono TZXO7 (2026)](http://www.youtube.com/watch?v=xjvXqUOxTLM) / [YM37D ¿Oportunidad Conservadora?](http://www.youtube.com/watch?v=Nbksr1IE7pU) |
| `TX26` / `TX28` | CER (Amortizables) | Amortizables de tramo corto-medio | Operados por ratio de precios intradiario/swing (`TX26/TX28`) en la planilla de ratios para capturar flujo de salida institucional | [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) |
| `PR17` | BADLAR + 0 bps | Bono de Consolidación que capitalizó intereses hasta 2026 y desde mayo-2026 paga 7% de capital + BADLAR/4 trimestral hasta 2029 | Recupera capital en ~8 cuotas si se sostiene la tasa flotante; se arbitra contra bonos Duales TAMAR/CER (`TXMD8`, `TXMJ8`) cuando el Dual rinde igual o más en versión TAMAR | [PR17 Alternativa en Pesos (2026)](http://www.youtube.com/watch?v=_oSDzanYRJk) / [Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM) |
| `TXMD8` / `TXMJ8` (`TMJ8`) | Dual (Máximo entre CER y TAMAR) | Bonos Duales del Tesoro con vencimiento en 2028 | Se evalúan simultáneamente en la curva CER-Dual y en la curva TAMAR-Dual; si su TIR TAMAR iguala a un TAMAR/BADLAR puro, la cobertura CER resulta gratuita | [Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM) / [TIR de la cartera de Bonos CER y TAMAR/TASA FIJA](http://www.youtube.com/watch?v=19qYECYckp0) |
| `T30A7` / `T31Y7` / `S17A6` / `TML27` / `TMF27` | Tasa Fija y TAMAR Soberanos | Vencimientos cortos en 2026 y abril/julio de 2027 | Se comparan contra `PBA27` (TAMAR provincial) y contra la inflación implícita (*breakeven*) de los CER de igual vencimiento (`TZXA7`, `TZXM7`) | [Opciones en Pesos y en USD de Corto Plazo (2026)](http://www.youtube.com/watch?v=YAnMRRLCleE) / [Los nuevos Bonos PBA 27 y 28](http://www.youtube.com/watch?v=nQd8O7IoLxE) |

### Títulos Subsoberanos (Provinciales) y Obligaciones Negociables Corporativas

El universo corporativo y provincial constituye la base de las carteras de *cash-flow* mensual en dólares (MEP y Cable) y de las rotaciones tácticas por calificación crediticia, flujo y lámina mínima.

| Ticker | Emisor y Tipo | Ley, Moneda y Lámina Mínima | Cupón, Vencimiento y Amortización | Lógica de Selección y Arbitraje en el Sistema | Fuentes Verificadas |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `BDC33` | Ciudad Autónoma de Buenos Aires (Subsoberano) | Ley NY, USD Cable, Mínimo 1.000 VN | Cupón 7,80% TNA; amortiza en 3 cuotas anuales (2031, 2032, 2033) | Considerado el activo más seguro del mercado argentino (CABA jamás reestructuró su deuda); compra bajo 101%–102% de paridad (TIR $\ge 7,1\%\text{–}7,5\%$), frena compra si TIR cae debajo de $7,0\%$ (paridad $\ge 105\%$) | [Cashflow mensual en USD Cable arriba del 7% Anual](http://www.youtube.com/watch?v=KoLLc-AHGG0) / [VSCXO ¿Vale la pena ir tan largo?](http://www.youtube.com/watch?v=xC4tFjouZhU) |
| `BNA26` / `BNA6D` | Provincia de Neuquén (Subsoberano) | Ley ARG/NY, USD, Mínimo 1.000 VN | Amortiza trimestralmente cuotas del 25% hasta abril de 2026; garantizado por regalías petroleras | Bajo valor residual ($50\%$ o menos) y garantía hidrocarburífera; pero requiere control estricto de punta vendedora (`Ask` $\le \text{USD } 50,75\text{–}50,80$ para asegurar $\text{TIR} \ge 7\%$) por alto spread *bid-ask* | [Bonos de la Provincia de Neuquén (2025)](http://www.youtube.com/watch?v=M426ASSqlww) / [Alternativas al BPY26 (2025)](http://www.youtube.com/watch?v=0bdFQ0eRES0) |
| `NDT25` / `NDT5D` | Provincia de Neuquén (Subsoberano) | Ley NY, USD Cable, Mínimo 1.000 VN | Cupón 6,88% TNA (abr/oct); amortiza en cuotas del 7,69% semestral hasta abril-2030 | Atractivo cuando rinde $> 8,0\%$ (dic-2025); cuando comprime a $5,4\%\text{–}6,0\%$ queda caro frente al soberano `AL29D` para igual horizonte 2029–2030 | [Bonos de la Provincia de Neuquén (2025)](http://www.youtube.com/watch?v=M426ASSqlww) / [Agregamos dos nuevos bonos a la Cartera](http://www.youtube.com/watch?v=fys2jlXdSf4) |
| `NDG4D` | Provincia de Neuquén (Subsoberano) | Ley NY, USD Cable, Mínimo 1.000 VN | Cupón 7,35% TNA; amortiza en 3 cuotas del 33,3% hasta 2034 | Alternativa larga en USD Cable con lámina accesible (1.000 VN) cuando rinde $\ge 7,3\%\text{–}7,6\%$ de TIR | [Cashflow mensual en USD Cable arriba del 7% Anual](http://www.youtube.com/watch?v=KoLLc-AHGG0) / [PLC7D arriba de 7% de TIR](http://www.youtube.com/watch?v=J2CDL8nu9fs) |
| `CO35` / `CO35D` | Provincia de Córdoba (Subsoberano) | Ley NY, USD Cable, **Mínimo 10.000 VN** | Cupón 8,60% TNA semestral (feb/ago); amortiza en 3 cuotas hasta ago-2035 | Percibido como seguro porque `CO26` nunca se reestructuró; caro en 104%–106% de paridad, oportunidad de entrada cuando corrige bajo la par ($96\%\text{–}97\%$, TIR $\approx 9,0\%$), restringido por su lámina de ~USD 9.800 | [YM37D ¿Oportunidad Conservadora? (2026)](http://www.youtube.com/watch?v=Nbksr1IE7pU) / [VSCXO ¿Vale la pena ir tan largo?](http://www.youtube.com/watch?v=xC4tFjouZhU) |
| `SJO5D` / `SJ35` | Provincia de San Juan (Subsoberano) | Ley NY, USD Cable, Mínimo 1.000 VN | Cupón 9,55% TNA (4,85% semestral); emisión chica (USD 600M), amortiza en 3 cuotas (2033, 2034, 2035) | Supera a `CO35` y al nuevo Entre Ríos para inversores minoristas por su alto cupón (9,55%), TIR de 9,4% y lámina mínima de 1.000 VN en vez de 10.000 VN | [Tenemos un nuevo sub soberano. Cupón del 9.55% anual en USD y ley Ny](http://www.youtube.com/watch?v=FsOv7TBEAh0) |
| `ERF25` / `ERF25D` | Provincia de Entre Ríos (Subsoberano) | Ley NY, USD Cable | Paga en febrero y agosto; vence ago-2028; ya amortizó 46% del capital (residual 54%) | Regla de rechazo de canje voluntario a 2034: al quedar solo 54% de capital residual, el riesgo de default baja y no conviene extender *duration* 6 años | [Sumamos dos Nuevos Bonos a la Cartera (2025)](http://www.youtube.com/watch?v=ek111LGCrh8) / [Canje en ERF25 (2026)](http://www.youtube.com/watch?v=KPtQ2ROAtyo) |
| `BB37D` / `BA37D` | Provincia de Buenos Aires (Subsoberano USD) | Ley NY, USD Cable (`BB37D` posee **Indenture 2005**) | Vencen en 2037; alta sensibilidad | `BB37D` gana en la simulación de TIR cruzada (12% PBA vs. 10% Soberanos) para mantener a mediano plazo, pero su baja liquidez en caja de puntas impide usarlo para trading intradiario de ratios | [On de YPF + Simulación Globales y Bonos de PBA (2025)](http://www.youtube.com/watch?v=szbHhfNKLuw) |
| `PBA27` / `PBA28` | Provincia de Buenos Aires (Subsoberano ARS) | Ley ARG, Pesos | `PBA27` (vence 30/04/2027, TAMAR + 733 bps, TNA ~31,37%); `PBA28` (vence 28/04/2028, CER, TIR ~10%–11%) | `PBA27` arbitra con ventaja de +600 bps sobre los TAMAR del Tesoro (`TML27`, `TMF27`) antes de las elecciones; `PBA28` es descartado frente a `TZX28`/`TZXM9` porque vence en abril-2028 sin dar tiempo suficiente al *pass-through* postelectoral | [Los nuevos Bonos PBA 27 y 28 (2026)](http://www.youtube.com/watch?v=nQd8O7IoLxE) / [Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM) |
| `PUA36` / `PUA36D` | Provincia de Chubut (Subsoberano) | Ley NY, USD Cable, Mínimo 1.000 VN | Cupón 9,45% TNA con pago trimestral; amortiza desde 2029 hasta abr-2036 | Flujo trimestral excelente, pero bloqueado para compra mientras cotice con paridad de 108% (regla de esperar paridad $< 100\%$) | [Nuevo Bono de Chubut (2026)](http://www.youtube.com/watch?v=-PXxoj8HZFU) |
| `YMCJO` / `YMCJD` vs. `YFCJO` | YPF S.A. vs. YPF Luz (ONs Corporativas) | Ley NY, USD Cable | Pagan ambas a fines de marzo y septiembre (acreditación en abril y octubre); `YFCJO` tiene cupón 7,875% | Arbitraje directo de rotación de `YMCJO` hacia `YFCJO` cuando `YFCJO` ofrece +50 a +100 bps de TIR sobre el mismo mes de flujo y riesgo grupo YPF | [¿Oportunidad para rotar de YMCJO a YFCJO? (2025)](http://www.youtube.com/watch?v=1c7nQR6f3V4) |
| `YM39D` vs. `YM34D` vs. `YM42D` vs. `YM37D` | YPF S.A. (ONs Corporativas) | Ley NY (`YM39D`, `YM34D`) y Ley ARG (`YM37D`, `YM42D`) | `YM39D` (vence jul-2030, bullet, cupón 8,75%, ene/jul); `YM34D` (vence 2034 en 3 cuotas, ene/jul); `YM42D` (vence 2029, jun/dic); `YM37D` (vence 07/05/2027, cupón 7% trimestral) | `YM39D` domina a `YM34D` a igual TIR por ser más corta, bullet y de mayor cupón; `YM37D` (TIR 6,37%) domina a `AO27` (TIR 2,9%) como dolarización conservadora preelectoral | [ON de Cresud para Cashflow (2025)](http://www.youtube.com/watch?v=PT6FDlf28ro) / [YM37D ¿Oportunidad Conservadora? (2026)](http://www.youtube.com/watch?v=Nbksr1IE7pU) / [Sumamos dos Nuevos Bonos a la Cartera](http://www.youtube.com/watch?v=ek111LGCrh8) |
| `MR36O` vs. `LECH0` | GEMSA vs. Albanesi (Grupo Albanesi) | Ley ARG (Dólar Linked / Hard Dollar) | Idéntico cronograma de pagos dentro del mismo grupo económico | Arbitraje de gemelos corporativos: vender la más cara (`MR36O`) y comprar la más barata (`LECH0`) para sumar nominales gratis; posterior reestructuración de GEMSA sirve como caso de alerta de riesgo crediticio | [¿Oportunidad? Pasar de MR36O a LECH0](https://mercapsoftware.com/oportunidad-pasar-de-mr36o-a-lech0/) / [Canje en ERF25 (2026)](http://www.youtube.com/watch?v=KPtQ2ROAtyo) |
| `VSCXO` | Vista Energy (ON Corporativa) | Ley NY, USD Cable, Mínimo 1.000 VN | Cupón 7,875% TNA (abr/oct); vence en 2038 amortizando en 3 cuotas desde 2036 ($MD \approx 6,85$) | ON larga de alta calidad de management; alerta de compra cuando corrige de 108% a $\le 101\%\text{–}102\%$ de paridad superando $7,5\%\text{–}7,8\%$ de TIR | [VSCXO ¿Vale la pena ir tan largo? (2026)](http://www.youtube.com/watch?v=xC4tFjouZhU) / [Cashflow mensual en USD Cable arriba del 7% Anual](http://www.youtube.com/watch?v=KoLLc-AHGG0) |
| `PLC7D` / `PLC7O` | Pluspetrol (ON Corporativa) | Ley NY, USD Cable, Mínimo 1.000 VN | Emisiones 2031 (bullet, cupón 8,15%) y 2037 (3 cuotas, cupón 7,55%, paga mar/sep) | Sustituto ideal de `MGCRD` (Pampa) para carteras menores porque exige 1.000 VN en lugar de 10.000 VN y ofrece TIR $> 7,0\%$ con calidad crediticia Tier-1 | [PLC7D arriba de 7% de TIR (2026)](http://www.youtube.com/watch?v=J2CDL8nu9fs) / [VSCXO ¿Vale la pena ir tan largo?](http://www.youtube.com/watch?v=xC4tFjouZhU) |
| `MGCRD` | Pampa Energía (ON Corporativa) | Ley NY, USD Cable, **Mínimo 10.000 VN** | Cupón 7,88% TNA; vence en 2037 | Compra cuando corrige de 107%–110% de paridad a $\le 99\%\text{–}102\%$ con TIR $\ge 7,6\%\text{–}8,0\%$ | [Cashflow mensual en USD Cable arriba del 7% Anual](http://www.youtube.com/watch?v=KoLLc-AHGG0) / [VSCXO ¿Vale la pena ir tan largo?](http://www.youtube.com/watch?v=xC4tFjouZhU) |
| `IRCOO` / `IRCFO` & `CS38O` / `CS44O` | IRSA y Cresud (Grupo IRSA) | Ley ARG / Ley NY, USD | `IRCOO` (vence 2029, bullet, cupón 7,25%, ene/jul); `IRCFO` (vence 2035, 3 cuotas, cupón 8%); Cresud (vence 2028, bullet, cupón 7%, **paga may/nov**) | Combinación complementaria para *cash-flow*: Cresud cubre los meses difíciles de mayo y noviembre mientras IRSA cubre enero y julio con bajo riesgo corporativo | [ON de Cresud para Cashflow (2025)](http://www.youtube.com/watch?v=PT6FDlf28ro) / [Cashflow Mensual ¿Volvimos? (2025)](http://www.youtube.com/watch?v=W5VDd02Q00c) |
| `OZC3O` / `OZCD` | EDESa (Empresa Distribuidora de Electricidad de Salta) | Ley ARG, USD MEP | Cupón 8,0%–8,5% TNA; vence feb/nov 2027 (antes del recambio presidencial) | Alerta de entrada cuando es castigada a 12% de TIR; toma de ganancia o espera paciente cuando comprime a 6,0%–6,6% de TIR | [TZXM9 arriba de 9% de TIR (2026)](http://www.youtube.com/watch?v=6b-217uVgoM) / [¿AO29 o AN29? (2026)](http://www.youtube.com/watch?v=iI_l2kb973c) |
| `SNS9O` | San Miguel (SAMI) | Ley ARG, USD | Cupón 9,0% TNA; alta TIR (>13%) por estrés de balance en 2018–2023 | Oportunidad especulativa de alto riesgo distinguida de GEMSA/Celulosa por la "voluntad de pago" (recompra de deuda propia y aportes de accionistas), limitada a una fracción marginal de cartera | [On de Sami ¿Oportunidad o alto Riesgo? (2025)](http://www.youtube.com/watch?v=wQGXzZaaOnM) / [¿Oportunidad para rotar de YMCJO a YFCJO?](http://www.youtube.com/watch?v=1c7nQR6f3V4) |

## Desarrollo Matemático y Lógica Algorítmica de Cada Estrategia de Arbitraje

A continuación se formaliza la lógica exacta de cada estrategia detectada en el canal de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni), especificando las ecuaciones matemáticas, las variables de entrada, las condiciones de disparo (*triggers*) y las restricciones operativas que el motor de inteligencia artificial debe implementar.

### Estrategia 1: Arbitraje Estadístico de Legislación en Soberanos Hard Dollar (Bandas de Bollinger sobre Puntas Operables y Spread de TIR)

El arbitraje entre bonos Globales (Ley Nueva York: `GD29`, `GD30`, `GD35`, `GD38`, `GD41`) y Bonares (Ley Argentina: `AL29`, `AL30`, `AL35`, `AE38`, `AL41`) parte de una identidad contractual fundamental: para cada par del mismo año de vencimiento, el cronograma de pagos de intereses y amortización de capital es exactamente idéntico hasta el centavo, diferenciándose únicamente en el tribunal competente ante un eventual litigio y en la moneda de liquidación (Dólar Cable especie 7.000 para `GD` vs. Dólar MEP especie 10.000 para `AL`/`AE`).

En los videos [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) y [¿TX31 o DICP? (2026) Gus Lucioni](http://www.youtube.com/watch?v=UtqZ3XpyJHE), así como en las planillas [Arbitraje Ratios](https://docs.google.com/spreadsheets/d/1W2kTK4n10-fKWYRJmoffOnxdaibkL-7I5wduSHVlGvI/edit?usp=drivesdk&ouid=103928833983870106232) y [Copia de Arbitraje Ratios](https://docs.google.com/spreadsheets/d/13p_RLsTPMxfkBnbe7awyfw2cQGyAglh6O96Yhw0Y9dM/edit?usp=drivesdk&ouid=103928833983870106232), esta estrategia se ejecuta bajo dos modalidades complementarias: **Trading de Ratios de Precio** (intradiario o *swing* para cuentas con comisión *flat* o bonificada) y **Arbitraje Posicional por Spread de TIR**.

#### Modalidad 1A: Trading de Ratio de Precios con Bandas de Bollinger sobre Puntas Vigentes

En la planilla [Arbitraje Ratios](https://docs.google.com/spreadsheets/d/1W2kTK4n10-fKWYRJmoffOnxdaibkL-7I5wduSHVlGvI/edit?usp=drivesdk&ouid=103928833983870106232), el ratio porcentual de legislación $R_t$ se define como la prima porcentual de precio en pesos (o en dólares) del título Ley Nueva York sobre el título Ley Argentina en el mismo plazo de liquidación:

$$R_t = \left( \frac{P_{\text{GD}, t}}{P_{\text{AL}, t}} - 1 \right) \times 100$$

Sin embargo, para evitar señales ilusorias producto del desfasaje en el último precio operado (`Last`), la hoja `Intraday` de [Copia de Arbitraje Ratios](https://docs.google.com/spreadsheets/d/13p_RLsTPMxfkBnbe7awyfw2cQGyAglh6O96Yhw0Y9dM/edit?usp=drivesdk&ouid=103928833983870106232) calcula dos ratios ejecutables en tiempo real cada 10 segundos utilizando las puntas compradora (`Bid`) y vendedora (`Ask`) de la caja de puntas:

1. **Ratio ejecutable para rotar de GD hacia AL ($R_{\text{GD}\to\text{AL}}$):** Se vende `GD` al precio comprador (`Bid`) y se compra `AL` al precio vendedor (`Ask`):
   $$R_{\text{GD}\to\text{AL}} = \left( \frac{\text{Bid}_{\text{GD}}}{\text{Ask}_{\text{AL}}} - 1 \right) \times 100$$
2. **Ratio ejecutable para rotar de AL hacia GD ($R_{\text{AL}\to\text{GD}}$):** Se vende `AL` al precio comprador (`Bid`) y se compra `GD` al precio vendedor (`Ask`):
   $$R_{\text{AL}\to\text{GD}} = \left( \frac{\text{Ask}_{\text{GD}}}{\text{Bid}_{\text{AL}}} - 1 \right) \times 100$$

Sobre la serie histórica de cierres diarios (ventana de $N = 21$ ruedas para *swing trading*, complementada con media rápida $MM_9$ y estadísticas de 5, 20, 60 y 100 ruedas) o sobre la serie intradiaria (ventana de $N = 180$ muestras en `MM180`), el sistema calcula la media móvil simple $\mu_N$ y la desviación estándar muestral $\sigma_N$, construyendo Bandas de Bollinger con factor $k = 1,5$:

$$\text{Banda Superior} = \mu_{21} + 1,5 \cdot \sigma_{21}$$

$$\text{Banda Inferior} = \mu_{21} - 1,5 \cdot \sigma_{21}$$

Las reglas de disparo del tacómetro de arbitraje son:

* **Alerta de Rotación `GD` $\to$ `AL` (Incremento de Nominales):** Se dispara cuando $R_{\text{GD}\to\text{AL}} \ge \text{Banda Superior}$ (o en el caso del par `GD38`/`AE38` citado en [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc), cuando el cociente $\frac{P_{\text{GD38}}}{P_{\text{AE38}}} \ge 1,03$, o en `GD41`/`AL41` cuando alcanza el máximo del rango reciente en $\approx 1,02$). Al ejecutar la rotación vendiendo $Q_{\text{GD}}$ nominales y comprando `AL`, el inversor obtiene una cantidad superior de nominales $Q_{\text{AL}} = Q_{\text{GD}} \cdot (1 + R_{\text{GD}\to\text{AL}} - C_{\text{total}})$, donde $C_{\text{total}}$ representa los costos transaccionales de ida y vuelta.
* **Alerta de Rotación `AL` $\to$ `GD` (Upgrade de Protección Legal y Dólar Cable):** Se dispara cuando $R_{\text{AL}\to\text{GD}} \le \text{Banda Inferior}$. Asimismo, en [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc), Lucioni advierte una **divergencia inter-pares**: cuando los tramos largos (`GD41/AL41`, `GD38/AE38`) se encuentran en el techo de su ratio (apreciándose la Ley NY) pero simultáneamente el ratio corto `GD30/AL30` cae a su piso relativo por presión compradora local sobre `AL30`, se habilita el pase táctico de `AL30` hacia `GD30` a contramarcha del resto de la curva.

#### Modalidad 1B: Arbitraje Posicional por Spread de TIR entre Ley Local y Ley Extranjera

En [¿TX31 o DICP? (2026) Gus Lucioni](http://www.youtube.com/watch?v=UtqZ3XpyJHE) y en el reporte [Bonos en baja: ¿hay desarbitraje entre TX31 y DICP, y oportunidad en la brecha ley local-extranjera?](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1878047353635792822), el criterio para carteras que no hacen *day trading* sino posicionamiento de mediano plazo se formula sobre el diferencial de TIR:

$$\Delta\text{TIR}_{\text{Ley}} = \text{TIR}_{\text{Ley ARG}} - \text{TIR}_{\text{Ley NY}}$$

* **Condición de Bloqueo de Ley Local (Regla de Paridad de Rendimiento):** Si $\Delta\text{TIR}_{\text{Ley}} \le 50\text{ bps}$ (como ocurrió durante meses en el par `GD35` vs. `AL35`, donde ambos rendían prácticamente lo mismo), **queda prohibido comprar o mantener el título Ley Argentina**. El motor debe emitir una alerta de **Migración Gratuita a Ley Extranjera (`AL` $\to$ `GD`)**, dado que el inversor obtiene cobertura en tribunales de Nueva York y cobro de cupones en Dólar Cable sin resignar rendimiento.
* **Condición de Sobreponderación de Ley Local por Ampliación de Spread:** Cuando una corrección de mercado amplía el spread a $\Delta\text{TIR}_{\text{Ley}} \ge 160\text{ a }200\text{ bps}$ en condiciones normales (por ejemplo, `AL35` rindiendo $+162\text{ bps}$ sobre `GD35`, o `AE38` rindiendo $+200\text{ bps}$ sobre `GD38` con precios de ARS 113.000 vs. ARS 123.000) o hasta $+350\text{ a }+400\text{ bps}$ en estrés preelectoral, se activa la alerta de **Valor Relativo a favor de Ley Local (`GD38` $\to$ `AE38`)**, fundamentada en que jamás en la historia argentina se reestructuró un bono Ley Local dejando *performing* a su gemelo Ley Extranjera.

### Estrategia 2: Arbitraje Intra-Curva CER (Inversión de Pendiente, Spread de Cupón Cero y Ventana de Pass-Through)

La curva de bonos en pesos ajustados por CER constituye el terreno donde [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni) ejecuta la mayor frecuencia de rotaciones fundamentales y tácticas. Un motor de alertas debe implementar cuatro detectores específicos dentro de esta familia.

#### Detector 2A: Arbitraje de Pendiente y Duration entre `TX31` y `DICP`

Expuesto en detalle en [¿TX31 o DICP? (2026) Gus Lucioni](http://www.youtube.com/watch?v=UtqZ3XpyJHE), [On de Sami ¿Oportunidad o alto Riesgo? (2025) Gus Lucioni](http://www.youtube.com/watch?v=wQGXzZaaOnM) y [PLC7D arriba de 7% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=J2CDL8nu9fs), este arbitraje compara dos bonos CER amortizables de tramo medio-largo con características estructurales asimétricas:

* **`TX31`:** Vence en noviembre de 2031, posee una *Duration* de $2,62$ años (y menor *Modified Duration*), paga un cupón del $2,50\%$ TNA semestral (mayo y noviembre) y comienza a amortizar capital en cuotas del $10\%$ semestral a partir del 31 de mayo de 2027.
* **`DICP`:** Vence el 31 de diciembre de 2033, posee una *Duration* de $3,08$ años, paga un cupón sustancialmente mayor del $5,83\%$ TNA semestral (junio y diciembre) y ya se encuentra amortizando cuotas semestrales del $5\%$ de capital.

En una curva normal con pendiente positiva por plazo y riesgo de duración, dado que $MD_{\text{TX31}} < MD_{\text{DICP}}$ y $\text{Maturity}_{\text{TX31}} < \text{Maturity}_{\text{DICP}}$, debe cumplirse que $\text{TIR}_{\text{TX31}} \le \text{TIR}_{\text{DICP}}$. El algoritmo evalúa el diferencial:

$$\Delta\text{TIR}_{\text{CER- Medio}} = \text{TIR}_{\text{TX31}} - \text{TIR}_{\text{DICP}}$$

1. **Disparo de Rotación `DICP` $\to$ `TX31` (Captura de Desarbitraje de Tasa y Reducción de Duration):** Si $\Delta\text{TIR}_{\text{CER-Medio}} \ge +60\text{ a }+100\text{ bps}$ (como el registro de $\text{TIR}_{\text{TX31}} = 11,32\%$ vs. $\text{TIR}_{\text{DICP}} = 10,67\%$ en [¿TX31 o DICP? (2026) Gus Lucioni](http://www.youtube.com/watch?v=UtqZ3XpyJHE)), existe una anomalía financiera: el bono más corto y menos volátil rinde más que el bono más largo. La alerta indica vender `DICP` y comprar `TX31`.
2. **Disparo de Rotación `TX31` $\to$ `DICP` (Reversión a Igualdad de TIR y Captura de Cupón):** Cuando la brecha se cierra y $|\text{TIR}_{\text{TX31}} - \text{TIR}_{\text{DICP}}| \le 35\text{ bps}$ (o cuando $\text{TIR}_{\text{DICP}} \ge \text{TIR}_{\text{TX31}} + 50\text{ bps}$, como al converger hacia $11,76\%$ vs. $11,37\%$ en [PLC7D arriba de 7% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=J2CDL8nu9fs)), desaparece el premio del `TX31` y pasa a dominar el `DICP` por su cupón corriente de $5,83\%$ frente a $2,50\%$. La regla de Lucioni indica rotar el $50\%$ (o la totalidad) de la tenencia de `TX31` hacia `DICP`.

#### Detector 2B: Arbitraje de Gemelos con Liquidez Asimétrica (`DICP` vs. `DIP0`)

En [Sumamos Bonos en pesos a la Cartera de Cashflow (2025) Gus Lucioni](http://www.youtube.com/watch?v=CzfEpVxJ0_E), se documenta que `DICP` y `DIP0` comparten exactamente el mismo prospecto de flujo de fondos (ambos vencen el 31/12/2033, pagan $5,83\%$ de interés y $5\%$ de amortización semestral). Sin embargo, `DIP0` suele cotizar casi $100\text{ bps}$ (1 punto porcentual) por encima de la TIR de `DICP` debido a su baja liquidez. El motor debe alertar oportunidad de compra en `DIP0` para carteras *buy-and-hold* únicamente cuando el inversor pueda ejecutar sobre una orden vendedora existente (`Ask`) que garantice $\text{TIR}_{\text{Ask}(\text{DIP0})} - \text{TIR}_{\text{Bid}(\text{DICP})} \ge 80\text{ bps}$.

#### Detector 2C: El "Electrocardiograma" entre Boncer Cupón Cero Contiguos (`TZXS8` vs. `TZX28` y `TZXM9`)

En [¿TZXS8 o TZX28? (2026) Gus Lucioni](http://www.youtube.com/watch?v=NKLjxmYOK4Q), [Nuevo Bono de Chubut (2026) Gus Lucioni](http://www.youtube.com/watch?v=-PXxoj8HZFU) y [TZXM9 arriba de 9% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=6b-217uVgoM), se analiza el arbitraje entre los bonos CER cupón cero que vencen en 2028 y 2029:

* **`TZX28`:** Vence el 30 de junio de 2028 (cupón cero, paga 100% del capital ajustado por CER al vencimiento).
* **`TZXS8`:** Vence el 30 de septiembre de 2028 (exactamente 3 meses después que `TZX28`, cupón cero).
* **`TZXM9`:** Vence el 31 de marzo de 2029 (cupón cero, *duration* $\approx 2,43$ años).

La ventaja estructural de los bonos CER cupón cero radica en que carecen de riesgo de reinversión de cupones y se compran con fuerte descuento sobre su Valor Técnico (por ejemplo, paridades de $83\%\text{–}85\%$). Además, frente a las elecciones presidenciales de fines de 2027, si ocurre un salto devaluatorio a fines de 2027, el traslado a precios minoristas (*pass-through* al índice CER) no es instantáneo sino que demora varios meses. Por ello, los 3 meses adicionales de vida del `TZXS8` (septiembre 2028 vs. junio 2028 del `TZX28`) y los 9 meses adicionales del `TZXM9` (marzo 2029) otorgan mayor cobertura frente a una devaluación tardía, en contraste con el provincial `PBA28` que vence el 28 de abril de 2028 sin dar margen temporal para capturar el *pass-through* ([Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM)).

El diferencial monitoreado en el graficador de Mercap Abbaco es:

$$\Delta\text{TIR}_{28} = \text{TIR}_{\text{TZXS8}} - \text{TIR}_{\text{TZX28}}$$

* **Señal Roja (Subvaluación Extrema de `TZXS8` — Rotar `TZX28` $\to$ `TZXS8`):** Cuando $\Delta\text{TIR}_{28} \ge 100\text{ bps}$ ($1,00\%$ de diferencia de TIR por solo 90 días de plazo adicional, como cuando `TZXS8` rinde $>8,80\%$ y `TZX28` rinde $7,75\%$), el sistema dispara alerta de compra de `TZXS8` y venta de `TZX28`.
* **Señal Verde (Compresión de Brecha — Rotar `TZXS8` $\to$ `TZX28`):** Cuando el spread se comprime a $\Delta\text{TIR}_{28} \le 25\text{ bps}$ (por ejemplo, $8,30\%$ vs. $8,05\%$ en [Nuevo Bono de Chubut (2026) Gus Lucioni](http://www.youtube.com/watch?v=-PXxoj8HZFU)), se toma ganancia parcial rotando de `TZXS8` hacia `TZX28`.
* **Señal de Extensión a `TZXM9` o Regreso a `TZXS8`:** En [TZXM9 arriba de 9% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=6b-217uVgoM) y [AO29 nuevo Bono soberano en USD con renta mensual](http://www.youtube.com/watch?v=3rScqsNVfT4), cuando `TZXM9` supera el umbral de $\text{TIR} \ge 9,0\%\text{–}10,0\%$ mientras `TZXS8` comprime, se rota hacia `TZXM9`; inversamente, cuando `TZXS8` vuelve a ofrecer una TIR igual o superior a `TZXM9` (llegando incluso a $11\%$ de TIR en [PLC7D arriba de 7% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=J2CDL8nu9fs)), se rota de `TZXM9` hacia `TZXS8` por tener menor *duration* e igual o mayor tasa real.

#### Detector 2D: Arbitraje de Escalón Electoral en CER Cortos (`TZXS7` vs. `TZXS8` y `TZXO7` vs. `TZXS7` / `TZXM7`)

En [Nuevo Bono TZXO7 (2026) Gus Lucioni](http://www.youtube.com/watch?v=xjvXqUOxTLM), se modela el "escalón de riesgo político" entre los bonos que vencen bajo la administración actual y los que vencen en el mandato siguiente:

1. **Par Pre-Electoral vs. Post-Electoral (`TZXS7` vs. `TZXS8`):** Históricamente, `TZXS7` (septiembre 2027) llegó a rendir hasta $500\text{ bps}$ menos de TIR que `TZXS8` (septiembre 2028) y a cotizar con una prima de paridad de hasta $+12,86\%$ (media histórica de $+10,50\%$). Cuando el spread de TIR se achica a $|\text{TIR}_{\text{TZXS7}} - \text{TIR}_{\text{TZXS8}}| \le 225\text{ bps}$ y la diferencia de paridad cae a $\le 9,20\%$, el mercado está cobrando muy barato el seguro contra el riesgo electoral, disparándose la alerta de **Rotar de `TZXS8` hacia `TZXS7`**.
2. **Par Intra-Ventana Electoral (`TZXO7` vs. `TZXS7`):** Ambos vencen en plena contienda electoral (septiembre vs. octubre de 2027). Si el nuevo bono `TZXO7` cotiza con $\text{TIR}_{\text{TZXO7}} - \text{TIR}_{\text{TZXS7}} \ge +40\text{ a }+50\text{ bps}$ ($6,34\%$ vs. $<5,90\%$), conviene arbitrar hacia `TZXO7` porque el riesgo político asumido es prácticamente idéntico.
3. **Filtro de Piso contra Plazo Fijo UVA (`TZXM7` / `TZX27`):** En [PARP abajo de 8% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=KTQlxbVUPJI) y [YM37D ¿Oportunidad Conservadora? (2026) Gus Lucioni](http://www.youtube.com/watch?v=Nbksr1IE7pU), cuando un bono CER corto que vence en pocos meses (`TZXM7` o `TZX27`) comprime su TIR por debajo de $2,0\%\text{–}2,8\%$, el costo de comisión de compra del broker erosiona el rendimiento real neto, dejándolo por debajo de un Plazo Fijo UVA precancelable o de un FCI CER (que no paga comisión de compraventa por cada título). El motor debe emitir alerta de **Bloqueo de Compra Directa / Toma de Ganancia en CER Corto** cuando $\text{TIR}_{\text{CER Corto}} - \frac{\text{Comisión}_{\text{Broker}}}{T_{\text{años}}} < \text{Tasa}_{\text{UVA}}$.

### Estrategia 3: Arbitraje Cross-Asset Soberano (Rotación entre Curva CER y Curva Hard Dollar)

Uno de los aportes más valiosos del canal de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni), desarrollado en [Rotar de HD a CER ¿Sigue siendo Oportunidad? (2025) Gus Lucioni](http://www.youtube.com/watch?v=GGXMEcxL7yY) y [¿Momento de rotar Bonos CER a Bonos en USD? (2026) Gus Lucioni](http://www.youtube.com/watch?v=_GG5fkS0xi8), consiste en emparejar bonos soberanos en pesos ajustados por inflación (CER) con bonos soberanos en dólares (Hard Dollar) de similar *Modified Duration* e historial de reestructuración para operar la brecha entre tasa real local y riesgo soberano en divisas:

* **Par Largo de Convexidad:** `PARP` (CER 2038) vs. `GD41` / `AL41` (Hard Dollar 2041).
* **Par Medio-Largo de Flujo (Ex-Discount):** `DICP` (Discount en Pesos CER 2033) vs. `AE38` / `GD38` (ex-DICA, Discount en USD 2038).
* **Par Medio-Corto:** `TX31` (CER 2031) vs. `AL30` / `GD30` (Hard Dollar 2030).

La relación fundamental que rige este arbitraje establece que el Estado Nacional tiene mayor capacidad para honrar deuda en su propia moneda indexada que deuda en moneda extranjera, por lo cual, en equilibrio:

$$\text{TIR}_{\text{CER}}(MD) < \text{TIR}_{\text{Hard Dollar}}(MD) \quad \text{y} \quad \text{Paridad}_{\text{CER}} > \text{Paridad}_{\text{Hard Dollar}}$$

Definimos el *TIR Spread Cross-Asset* para cada par emparejado por duración como:

$$S_{\text{HD-CER}} = \text{TIR}_{\text{Hard Dollar}} - \text{TIR}_{\text{CER}}$$

El motor de alertas debe monitorear dos regímenes extremos de desarbitraje:

1. **Régimen de Inversión de Curvas ($S_{\text{HD-CER}} \le 0\text{ bps}$ — Alerta de Rotación `Hard Dollar` $\to$ `CER`):** Documentado en [Rotar de HD a CER ¿Sigue siendo Oportunidad? (2025) Gus Lucioni](http://www.youtube.com/watch?v=GGXMEcxL7yY), cuando por una venta masiva de activos en pesos o intervención oficial el bono en dólares pasa a rendir menos TIR que su par CER (por ejemplo, $\text{TIR}_{\text{GD41}} < \text{TIR}_{\text{PARP}}$ o $\text{TIR}_{\text{AE38}} < \text{TIR}_{\text{DICP}}$, reduciéndose además la brecha de paridades a mínimos de $8\%\text{–}13\%$), se configura una anomalía severa. La señal ordena **vender Hard Dollar (`GD41`, `AE38`) y comprar CER (`PARP`, `DICP`)**.
2. **Régimen de Compresión Extrema de CER y Ampliación de Brecha ($S_{\text{HD-CER}} \ge 250\text{ a }350\text{ bps}$ — Alerta de Rotación `CER` $\to$ `Hard Dollar`):** Documentado en [¿Momento de rotar Bonos CER a Bonos en USD? (2026) Gus Lucioni](http://www.youtube.com/watch?v=_GG5fkS0xi8), cuando los bonos CER experimentan un fuerte *rally* (comprimiendo `PARP` hacia $\le 7,5\%$ de TIR y los CER cortos hacia tasas cercanas a cero o negativas) mientras los bonos Hard Dollar quedan rezagados con TIRs de $10\%\text{–}11\%$, y simultáneamente el tipo de cambio financiero se ubica cerca del piso o lejos del techo de la banda cambiaria, el potencial alcista de los CER se agota y su riesgo cambiario aumenta. La señal ordena **tomar ganancias en CER (`PARP`, `DICP`, `TX31`) y rotar hacia Hard Dollar (`GD41`, `AE38`, `AL30`)**.

### Estrategia 4: Arbitraje Intra-Curva Soberana Hard Dollar (Pre-Cupón, Flujo Acumulado y Frecuencia Mensual vs. Semestral)

Dentro de los bonos soberanos en dólares, el análisis del canal identifica tres mecanismos de arbitraje que van más allá de la simple comparación de TIR puntual.

#### Mecanismo 4A: Rotación Táctica Pre-Corte de Cupón y Inicio de Amortización (`GD41` $\to$ `AE38`)

En [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) y [¿Tengo un Bono en USD favorito? (2025) Gus Lucioni](http://www.youtube.com/watch?v=ok2pA7OZer8), Lucioni explica que aunque `GD41` y `AL41` lideran las simulaciones teóricas de suba ante una compresión paralela de tasas por su mayor convexidad, el bono `AE38` cuenta con dos ventajas operativas concretas:
* Su tasa de cupón corriente es del $5,00\%$ anual frente al $3,50\%$ del `GD41`/`AL41`.
* Comienza a devolver capital el 9 de julio de 2027 en cuotas semestrales del $4,54\%$, mientras que el 41 recién comienza el 9 de enero de 2028 en cuotas del $3,57\%$.

Por consiguiente, en las semanas previas a las fechas de corte semestral (9 de enero y 9 de julio), cuando `AE38` cotiza con una TIR igual o superior a la de `GD41` (o cuando el ratio $\frac{P_{\text{AE38}}}{P_{\text{GD41}}} \le 1,11$), se dispara una alerta de **Rotación Táctica Pre-Cupón hacia `AE38`**, dado que el mercado tiende a demandar el título de mayor pago inmediato a medida que se acerca la fecha *ex-cupón*.

#### Mecanismo 4B: Arbitraje de Velocidad de Recupero de Dólares (`GD46` vs. `GD41` vs. `AE38`)

En el artículo [Cash-flow en dólares: ¿momento de vender el GD46?](https://mercapsoftware.com/cash-flow-en-dolares-momento-de-vender-el-gd46/) ([Correo Mercap Abbaco 27/12/2024](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1819617300032268661)) y en el video [Cartera de Cashflow ¿AE38 o GD46? (2026) Gus Lucioni](http://www.youtube.com/watch?v=wyUa64aHGcQ), la comparación entre bonos largos no se realiza solo por TIR a vencimiento (2038 vs. 2041 vs. 2046), sino mediante una **Simulación de Flujo Acumulado por Monto Invertido ($I_0$)**:

Para un capital inicial fijo en dólares $I_0$ (por ejemplo, USD 1.000 o USD 10.000), se calcula la cantidad de nominales adquiribles de cada bono $i$:

$$VN_i = \frac{I_0}{P_{\text{Ask}, i} / 100}$$

y se computa el flujo acumulado de dólares cobrados (intereses + amortizaciones) hasta un horizonte $H$ (por ejemplo, fin del mandato presidencial o primeros 5 años):

$$CF_i(H) = VN_i \cdot \sum_{t \le H} (c_{i,t} + a_{i,t})$$

* Cuando `GD46` cotiza lo suficientemente barato respecto a `AE38`, `GD46` ofrece la ventaja de estar ya pagando cuotas semestrales de amortización del $2,27\%$ (entregando $\approx \text{USD } 8$ anuales por lámina bajo Ley Nueva York).
* Cuando `GD46` se encarece en relación con `GD41` o `AE38` de forma tal que $CF_{\text{GD41}}(H) > CF_{\text{GD46}}(H)$ con menor *maturity* y protección *Indenture 2005*, se dispara la alerta de **Venta de `GD46` y Rotación a `GD41` / `AE38`**.

#### Mecanismo 4C: Arbitraje de Frecuencia de Flujo y Ventana Política en los Nuevos Soberanos (`AO29` vs. `AN29` vs. `AO28`)

En [¿AO29 o AN29? (2026) Gus Lucioni](http://www.youtube.com/watch?v=iI_l2kb973c) y [AO29 nuevo Bono soberano en USD con renta mensual](http://www.youtube.com/watch?v=3rScqsNVfT4), se establece la lógica de arbitraje para la nueva familia de bonos del Tesoro en dólares con vencimientos en 2027, 2028 y 2029:

1. **Arbitraje de Frecuencia de Cobro (`AO29` vs. `AN29`):** Ambos títulos son Ley Argentina, vencen en 2029 (octubre y noviembre respectivamente) y cotizan con TIR casi idéntica (`AN29` rinde apenas unas décimas más por tener cupón anual de $6,50\%$ frente al $6,00\%$ del `AO29`). Sin embargo, `AN29` paga intereses de forma **semestral** (mayo y noviembre), mientras que `AO29` paga intereses **todos los meses** ($0,50\%$ mensual, es decir USD 0,50 por cada lámina de 100 VN). Bajo incertidumbre electoral para fines de 2027, el inversor en `AO29` cobra cupones todos los meses previos a las elecciones (junio, julio, agosto, septiembre y octubre de 2027) bajo la gestión actual, reduciendo su capital en riesgo mucho más rápido que en `AN29`.
   * **Regla de Alerta:** Siempre que $\text{TIR}_{\text{AN29}} - \text{TIR}_{\text{AO29}} \le 75\text{ bps}$, el sistema debe alertar **Rotación de `AN29` hacia `AO29`** por superioridad de flujo mensual y menor exposición preelectoral.
2. **Arbitraje de Extensión Mismo Riesgo Político (`AO28` $\to$ `AO29`):** Dado que tanto `AO28` como `AO29` vencen después del cambio de mandato presidencial de diciembre de 2027 (asumiendo ambos el mismo riesgo de reestructuración en caso de cambio de signo político), cuando `AO29` cotiza con $\text{TIR}_{\text{AO29}} > \text{TIR}_{\text{AO28}}$ y menor precio de entrada, el sistema dispara alerta de **Rotación de `AO28` a `AO29`** para capturar mayor TNA corriente y un año adicional de renta mensual a igual evento binario de riesgo político.

### Estrategia 5: Arbitraje por Simulación de Sensibilidad Cruzada (Upside Objetivo vs. Downside de Estrés Histórico)

En [¿Tengo un Bono en USD favorito? (2025) Gus Lucioni](http://www.youtube.com/watch?v=ok2pA7OZer8), [Bonos Hard Dólar: ¿Cuáles tienen mayor Potencial de Suba? (2025) Gus Lucioni](http://www.youtube.com/watch?v=RpRWXd7hXXo), [GD41 ¿El Mejor de los Globales? (2025) Gus Lucioni](http://www.youtube.com/watch?v=8yXP9CoAPGE), [AE38 quedo Relegado Nuevamente (2025) Gus Lucioni](http://www.youtube.com/watch?v=Wuz2yBw8ECk), [On de YPF + Simulación Globales y Bonos de PBA (2025) Gus Lucioni](http://www.youtube.com/watch?v=szbHhfNKLuw), [¿Se viene el Rebote? (2026) Gus Lucioni](http://www.youtube.com/watch?v=xbpulrQpAB4) y [PARP abajo de 8% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=KTQlxbVUPJI), el canal emplea una metodología cuantitativa rigurosa que la mayoría de las aplicaciones minoristas omiten: la **Matriz de Sensibilidad con TIR Cruzada**.

El error habitual al comparar bonos de distinta duración, legislación o emisor consiste en proyectar el cambio de precio asumiendo que todos los bonos irán a la misma TIR objetivo. Lucioni corrige este sesgo asignando a cada bono $i$ su propio par de parámetros históricos:

* **TIR Objetivo Alcista ($\text{TIR}_{i}^{\text{bull}}$):** Definida por la tasa mínima alcanzada por ese bono en el último ciclo alcista o por la tasa de *rollover* soberano más el spread estructural de su categoría. Por ejemplo:
  * En Globales Ley NY (`GD38`, `GD41`, `GD46`): $\text{TIR}_{\text{NY}}^{\text{bull}} \in [7,5\%, 8,5\%]$.
  * En Bonares Ley ARG (`AE38`, `AL41`, `AL35`): $\text{TIR}_{\text{ARG}}^{\text{bull}} \in [8,5\%, 10,0\%]$.
  * En Provinciales PBA (`BB37D`, `BA37D`): $\text{TIR}_{\text{PBA}}^{\text{bull}} = \text{TIR}_{\text{NY}}^{\text{bull}} + 200\text{ bps}$ (por ejemplo, si los Globales van a $10\%$, a `BB37D` se le exige $12\%$).
  * En Curva CER (`PARP` vs. `TZX27`): si `PARP` comprime a $6,0\%$ de TIR, a `TZX27` se le proyecta $0\%$ a $-5,0\%$ de TIR.
* **TIR Objetivo Bajista / Estrés ($\text{TIR}_{i}^{\text{bear}}$):** Definida por el máximo histórico reciente de TIR de cada título específico durante eventos de estrés electoral:
  * `AL41` / `GD41`: $\text{TIR}^{\text{bear}} \approx 27\%$.
  * `AE38`: $\text{TIR}^{\text{bear}} \approx 33\%$ (o $22,5\%$ dentro del mandato actual).
  * `BB37D` / `BA37D`: $\text{TIR}^{\text{bear}} \approx 30\%$.
  * `PARP`: $\text{TIR}^{\text{bear}} \approx 12\%$ vs. `TZX27`: $\text{TIR}^{\text{bear}} \approx 20\%\text{–}25\%$.

Para cada activo $i$, el motor calcula el precio teórico $P_i(\text{TIR})$ descontando su flujo de fondos exacto a la fecha de evaluación (o a un horizonte $t + \Delta t$) y obtiene el retorno potencial alcista ($U_i$) y la pérdida potencial bajista ($D_i$):

$$U_i = \frac{P_i\left(\text{TIR}_{i}^{\text{bull}}\right) - P_{i,\text{Ask}}}{P_{i,\text{Ask}}}, \quad D_i = \left| \frac{P_i\left(\text{TIR}_{i}^{\text{bear}}\right) - P_{i,\text{Bid}}}{P_{i,\text{Bid}}} \right|$$

A partir de estas dos métricas, el sistema clasifica y alerta desarbitrajes en la curva cuando un bono domina simultáneamente en el ratio de asimetría:

$$\Omega_i = \frac{U_i}{D_i}$$

| Escenario / Comparativa en el Canal | Activos Evaluados | Parámetros de TIR Cruzada Aplicados | Ganador Algorítmico y Regla de Rotación | Fuente del Canal |
| :--- | :--- | :--- | :--- | :--- |
| **Rebote Soberanos Ley Local** | `AL41`, `AE38`, `AL35`, `AL30` | $\text{TIR}^{\text{bull}} \in \{10\%, 9\%, 8\%, 7\%\}$; $\text{TIR}^{\text{bear}} = 27\%$ (`AL41`) vs. $33\%$ (`AE38`) | **`AL41`** lidera en *upside* en todos los escenarios alcistas; **`AE38`** lidera en menor *downside* en escenarios bajistas (15%–18% TIR) y empata en caída máxima (-36%) bajo TIR cruzada (27% vs. 33%) | [Bonos Hard Dólar: ¿Cuáles tienen mayor Potencial de Suba?](http://www.youtube.com/watch?v=RpRWXd7hXXo) / [AE38 quedo Relegado Nuevamente](http://www.youtube.com/watch?v=Wuz2yBw8ECk) |
| **Rebote Soberanos Ley NY** | `GD41`, `GD46`, `GD38`, `GD35`, `GD30`, `GD29` | $\text{TIR}^{\text{bull}} \in \{8,5\%, 8,0\%, 7,5\%\}$; $\text{TIR}^{\text{bear}} \in \{15\%, 17\%\}$ | **`GD41`** y **`GD46`** alternan el primer puesto de *upside*: cuando `GD46` queda rezagado en TIR respecto a `GD41`, `GD46` supera en *upside*; `GD41` es preferido como posición núcleo por liquidez e *Indenture 2005* | [GD41 ¿El Mejor de los Globales?](http://www.youtube.com/watch?v=8yXP9CoAPGE) / [¿Se viene el Rebote? (2026)](http://www.youtube.com/watch?v=xbpulrQpAB4) |
| **Soberanos NY vs. Provincia Bs. As.** | `GD38D`, `GD41D`, `GD35D`, `GD46D` vs. `BB37D`, `BA37D` | Alcista: $10\%$ Soberanos vs. $12\%$ PBA; Bajista: $25\%\text{–}27\%$ Soberanos vs. $30\%$ PBA | **`BB37D`** supera en *upside* neto (+34% a +46%) a los Globales con similar *downside* en estrés y cuenta con *Indenture 2005*; apto para *hold*, descartado para *trading* por iliquidez | [On de YPF + Simulación Globales y Bonos de PBA (2025)](http://www.youtube.com/watch?v=szbHhfNKLuw) |
| **Curva CER Larga vs. Corta** | `PARP` vs. `TZX27` | Alcista: `PARP` a $6\%$ vs. `TZX27` a $0\%\text{ / }-5\%$; Bajista: `PARP` a $12\%$ vs. `TZX27` a $20\%$ | Con `PARP` en $7,72\%$ y `TZX27` en $1,91\%$, la caída de `PARP` a $12\%$ (-22%) vs. `TZX27` a $20\%$ (-16%) muestra que la curva está arbitrada; se mantiene `PARP` existente pero las nuevas compras van al tramo corto | [PARP abajo de 8% de TIR (2026)](http://www.youtube.com/watch?v=KTQlxbVUPJI) |

### Estrategia 6: Arbitraje en Obligaciones Negociables (Intra-Grupo Empresario, Intra-Emisor y Sustitución de Soberanos Cortos)

El mercado de deuda corporativa argentina presenta frecuentes fragmentaciones por iliquidez minorista y emisión constante de nuevas series. El análisis de los videos de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni) permite extraer cinco reglas algorítmicas de arbitraje en ONs:

#### Regla 6A: Arbitraje de Gemelos Intra-Grupo Empresario a Costo Cero (`MR36O` $\to$ `LECH0` y `IRSA` $\leftrightarrow$ `Cresud`)

Documentado en [¿Oportunidad? Pasar de MR36O a LECH0](https://mercapsoftware.com/oportunidad-pasar-de-mr36o-a-lech0/) ([Correo Mercap Abbaco 20/01/2025](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1821783958137677943)), cuando un mismo grupo económico emite obligaciones negociables a través de dos sociedades operativas vinculadas con **idéntico cronograma de pagos y tasa de cupón** (como `MR36O` de Generación Mediterránea S.A. - GEMSA y `LECH0` de Albanesi Energía S.A., ambas integrantes del Grupo Albanesi), ambas comparten exactamente el mismo riesgo crediticio consolidado y el mismo flujo de caja.

Si en la caja de puntas el precio comprador de la especie A supera al precio vendedor de la especie B descontadas las comisiones:

$$\frac{\text{Bid}_{A} \cdot (1 - c_{\text{venta}})}{\text{Ask}_{B} \cdot (1 + c_{\text{compra}})} > 1 + \delta_{\text{min}}$$

donde $\delta_{\text{min}}$ es el umbral mínimo de ganancia neta de nominales (por ejemplo, $\ge 1,0\%$), el motor dispara una **Alerta de Arbitraje Puro Intra-Grupo**: vender `MR36O` y comprar `LECH0`, incrementando la cantidad de valores nominales a costo cero y manteniendo idéntico *cash-flow*. De forma análoga, para carteras conservadoras en USD, Lucioni empareja las ONs de **IRSA** (`IRCOO`, `IRCFO`, pagos en enero y julio) con las de su controlante **Cresud** (`CS38O`, `CS44O`, pagos en mayo y noviembre) por compartir el mismo riesgo de grupo empresario ([ON de Cresud para Cashflow (2025) Gus Lucioni](http://www.youtube.com/watch?v=PT6FDlf28ro) y [Cashflow Mensual ¿Volvimos? (2025) Gus Lucioni](http://www.youtube.com/watch?v=W5VDd02Q00c)).

#### Regla 6B: Arbitraje entre Emisores Vinculados con Idéntica Fecha de Pago (`YMCJO` $\to$ `YFCJO`)

En [¿Oportunidad para rotar de YMCJO a YFCJO? (2025) Gus Lucioni](http://www.youtube.com/watch?v=1c7nQR6f3V4) ([Correo Mercap Abbaco 19/06/2025](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1835363123060456151)), analiza la rotación entre `YMCJO` (emitida por YPF S.A.) e `YFCJO` (emitida por su subsidiaria eléctrica YPF Luz). Ambos títulos pagan semestralmente a fines de marzo y septiembre (acreditándose en abril y octubre) y poseen tickers casi idénticos. Cuando el diferencial de rendimiento cumple:

$$\text{TIR}_{\text{Ask}(\text{YFCJO})} - \text{TIR}_{\text{Bid}(\text{YMCJO})} \ge 50\text{ a }100\text{ bps}$$

y el cupón de `YFCJO` ($7,875\%$) supera al de `YMCJO`, se dispara la alerta de **Rotación Corporativa Intra-Mes de Flujo (`YMCJO` $\to$ `YFCJO`)**, siempre que el diferencial de TIR supere el costo transaccional de entrada y salida amortizado en el plazo remanente.

#### Regla 6C: Arbitraje Intra-Curva YPF por Estructura de Amortización (`YM39D` vs. `YM34D` vs. `YM42D`)

En [ON de Cresud para Cashflow (2025) Gus Lucioni](http://www.youtube.com/watch?v=PT6FDlf28ro), [¿Alternativa Interesante para quienes buscan Cashflow? (2025) Gus Lucioni](http://www.youtube.com/watch?v=F2Z5Cx36ilg) y [Sumamos dos Nuevos Bonos a la Cartera (2025) Gus Lucioni](http://www.youtube.com/watch?v=ek111LGCrh8), advierte en primer lugar una **regla de parseo de tickers para la IA**: en las ONs de YPF, el número del ticker **no indica el año de vencimiento** (`YM39D` vence en julio de 2030; `YM42D` vence en 2029; `YM37D` vence en mayo de 2027; `YM34D` vence en 2034).

Al comparar `YM39D` contra `YM34D` (ambas Ley Nueva York, ambas pagaderas en enero y julio y cotizando alrededor de 100% de paridad):
* `YM39D` vence en julio de 2030 (5 años), es *bullet* (devuelve el 100% al final) y paga un cupón de $8,75\%$ TNA.
* `YM34D` vence en 2034 (amortizando en 3 cuotas en 2032, 2033 y 2034) y paga un cupón menor ($8,25\%$ TNA).

Cuando la curva de YPF se aplana o se invierte de modo que $\text{TIR}_{\text{YM39D}} \ge \text{TIR}_{\text{YM34D}} - 25\text{ bps}$, `YM39D` domina estrictamente a `YM34D` (mayor cupón, menor plazo de vencimiento y estructura *bullet* sin necesidad de reinvertir tercios de capital), disparando alerta de **Rotación `YM34D` $\to$ `YM39D`**.

#### Regla 6D: Arbitraje de Dolarización Corta Pre-Electoral (`YM37D` / `OZC3O` vs. `AO27` / `BPY26`)

En [YM37D ¿Oportunidad Conservadora? (2026) Gus Lucioni](http://www.youtube.com/watch?v=Nbksr1IE7pU), [Opciones en Pesos y en USD de Corto Plazo (2026) Gus Lucioni](http://www.youtube.com/watch?v=YAnMRRLCleE) y [Alternativas al BPY26 (2025) Gus Lucioni](http://www.youtube.com/watch?v=0bdFQ0eRES0), identifica un desarbitraje estructural causado por la demanda institucional: los inversores institucionales regulados que buscan cobertura en dólares antes de las elecciones presidenciales de octubre de 2027 están obligados por liquidez y normativa a comprar el bono soberano `AO27` (comprimiendo su TIR a apenas $2,84\%\text{–}2,90\%$) o BOPREAL `BPY26`.

Un inversor minorista o cartera mediana no tiene esa restricción de volumen y puede arbitrar vendiendo `AO27` (o `BPY26`) y comprando ONs corporativas cortas que vencen antes del recambio presidencial:
* **`YM37D` (YPF):** Vence el 7 de mayo de 2027 (5 meses antes de las elecciones), paga cupón trimestral del $7,0\%$ TNA (noviembre, febrero y mayo), cotiza a $\approx 100\%$ de paridad y rinde **$6,37\%$ de TIR** (un spread positivo de **$+347\text{ bps}$** sobre el soberano `AO27` con menor plazo y menor riesgo de default).
* **`OZC3O` / `OZCD` (EDESa):** Vence en febrero/noviembre de 2027 con cupón del $8,0\%\text{–}8,5\%$ TNA y rinde entre **$6,64\%$ y $7,39\%$ de TIR** (y hasta $12\%$ en momentos de iliquidez, según [TZXM9 arriba de 9% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=6b-217uVgoM)).

#### Regla 6E: Sustitución por Lámina Mínima y Umbral del 7% en ONs Hard Dollar Largas (`MGCRD` $\leftrightarrow$ `PLC7D` / `VSCXO`)

En [Cashflow mensual en USD Cable arriba del 7% Anual (2026) Gus Lucioni](http://www.youtube.com/watch?v=KoLLc-AHGG0), [VSCXO ¿Vale la pena ir tan largo? (2026) Gus Lucioni](http://www.youtube.com/watch?v=xC4tFjouZhU) y [PLC7D arriba de 7% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=J2CDL8nu9fs), codifica las reglas para el segmento de ONs y subsoberanos largos Ley Nueva York que pagan en Dólar Cable:

1. **Umbral Mágico del 7% de TIR:** Solo se activan alertas de compra para carteras de renta en ONs corporativas largas de primera línea (`VSCXO` de Vista 2038, `PLC7D` de Pluspetrol 2031/2037, `MGCRD` de Pampa 2037, `IRCFO` de IRSA 2035, `TLCMO` de Telecom) cuando una corrección de precios lleva su $\text{TIR}_{\text{Ask}} \ge 7,0\%$ (idealmente entre $7,15\%$ y $7,85\%$) y sus paridades recortan desde $106\%\text{–}110\%$ hacia $\le 99\%\text{–}103\%$.
2. **Sustitución Automática por Restricción de Lámina Mínima:** `MGCRD` (Pampa Energía 2037) y `CO35` (Provincia de Córdoba 2035) exigen una **lámina mínima de 10.000 nominales** ($\approx \text{USD } 9.800\text{ a }10.200$ por posición). Para carteras minoristas donde ese mínimo impide diversificar, el algoritmo debe sustituir automáticamente `MGCRD` por `PLC7D` / `PLC7O` (Pluspetrol, que paga en los mismos meses de marzo y septiembre, es Ley NY Cable, rinde $>7\%$ y tiene **lámina mínima de 1.000 nominales**) y sustituir `CO35` por `SJO5D` (San Juan 2035, cupón 9,55%, Ley NY, **lámina mínima de 1.000 nominales**) o `NDG4D` (Neuquén 2034, **lámina mínima de 1.000 nominales**).

### Estrategia 7: Arbitraje en Títulos Subsoberanos (Factor de Capital Residual, Canjes Voluntarios y Techo de Paridad)

El análisis de los bonos provinciales en el canal de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni) incorpora variables institucionales y técnicas que determinan cuándo un subsoberano está desarbitrado respecto a la curva soberana o respecto a otros provinciales:

1. **Indicador de Protección por Bajo Capital Residual ($VR_t \le 55\%$):** En [Sumamos dos Nuevos Bonos a la Cartera (2025) Gus Lucioni](http://www.youtube.com/watch?v=ek111LGCrh8), [Canje en ERF25 (2026) Gus Lucioni](http://www.youtube.com/watch?v=KPtQ2ROAtyo), [Bonos de la Provincia de Neuquén (2025) Gus Lucioni](http://www.youtube.com/watch?v=M426ASSqlww) y [Opciones en Pesos y en USD de Corto Plazo (2026) Gus Lucioni](http://www.youtube.com/watch?v=YAnMRRLCleE), Lucioni demuestra que la probabilidad de que una provincia reestructure o incumpla un bono cae drásticamente cuando el **Valor Residual ($VR_t$, porcentaje del capital original aún no amortizado)** es bajo, ya que el costo político, legal y financiero de organizar un canje supera el ahorro sobre un saldo remanente pequeño (tal como ocurrió históricamente con el `CO26` de Córdoba, que nunca fue reestructurado en 2020 porque ya había amortizado cuotas y era una emisión chica).
   * **Ejemplos operativos:** `ERF25` (Entre Ríos, $VR = 54\%$, ya devolvió el $46\%$), `BNA6D` (Neuquén, $VR = 50\%\text{ a }25\%$), `NDT25` (Neuquén, le restan solo $\approx 40\%$ de capital en el próximo mandato presidencial).
2. **Regla Algorítmica ante Ofertas de Canje Voluntario (`ERF25` $\to$ Nuevo Entre Ríos 2034):** En [Canje en ERF25 (2026) Gus Lucioni](http://www.youtube.com/watch?v=KPtQ2ROAtyo), cuando una provincia ofrece canjear un bono corto que ya está amortizando capital (`ERF25` con vencimiento en agosto de 2028 y $VR = 54\%$) por un nuevo bono largo a 2034 (con estructura de 3 cuotas al final y TIR de $\approx 9\%$), el sistema debe evaluar:
   * Si el bono original tiene $VR_t \le 60\%$, vence dentro de los próximos $2,5$ años y su TIR actual ($\ge 8,2\%$) es similar a la del nuevo título largo ($\approx 9,0\%$), **la recomendación algorítmica es rechazar el canje y mantener el título corto** (aun asumiendo pérdida de liquidez secundaria), evitando extender *duration* 6 años sin prima de compensación.
3. **Arbitraje de Desconexión Subsoberano vs. Soberano (`NDT25` vs. `AL29D` y Bono de Salta):**
   * En [Bonos de la Provincia de Neuquén (2025) Gus Lucioni](http://www.youtube.com/watch?v=M426ASSqlww), cuando `NDT25` (Neuquén 2030) comprime su TIR a $\approx 5,4\%\text{–}6,0\%$ entregando un resultado operativo de USD 1.147 sobre USD 6.968 invertidos hasta 2030, mientras que el soberano `AL29D` (que vence antes, en julio de 2029) cotiza a USD 68,07 para devolver USD 81,80 por lámina (entregando USD 41,30 antes del fin del mandato actual), la brecha de rendimiento a favor de `AL29D` resulta excesiva para un mismo horizonte sistémico, disparando alerta de **Sobrevaluación de `NDT25` frente a `AL29D`**.
   * En [¿Como saber si estoy pagando caro o barato?](http://www.youtube.com/watch?v=sUSsj5h9Nxw) y [AO29 nuevo Bono soberano en USD con renta mensual](http://www.youtube.com/watch?v=3rScqsNVfT4), cuando un bono provincial ilíquido como el de Salta o Entre Ríos aparece en la caja de puntas con $\text{TIR}_{\text{Ask}} \le 4,0\%$ (rindiendo menos que un bono del Tesoro de EE. UU.), el sistema debe emitir una **Alerta de Venta / Salida Inmediata por Desarbitraje Extremo**.
4. **Filtro de Paridad Máxima en Subsoberanos Largos (`PUA36D` de Chubut):** En [Nuevo Bono de Chubut (2026) Gus Lucioni](http://www.youtube.com/watch?v=-PXxoj8HZFU), aunque `PUA36D` ofrece un cupón trimestral muy atractivo del $9,45\%$ TNA y una TIR del $8,0\%$, cotiza a una paridad de **$108,75\%$**. La regla de Lucioni bloquea la compra de cualquier bono subsoberano de provincia con fragilidad fiscal cuya paridad supere el $102\%\text{–}104\%$, configurando una alerta de espera hasta que la paridad perfore el umbral de $\le 100\%$.

### Estrategia 8: Arbitraje de Tasas en Pesos (Opcionalidad en Bonos Duales TAMAR/CER, Spread Provincial `PBA27` y Tasa Fija)

En los videos [Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM), [Los nuevos Bonos PBA 27 y 28 (2026) Gus Lucioni](http://www.youtube.com/watch?v=nQd8O7IoLxE), [PR17 Alternativa en Pesos (2026) Gus Lucioni](http://www.youtube.com/watch?v=_oSDzanYRJk), [TIR de la cartera de Bonos CER y TAMAR/TASA FIJA](http://www.youtube.com/watch?v=19qYECYckp0) y [Opciones en Pesos y en USD de Corto Plazo (2026) Gus Lucioni](http://www.youtube.com/watch?v=YAnMRRLCleE), se estructuran tres arbitrajes dentro del universo de tasas en pesos:

1. **Arbitraje de Opcionalidad Gratuita en Bonos Duales (`TXMD8` / `TXMJ8` vs. `PR17` y TAMAR Puros):** Los bonos duales TAMAR/CER pagan al vencimiento el máximo entre la capitalización de la tasa variable TAMAR y el ajuste por inflación CER:
   $$\text{Payoff}_{\text{Dual}} = \max\left( \text{Flujo}_{\text{TAMAR}}, \text{Flujo}_{\text{CER}} \right)$$
   Por lo tanto, el precio de un bono Dual contiene una opción implícita ($\text{Valor}_{\text{Opción}} \ge 0$). En [Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM), Lucioni muestra que evaluados en la curva CER-Dual rinden varios puntos menos que los CER puros (el costo de la opción vista desde CER), pero evaluados en la curva **TAMAR-Dual** llegan a rendir entre **$33\%$ y $40\%$ de TIR**, superando o igualando la TIR del bono `PR17` (que ajusta únicamente por tasa BADLAR + 0%, sin piso de inflación).
   * **Regla de Alerta:** Siempre que para un plazo comparable se cumpla:
     $$\text{TIR}_{\text{Dual (bajo supuesto TAMAR)}} \ge \text{TIR}_{\text{Bono TAMAR/BADLAR Puro}} - 50\text{ bps}$$
     existe un **Desarbitraje de Opcionalidad Gratuita**: conviene vender el flotante puro (`PR17` o letra TAMAR) y comprar el Dual (`TXMD8`, `TXMJ8`), ya que se obtiene el mismo rendimiento flotante más un seguro gratuito contra una aceleración inflacionaria.
2. **Arbitraje de Sobretasa Subsoberana en Pesos (`PBA27` vs. `TML27` / `TMF27` / `T30A7`):** En [Los nuevos Bonos PBA 27 y 28 (2026) Gus Lucioni](http://www.youtube.com/watch?v=nQd8O7IoLxE) y [YM37D ¿Oportunidad Conservadora? (2026) Gus Lucioni](http://www.youtube.com/watch?v=Nbksr1IE7pU), el bono de la Provincia de Buenos Aires `PBA27` (vence el 30 de abril de 2027, antes de las elecciones) cotiza con un spread de **$\text{TAMAR} + 733\text{ bps}$** (TNA $\approx 31,37\%$), mientras que los bonos TAMAR del Tesoro Nacional de similar vencimiento (`TML27` jul-2027 a $\text{TAMAR} + 540\text{ bps}$, `TMF27` feb-2027) rinden entre $24\%$ y $25\%$ de TEA, y el bono a tasa fija `T30A7` (abr-2027) rinde $28\%\text{–}30\%$ fijo sin cobertura ante suba de tasas.
   * **Regla de Alerta:** Cuando $\text{TIR}_{\text{PBA27}} - \text{TIR}_{\text{TML27/T30A7}} \ge 300\text{ a }600\text{ bps}$ y el precio de `PBA27` se ubica bajo $101\%$ de paridad, el motor dispara alerta a favor de `PBA27` (considerando que el riesgo de default de deuda provincial en moneda local antes de las elecciones es marginal).

### Estrategia 9: Arbitraje de Costo de Oportunidad Internacional (Curva Local vs. `TLT` y Soberanos de Brasil `BR45`)

En [¿Permanecer Líquido es Opción? (2026) Gus Lucioni](http://www.youtube.com/watch?v=Rh3t_OTUbwg), [Bonos del Tesoro (2026) Gus Lucioni](http://www.youtube.com/watch?v=25uYIk7URNs), [TZXM9 arriba de 9% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=6b-217uVgoM) y [Nuevo Bono TZXO7 (2026) Gus Lucioni](http://www.youtube.com/watch?v=xjvXqUOxTLM), se incorpora un piso externo de arbitraje que evita quedar atrapado en activos locales sobrevaluados:

* **Benchmark Externo Libre de Riesgo Argentino:** La tasa de los bonos del Tesoro de EE. UU. a 10–20 años ($y_{\text{UST}} \approx 4,5\%\text{–}4,6\%$, operable localmente vía el CEDEAR del ETF **`TLT`**), los Fondos Comunes de Inversión LatAm (con bonos de EE. UU., Chile y Brasil rindiendo $4,5\%\text{–}5,0\%$ sin impacto de Ganancias por compraventa para personas humanas) y el bono soberano largo de Brasil **`BR45`** (cuyo umbral de compra atractiva se ubica cuando su TIR se acerca o supera el $7,5\%\text{–}8,0\%$).
* **Regla de Salida hacia Liquidez / Exterior:** Cuando las ONs corporativas argentinas de primera línea (YPF `YM35`, Banco Galicia, Banco Macro, Pampa) comprimen su TIR hacia el rango de $1,0\%\text{ a }4,5\%$ (o cuando los bonos soberanos Hard Dollar tocan mínimos de TIR debajo de $8,5\%\text{–}9,0\%$ a la par de una compresión generalizada), el diferencial sobre $y_{\text{UST}}$ se vuelve nulo o negativo:
  $$\text{Spread}_{\text{Corp vs. UST}} = \text{TIR}_{\text{ON Tier-1}} - y_{\text{UST}} \le 50\text{ bps}$$
  En ese punto, el sistema debe disparar una **Alerta de Desarme por Premio Insuficiente** y sugerir rotar hacia `TLT`, FCI internacional o liquidez hasta que el mercado local depure precios.

### Estrategia 10: Arbitrajes Microestructurales, Dólar MEP Ida/Vuelta, Canje de Renta Cable y Ratio Macro Merval/CER

Esta familia agrupa las reglas de ejecución en tiempo real que determinan la rentabilidad efectiva de la operatoria diaria.

#### Regla 10A: Evaluación Exclusiva sobre Caja de Puntas (`Bid` / `Ask`) vs. Último Operado (`Last`)

En [¿Como saber si estoy pagando caro o barato?](http://www.youtube.com/watch?v=sUSsj5h9Nxw), [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc), [Alternativas al BPY26 (2025) Gus Lucioni](http://www.youtube.com/watch?v=0bdFQ0eRES0), [Canje en ERF25 (2026) Gus Lucioni](http://www.youtube.com/watch?v=KPtQ2ROAtyo) y [Bonos de la Provincia de Neuquén (2025) Gus Lucioni](http://www.youtube.com/watch?v=M426ASSqlww), Lucioni demuestra que en el mercado argentino el precio `Last` (último operado) puede haber ocurrido horas antes o por un monto insignificante, mientras que la caja de puntas actual muestra una realidad completamente distinta. Por ejemplo:
* En `BC37D`, el último operado marca ARS 118.000 ($\text{TIR} = 10,57\%$), pero la punta vendedora (`Ask`) está en ARS 119.990 ($\text{TIR} = 10,23\%$).
* En `BNA6D`, con un valor residual de USD 50, pagar USD 50,99 en la punta vendedora (`Ask`) en lugar de USD 50,46 del último operado desploma la TIR desde $>9,0\%$ hasta $<5,8\%$.
* En las especies `D` (dólares) de títulos ilíquidos (`ERF25D`, `BNA6D`, ONs y bonos CER en `D`), el spread entre punta compradora y vendedora es mucho más amplio que en pesos.

Por lo tanto, **ninguna alerta de arbitraje en la aplicación debe dispararse usando `Last`**. Toda condición de arbitraje entre un Activo A (en cartera o a vender) y un Activo B (a comprar) debe evaluarse estrictamente como:

$$\Delta\text{TIR}_{\text{Ejecutable}} = \text{TIR}\left(\text{Ask}_B\right) - \text{TIR}\left(\text{Bid}_A\right)$$

y debe verificarse que el tamaño disponible en la caja de puntas cumpla $\text{AskSize}_B \ge \text{Lámina Mínima}_B$ y $\text{BidSize}_A \ge \text{Lámina Mínima}_A$.

#### Regla 10B: Arbitraje de Dólar MEP "Ida y Vuelta" (Rulo / Arbitraje de Tipos de Cambio Implícitos)

En la pestaña `MEPs` de la planilla [Copia de Arbitraje Ratios](https://docs.google.com/spreadsheets/d/13p_RLsTPMxfkBnbe7awyfw2cQGyAglh6O96Yhw0Y9dM/edit?usp=drivesdk&ouid=103928833983870106232), se monitorea cada 10 segundos en Contado Inmediato (o plazo normal 24 hs) el tipo de cambio MEP implícito en las puntas de cada activo $i \in \{\text{GD30}, \text{AL30}, \text{Letras}\}$:

* **MEP de Compra de USD ("Ida" con activo $i$):** Se compran nominales en pesos al `Ask` y se venden en dólares (`D`) al `Bid`:
  $$\text{MEP}_{\text{Ida}}(i) = \frac{\text{Ask}_{\text{ARS}, i}}{\text{Bid}_{\text{USD}, i}}$$
* **MEP de Venta de USD ("Vuelta" con activo $j$):** Se compran nominales en dólares (`D`) al `Ask` y se venden en pesos al `Bid`:
  $$\text{MEP}_{\text{Vuelta}}(j) = \frac{\text{Bid}_{\text{ARS}, j}}{\text{Ask}_{\text{USD}, j}}$$

El spread porcentual de arbitraje cambiario cruzado entre el activo $i$ y el activo $j$ es:

$$R_{\text{MEP}}(i \to j) = \left( \frac{\text{MEP}_{\text{Vuelta}}(j)}{\text{MEP}_{\text{Ida}}(i)} - 1 \right) - C_{\text{total}}$$

Cuando $R_{\text{MEP}}(i \to j) > 0$, existe una ganancia neta en pesos (o en dólares) por comprar MEP vía el activo $i$ y vender MEP vía el activo $j$ (o bien indica por cuál papel resulta más barato dolarizar y por cuál resulta más rentable pesificar).

#### Regla 10C: Arbitraje del Canje Cable $\to$ MEP en el Cobro de Cupones y Amortizaciones

En [VSCXO ¿Vale la pena ir tan largo? (2026) Gus Lucioni](http://www.youtube.com/watch?v=xC4tFjouZhU) (minuto `09:18`), se explicita una regla de arbitraje sobre flujos de caja cobrados: cuando un inversor cobra renta o amortización en **Dólar Cable (especie 7.000)** proveniente de cualquier bono u ON Ley Nueva York (`BDC33`, `VSCXO`, `PLC7D`, `MGCRD`, `CO35`, `SJO5D`, `NDG4D`, `GD30`, `GD38`, `GD41`, `GD46`), si solicita al broker la conversión automática a Dólar MEP (especie 10.000), muchos brokers convierten a paridad $1:1$ quedándose con la prima del Canje ($\text{Canje} = \frac{\text{CCL}}{\text{MEP}} - 1 > 0$).

La app debe emitir una **Alerta de Optimización de Cobro en Cable** cada vez que se acredite un cupón en especie 7.000 y el canje implícito en bonos (`GD30C`/`GD30D`) o CEDEARs (`SPY`/`AAPL`/`KO` en `C` vs. `D`) sea positivo:
1. Comprar con los USD Cable un bono en especie `C` (al $\text{Ask}_C$) o un CEDEAR en especie `C`.
2. Vender inmediatamente ese título en especie `D` (al $\text{Bid}_D$), capturando un incremento neto de dólares billete locales:
   $$\text{Ganancia}_{\text{USD MEP}} = \left( \frac{\text{Bid}_D}{\text{Ask}_C} - 1 \right) - C_{\text{comisión}}$$

#### Regla 10D: Ratio Macro de Rotación entre Renta Fija CER y Renta Variable (`Merval / CER` y `GGAL / CER`)

En [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) y [AO29 nuevo Bono soberano en USD con renta mensual](http://www.youtube.com/watch?v=3rScqsNVfT4), el sistema monitorea el cociente entre la renta variable local en pesos y el coeficiente de estabilización de referencia (CER):

$$R_{\text{Merval/CER}}(t) = \frac{\text{Índice Merval}_{\text{ARS}, t}}{\text{CER}_t}, \quad R_{\text{GGAL/CER}}(t) = \frac{P_{\text{GGAL}, t}}{\text{CER}_t}$$

comparándolo contra sus medias móviles históricas de 1, 2, 4 y 5 años:
* Si la curva $R_{\text{Merval/CER}}(t)$ tiene pendiente negativa, la inflación (y por ende la cartera de bonos CER) le está ganando a las acciones.
* Cuando $R_{\text{Merval/CER}}(t)$ cae hasta tocar los **mínimos de los últimos 1 a 2 años** (muy por debajo de su media anual, por ejemplo $40,58$ en la planilla de Lucioni), marca una zona histórica de piso y rebote en términos reales, disparando una alerta de **Rotación Táctica Macro desde Bonos CER hacia Renta Variable (`Merval` / `GGAL`)**.

## Arquitectura de Reglas Lógicas y Especificación Técnica para la IA de Desarrollo

Para que la inteligencia artificial encargada del desarrollo pueda contrastar el código actual de tu aplicación contra las estrategias extraídas del canal de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni), esta sección traduce el análisis financiero a especificaciones de ingeniería de software: modelo de datos de entrada, motor de reglas parametrizado y matriz de auditoría de brechas (*Gap Analysis*).

### Modelo de Datos Requerido por el Motor de Alertas

Muchas aplicaciones de arbitraje fallan o omiten estrategias de Lucioni porque solo ingieren precios (`last`, `bid`, `ask`) sin almacenar los metadatos estructurales de cada bono u ON. El esquema de entidad de cada instrumento (`InstrumentMetadata`) y de cada instantánea de mercado (`OrderBookSnapshot`) debe contener obligatoriamente los siguientes campos:

```json
{
  "InstrumentMetadata": {
    "ticker_ars": "GD41",
    "ticker_mep": "GD41D",
    "ticker_cable": "GD41C",
    "issuer_type": "SOVEREIGN | SUBSOVEREIGN | CORPORATE_ON | BCRA_BOPREAL | EQUITY_INDEX",
    "issuer_group": "REPUBLICA_ARGENTINA | CABA | NEUQUEN | CORDOBA | PBA | GRUPO_YPF | GRUPO_ALBANESI | GRUPO_IRSA | VISTA | PLUSPETROL | PAMPA",
    "governing_law": "NY | ARG",
    "indenture_year": 2005,
    "adjustment_clause": "HARD_DOLLAR | CER | TAMAR | BADLAR | DUAL_TAMAR_CER | DOLLAR_LINKED | FIXED_ARS",
    "payment_currency": "USD_CABLE_7000 | USD_MEP_10000 | ARS",
    "coupon_frequency": "MONTHLY | QUARTERLY | SEMIANNUAL | ANNUAL | ZERO_COUPON",
    "coupon_months": [1, 7],
    "annual_coupon_rate": 0.035,
    "amortization_type": "BULLET | SINKING_FUND",
    "first_principal_payment_date": "2028-01-09",
    "maturity_date": "2041-07-09",
    "residual_value_factor": 1.00,
    "min_denomination_vn": 1,
    "lot_multiple_vn": 1,
    "callable_flag": false,
    "historical_stress_max_tir": 0.27,
    "historical_bull_min_tir": 0.083,
    "cross_election_boundary_2027": true
  },
  "OrderBookSnapshot": {
    "timestamp_utc": "2026-11-11T15:00:00Z",
    "settlement_term": "CI | 24HS",
    "bid_price": 113200.0,
    "bid_size_vn": 25000,
    "ask_price": 113500.0,
    "ask_size_vn": 18000,
    "last_price": 113400.0,
    "tir_at_bid": 0.0965,
    "tir_at_ask": 0.0958,
    "parity_at_bid": 0.6960,
    "parity_at_ask": 0.6979,
    "modified_duration": 5.71,
    "technical_value": 105.85
  }
}
```

### Catálogo de Reglas Algorítmicas (Pseudocódigo de Detección para la IA)

A continuación se definen las 12 reglas formales que la IA desarrolladora debe verificar e implementar en el motor de evaluación en tiempo real:

```python
# REGLA 01: Filtro universal de liquidez y cálculo sobre puntas operables (Nunca usar LAST)
def get_executable_metrics(snapshot, min_capital_usd, fx_rate):
    # Verifica que el volumen en la punta cubra el mínimo operable y la lámina mínima
    valid_bid = (snapshot.bid_price > 0) and (snapshot.bid_size_vn >= snapshot.meta.min_denomination_vn)
    valid_ask = (snapshot.ask_price > 0) and (snapshot.ask_size_vn >= snapshot.meta.min_denomination_vn)
    # Descarta distorsiones cuando el bid-ask spread de TIR supera el umbral de iliquidez (ej. > 150 bps en cortos)
    spread_tir_bps = (snapshot.tir_at_bid - snapshot.tir_at_ask) * 10000
    return valid_bid, valid_ask, spread_tir_bps

# REGLA 02: Arbitraje Estadístico de Legislación (GD vs AL/AE con Bollinger 21 ruedas +/- 1.5 sigma)
def check_legislation_arbitrage(gd_snap, al_snap, ratio_history_21d, roundtrip_fee=0.005):
    ratio_sell_gd_buy_al = (gd_snap.bid_price / al_snap.ask_price) - 1.0
    ratio_sell_al_buy_gd = (gd_snap.ask_price / al_snap.bid_price) - 1.0
    mu_21 = mean(ratio_history_21d)
    sigma_21 = std(ratio_history_21d)
    upper_band = mu_21 + 1.5 * sigma_21
    lower_band = mu_21 - 1.5 * sigma_21
    tir_spread_bps = (al_snap.tir_at_ask - gd_snap.tir_at_bid) * 10000

    # Caso A: Ambos rinden casi igual -> Prohibido estar en Ley Local, migrar a Ley NY
    if tir_spread_bps <= 50 or ratio_sell_al_buy_gd <= lower_band:
        return Alert("ROTAR_AL_A_GD", pair=(al_snap.ticker, gd_snap.ticker),
                     reason=f"Upgrade barato a Ley NY + Cable: Ratio={ratio_sell_al_buy_gd:.2%}, Spread TIR={tir_spread_bps:.0f} bps")

    # Caso B: Ratio rompe Banda Superior o Spread de TIR > 200 bps (ej. GD38/AE38 > 1.03)
    if (ratio_sell_gd_buy_al >= upper_band and (ratio_sell_gd_buy_al - mu_21) > roundtrip_fee) or tir_spread_bps >= 200:
        return Alert("ROTAR_GD_A_AL", pair=(gd_snap.ticker, al_snap.ticker),
                     reason=f"Ganar nominales en Ley Local: Ratio={ratio_sell_gd_buy_al:.2%} > BS={upper_band:.2%}, Spread TIR={tir_spread_bps:.0f} bps")

# REGLA 03: Desarbitraje Intra-Curva CER por Inversión de Pendiente / Duration (TX31 vs DICP)
def check_tx31_dicp_arbitrage(tx31_snap, dicp_snap):
    # TX31 tiene menor Modified Duration (2.62) y menor Maturity (2031) que DICP (3.08, 2033)
    tir_diff_bps = (tx31_snap.tir_at_ask - dicp_snap.tir_at_bid) * 10000
    if tir_diff_bps >= 60:
        return Alert("DESARBITRAJE_DICP_A_TX31",
                     reason=f"Anomalía de pendiente CER: TX31 (menor MD={tx31_snap.modified_duration}) rinde +{tir_diff_bps:.0f} bps más que DICP")
    # Cuando las TIR convergen (diferencia <= 35 bps), conviene volver 50% a DICP por su cupón de 5.83% vs 2.50%
    rev_diff_bps = abs(tx31_snap.tir_at_bid - dicp_snap.tir_at_ask) * 10000
    if rev_diff_bps <= 35:
        return Alert("CONVERGENCIA_TX31_A_DICP",
                     reason=f"TIRs igualadas (dif={rev_diff_bps:.0f} bps): rotar 50% de TX31 a DICP para capturar cupón de 5.83% TNA")

# REGLA 04: Electrocardiograma de Bonos CER Cupón Cero Contiguos (TZXS8 vs TZX28 y TZXS7 vs TZXS8)
def check_zero_coupon_cer_pairs(tzx28_snap, tzxs8_snap, tzxs7_snap, tzxo7_snap):
    spread_s8_28_bps = (tzxs8_snap.tir_at_ask - tzx28_snap.tir_at_bid) * 10000
    if spread_s8_28_bps >= 80:
        return Alert("ROTAR_TZX28_A_TZXS8",
                     reason=f"TZXS8 rinde +{spread_s8_28_bps:.0f} bps por solo 3 meses más y da ventana de pass-through postelectoral")
    if (tzxs8_snap.tir_at_bid - tzx28_snap.tir_at_ask) * 10000 <= 25:
        return Alert("ROTAR_TZXS8_A_TZX28",
                     reason="Spread TZXS8-TZX28 comprimido a <= 25 bps: acortar duration hacia TZX28")

    # Escalón electoral TZXS7 (pre-elecciones) vs TZXS8 (post-elecciones)
    parity_ratio_s7_s8 = (tzxs7_snap.parity_at_ask / tzxs8_snap.parity_at_bid) - 1.0
    tir_gap_s8_s7_bps = (tzxs8_snap.tir_at_bid - tzxs7_snap.tir_at_ask) * 10000
    if parity_ratio_s7_s8 <= 0.092 and tir_gap_s8_s7_bps <= 225:
        return Alert("ROTAR_TZXS8_A_TZXS7_DEFENSIVO",
                     reason=f"Prima electoral en mínimos (Paridad +{parity_ratio_s7_s8:.2%}, Spread TIR {tir_gap_s8_s7_bps:.0f} bps): eliminar riesgo electoral")

# REGLA 05: Arbitraje Cross-Asset Soberano (Curva CER vs Curva Hard Dollar igual Duration)
def check_cross_asset_cer_hd(cer_snap, hd_snap, fx_distance_to_upper_band_pct):
    # Pares: (PARP, GD41), (DICP, AE38), (TX31, AL30)
    # Anomalía 1: Bono CER rinde más TIR que Bono Hard Dollar
    if cer_snap.tir_at_ask > hd_snap.tir_at_bid:
        return Alert("ANOMALIA_ROTAR_HD_A_CER", pair=(hd_snap.ticker, cer_snap.ticker),
                     reason=f"Inversión extrema: {cer_snap.ticker} (TIR={cer_snap.tir_at_ask:.2%}) rinde más que {hd_snap.ticker} (TIR={hd_snap.tir_at_bid:.2%})")
    # Anomalía 2: CER comprimió fuerte (< 7.5% en largos) y HD quedó rezagado con spread > 250 bps y dólar lejos del techo
    if (hd_snap.tir_at_ask - cer_snap.tir_at_bid) * 10000 >= 250 and cer_snap.tir_at_bid <= 0.075 and fx_distance_to_upper_band_pct > 0.05:
        return Alert("ROTAR_CER_A_HD", pair=(cer_snap.ticker, hd_snap.ticker),
                     reason=f"Compresión CER agotada y brecha de TIR de {(hd_snap.tir_at_ask - cer_snap.tir_at_bid)*10000:.0f} bps a favor de Hard Dollar")

# REGLA 06: Arbitraje de Frecuencia de Flujo y Ventana Política en Nuevos Soberanos (AO29 vs AN29 vs AO28)
def check_new_sovereigns_usd(ao29_snap, an29_snap, ao28_snap):
    # AO29 paga 0.5% TODOS LOS MESES; AN29 paga semestralmente
    if (an29_snap.tir_at_bid - ao29_snap.tir_at_ask) * 10000 <= 75:
        return Alert("PREFERIR_AO29_SOBRE_AN29",
                     reason="TIR casi idéntica pero AO29 paga flujo mensual (0.5%/mes), cobrando más USD antes de las elecciones de 2027")
    # AO28 y AO29 comparten el mismo riesgo electoral 2027; si AO29 rinde más que AO28, pasar a AO29
    if ao29_snap.tir_at_ask > ao28_snap.tir_at_bid:
        return Alert("ROTAR_AO28_A_AO29",
                     reason="Mismo riesgo electoral 2027 pero mayor TIR y mayor TNA asegurada por un año adicional en AO29")

# REGLA 07: Arbitraje Corporativo Intra-Grupo Empresario e Intra-Emisor (ONs)
def check_corporate_on_arbitrage(on_a_snap, on_b_snap, roundtrip_fee=0.005):
    # Sub-regla 7.1: Mismo grupo empresario e idéntico flujo (ej. MR36O vs LECH0, o DICP vs DIP0)
    if on_a_snap.meta.issuer_group == on_b_snap.meta.issuer_group and on_a_snap.meta.cashflow_hash == on_b_snap.meta.cashflow_hash:
        net_vn_gain = (on_a_snap.bid_price * (1 - roundtrip_fee)) / (on_b_snap.ask_price * (1 + roundtrip_fee)) - 1.0
        if net_vn_gain >= 0.01:
            return Alert("ARBITRAJE_VN_COSTO_CERO", pair=(on_a_snap.ticker, on_b_snap.ticker),
                         reason=f"Mismo grupo y flujo: vender {on_a_snap.ticker} y comprar {on_b_snap.ticker} suma +{net_vn_gain:.2%} nominales gratis")

    # Sub-regla 7.2: Mismo grupo y mismos meses de pago con diferencial de TIR (ej. YMCJO vs YFCJO)
    if on_a_snap.meta.issuer_group == on_b_snap.meta.issuer_group and on_a_snap.meta.coupon_months == on_b_snap.meta.coupon_months:
        tir_gain_bps = (on_b_snap.tir_at_ask - on_a_snap.tir_at_bid) * 10000
        if tir_gain_bps >= 50:
            return Alert("ROTAR_ON_MISMO_MES", pair=(on_a_snap.ticker, on_b_snap.ticker),
                         reason=f"Mismo grupo ({on_a_snap.meta.issuer_group}) y meses de pago: +{tir_gain_bps:.0f} bps rotando a {on_b_snap.ticker}")

    # Sub-regla 7.3: Mismo emisor, estructura Bullet más corta vs Amortizable más larga (ej. YM39D jul-2030 vs YM34D 2034)
    if (on_a_snap.meta.issuer_group == on_b_snap.meta.issuer_group and
        on_b_snap.meta.amortization_type == "BULLET" and
        on_b_snap.meta.maturity_date < on_a_snap.meta.maturity_date and
        on_b_snap.tir_at_ask >= on_a_snap.tir_at_bid - 0.0025):
        return Alert("DOMINANCIA_ON_BULLET_CORTA", pair=(on_a_snap.ticker, on_b_snap.ticker),
                     reason=f"{on_b_snap.ticker} vence antes, es Bullet, tiene mayor cupón y rinde igual o más TIR que {on_a_snap.ticker}")

# REGLA 08: Arbitraje de Dolarización Corta Pre-Electoral (YM37D / OZC3O vs Soberano AO27 / BPY26)
def check_short_usd_pre_election(corp_short_snap, ao27_snap):
    if (not corp_short_snap.meta.cross_election_boundary_2027 and
        (corp_short_snap.tir_at_ask - ao27_snap.tir_at_bid) * 10000 >= 250 and
        corp_short_snap.parity_at_ask <= 1.02):
        return Alert("DOLARIZACION_CORTA_CORP_VS_AO27", pair=(ao27_snap.ticker, corp_short_snap.ticker),
                     reason=f"{corp_short_snap.ticker} vence antes de elecciones y rinde +{(corp_short_snap.tir_at_ask - ao27_snap.tir_at_bid)*10000:.0f} bps sobre AO27")

# REGLA 09: Opcionalidad Gratuita en Bonos Duales (Dual TAMAR/CER vs BADLAR/TAMAR Puro como PR17)
def check_dual_bond_optionality(dual_snap_tamar_tir, pure_float_snap):
    if (dual_snap_tamar_tir - pure_float_snap.tir_at_bid) * 10000 >= -50:
        return Alert("OPCIONALIDAD_GRATUITA_BONO_DUAL",
                     reason="El Bono Dual rinde en versión TAMAR igual o más que el flotante puro (PR17/TAMAR), entregando gratis la cobertura CER")
```

### Matriz de Auditoría de Brechas (Checklist de Verificación para tu App Actual)

Al pasarle este informe a la inteligencia artificial que desarrolla tu aplicación de alertas, instruila para que audite su propio código fuente contra los 15 puntos de control de la siguiente tabla. Los puntos desde el `#04` hasta el `#15` suelen ser los que faltan en las aplicaciones convencionales centradas únicamente en el ratio `GD30/AL30` o en arbitrajes cambiarios simples:

| # | Módulo / Tipo de Arbitraje a Verificar en la App | Qué suelen hacer las Apps básicas | Qué exige la lógica de Gustavo Lucioni | Prioridad de Implementación |
| :--- | :--- | :--- | :--- | :--- |
| **01** | **Fuente de Precio para TIR y Ratios** | Calculan TIR y ratios usando el último precio operado (`Last`). | Calcular estrictamente sobre **puntas operables** (`Ask` para comprar, `Bid` para vender) y filtrar si `AskSize` no cubre la lámina mínima ([¿Como saber si estoy pagando caro o barato?](http://www.youtube.com/watch?v=sUSsj5h9Nxw)). | **CRÍTICA** |
| **02** | **Ratio de Legislación (`GD` vs. `AL`/`AE`)** | Solo monitorean `GD30/AL30` con umbrales fijos. | Monitorear toda la curva (`29`, `30`, `35`, `38`, `41`) con **Bandas de Bollinger dinámicas ($MM_{21} \pm 1,5\sigma$)**, detectar divergencias `GD30` vs. largos y bloquear Ley Local si $\Delta\text{TIR} \le 50\text{ bps}$ ([Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc)). | **ALTA** |
| **03** | **Desarbitraje Intra-Curva CER (`TX31` vs. `DICP`)** | No comparan bonos CER amortizables entre sí ajustados por *duration*. | Alertar rotación `DICP` $\to$ `TX31` cuando $\text{TIR}_{\text{TX31}} > \text{TIR}_{\text{DICP}} + 60\text{ bps}$ (menor *duration* y mayor tasa), y regreso `TX31` $\to$ `DICP` cuando las TIR se igualan para capturar el cupón de $5,83\%$ ([¿TX31 o DICP?](http://www.youtube.com/watch?v=UtqZ3XpyJHE)). | **ALTA** |
| **04** | **Electrocardiograma CER Cupón Cero (`TZXS8` vs. `TZX28` y `TZXM9`)** | Tratan cada Lecap/Boncer como un activo aislado. | Monitorear el spread de TIR entre vencimientos contiguos (umbral $\ge 80\text{–}100\text{ bps}$ para ir a `TZXS8`, $\le 25\text{ bps}$ para volver a `TZX28`) y ponderar la ventana de *pass-through* postelectoral ([Nuevo Bono de Chubut](http://www.youtube.com/watch?v=-PXxoj8HZFU)). | **ALTA** |
| **05** | **Escalón de Riesgo Electoral (`TZXS7` vs. `TZXS8` y `AO27` vs. `AO28`/`AO29`)** | Ignoran la fecha de cambio de mandato presidencial. | Etiquetar cada activo con un booleano `cross_election_boundary` y medir la prima de paridad/TIR entre el último bono del mandato actual y el primero del mandato siguiente ([Nuevo Bono TZXO7](http://www.youtube.com/watch?v=xjvXqUOxTLM)). | **ALTA** |
| **06** | **Arbitraje Cross-Asset Soberano (`CER` $\leftrightarrow$ `Hard Dollar`)** | Separan los tableros de pesos y de dólares sin cruzarlos. | Cruzar pares de igual *Modified Duration* (`PARP` vs. `GD41`, `DICP` vs. `AE38`, `TX31` vs. `AL30`): si $\text{TIR}_{\text{CER}} > \text{TIR}_{\text{HD}}$ alertar pase a CER; si $\text{TIR}_{\text{HD}} - \text{TIR}_{\text{CER}} \ge 250\text{ bps}$ con CER $<7,5\%$ alertar dolarización ([Rotar de HD a CER](http://www.youtube.com/watch?v=GGXMEcxL7yY)). | **CRÍTICA** |
| **07** | **Simulador de Sensibilidad con TIR Cruzada** | Calculan sensibilidad asumiendo la misma TIR objetivo para todos los bonos. | Implementar motor de escenarios con **TIR objetivo diferenciada por ley/emisor** (ej. 8% NY, 9% ARG, 12% PBA) y **TIR de estrés histórica individual** (27% `AL41`, 33% `AE38`, 30% `BB37D`) para rankear por ratio *Upside/Downside* ([On de YPF + Simulación PBA](http://www.youtube.com/watch?v=szbHhfNKLuw)). | **ALTA** |
| **08** | **Frecuencia de Pago en Soberanos Nuevos (`AO29` vs. `AN29`)** | Ordenan solo por TIR anualizada (eligiendo `AN29` por 20–40 bps más). | Penalizar el pago semestral frente al **pago mensual del 0,5%** del `AO29` y calcular cuántos dólares efectivos se cobran antes de las elecciones ([¿AO29 o AN29?](http://www.youtube.com/watch?v=iI_l2kb973c)). | **MEDIA** |
| **09** | **Gemelos Corporativos Intra-Grupo (`MR36O`/`LECH0`, `YMCJO`/`YFCJO`, `YM39D`/`YM34D`)** | No agrupan las ONs por grupo económico ni por mes de pago de cupón. | Agrupar ONs por `issuer_group` y `coupon_months`; alertar cuando se pueden ganar nominales gratis (`MR36O` $\to$ `LECH0`), ganar +50–100 bps en el mismo mes (`YMCJO` $\to$ `YFCJO`) o pasar de amortizable a *bullet* más corta con mayor cupón (`YM34D` $\to$ `YM39D`) ([Pasar de MR36O a LECH0](https://mercapsoftware.com/oportunidad-pasar-de-mr36o-a-lech0/)). | **CRÍTICA** |
| **10** | **Dolarización Corta Minorista (`YM37D` / `OZC3O` vs. `AO27` / `BPY26`)** | No comparan ONs cortas contra soberanos cortos / BOPREAL. | Alertar cuando una ON Tier-1 que vence antes de las elecciones (`YM37D` mayo-2027, TIR 6,37%) supera en $+300\text{ bps}$ al soberano corto `AO27` (TIR 2,9%) ([YM37D ¿Oportunidad Conservadora?](http://www.youtube.com/watch?v=Nbksr1IE7pU)). | **ALTA** |
| **11** | **Factor de Capital Residual y Rechazo de Canjes (`ERF25`, `BNA6D`, `NDT25`)** | No rastrean el porcentaje de capital ya amortizado ($1 - VR_t$). | Incorporar `residual_value_factor`: priorizar subsoberanos con $VR_t \le 55\%$, alertar rechazo de canjes que extienden *duration* sin premio (`ERF25`) y alertar venta cuando un provincial comprime debajo de un soberano comparable (`NDT25` vs. `AL29D`) ([Canje en ERF25](http://www.youtube.com/watch?v=KPtQ2ROAtyo)). | **MEDIA** |
| **12** | **Restricción de Lámina Mínima y Regla del 7% Cable (`MGCRD` vs. `PLC7D`/`SJO5D`)** | Recomiendan bonos/ONs sin verificar si exigen 10.000 nominales. | Filtrar por `min_denomination_vn`: ofrecer reemplazo automático de `MGCRD` (10.000 VN) por `PLC7D` (1.000 VN) y de `CO35` (10.000 VN) por `SJO5D`/`NDG4D` (1.000 VN) cuando superan el 7% de TIR Cable ([Cashflow mensual en USD Cable](http://www.youtube.com/watch?v=KoLLc-AHGG0)). | **MEDIA** |
| **13** | **Opcionalidad en Bonos Duales (`TXMD8`/`TXMJ8` vs. `PR17` y `PBA27` vs. `TML27`)** | Valúan los Duales bajo una sola curva. | Calcular la doble TIR del Dual (versión CER y versión TAMAR); alertar cuando $\text{TIR}_{\text{Dual-TAMAR}} \ge \text{TIR}_{\text{PR17}}$ (cobertura CER gratis) y cuando `PBA27` ($\text{TAMAR} + 733\text{ bps}$) supera en $>400\text{ bps}$ a los TAMAR del Tesoro ([Curva de Bonos duales](http://www.youtube.com/watch?v=W82Ml-x-axM)). | **ALTA** |
| **14** | **Piso contra Plazo Fijo UVA y contra US Treasuries (`TLT` / `BR45`)** | Siguen sugiriendo compra cuando toda la curva comprimió. | Bloquear compra de CER cortos si $\text{TIR}_{\text{neta}} < \text{UVA}$, y alertar rotación a liquidez / `TLT` / `BR45` si las ONs Tier-1 comprimen a $\le 5,0\%$ de TIR ([¿Permanecer Líquido es Opción?](http://www.youtube.com/watch?v=Rh3t_OTUbwg)). | **MEDIA** |
| **15** | **Arbitraje de Cobro en Dólar Cable (Especie `C` $\to$ `D`) y Ratio `Merval/CER`** | Ignoran el diferencial Cable/MEP al cobrar renta y el ciclo Acciones/CER. | Emitir alerta en fecha de pago de cupones Ley NY para arbitrar los USD Cable vía compra en `C` y venta en `D`, y monitorear el cociente $\text{Merval}/\text{CER}$ contra su media de 1 y 2 años ([VSCXO ¿Vale la pena ir tan largo?](http://www.youtube.com/watch?v=xC4tFjouZhU)). | **MEDIA** |

## Conclusiones y Directrices de Integración para el Sistema de Desarrollo

La sistematización del repertorio analítico de [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni) demuestra que un sistema profesional de alertas de arbitraje para el mercado argentino de capitales no puede limitarse a evaluar diferencias estáticas de precios entre un único par de bonos soberanos. La ventaja competitiva del enfoque relevado reside en combinar el monitoreo de ratios de precios en tiempo real sobre puntas ejecutables (`Bid`/`Ask`) con el análisis multidimensional de flujos de fondos descontados: diferenciales de TIR ajustados por *Modified Duration*, cruces inter-curva entre pesos indexados (CER), tasas flotantes (TAMAR/BADLAR/Duales) y dólares (MEP/Cable), simulaciones de sensibilidad con tasas objetivo cruzadas, y filtros microestructurales de lámina mínima, capital residual y riesgo político-electoral.

Al inyectar este documento como especificación de entrada en la inteligencia artificial encargada del desarrollo de la aplicación, se recomienda ejecutar primero un diagnóstico automatizado contra la **Matriz de Auditoría de Brechas** (verificando qué campos de `InstrumentMetadata` aún no existen en la base de datos de la app) y luego desplegar secuencialmente los módulos de reglas desde las anomalías de ejecución inmediata (Reglas 01, 02, 03, 04 y 07) hacia los simuladores de rotación táctica y sensibilidad cruzada (Reglas 05, 06, 08 y 09).

## Referencias Documentales y Fuentes Verificadas

* **Canal Oficial de YouTube:** [Gustavo Lucioni (@GustavoLucioni)](https://www.youtube.com/@GustavoLucioni) — [Listado de Videos del Canal](https://www.youtube.com/channel/UCmlHXBbRdn_xe983dGdCqjQ/videos).
* **Videos Analizados con Transcripción Completa:**
  * [PLC7D arriba de 7% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=J2CDL8nu9fs) (Publicado el 4 de noviembre de 2026).
  * [YM37D ¿Oportunidad Conservadora? (2026) Gus Lucioni](http://www.youtube.com/watch?v=Nbksr1IE7pU) (Publicado el 30 de octubre de 2026).
  * [Opciones en Pesos y en USD de Corto Plazo (2026) Gus Lucioni](http://www.youtube.com/watch?v=YAnMRRLCleE) (Publicado el 21 de octubre de 2026).
  * [VSCXO ¿Vale la pena ir tan largo? (2026) Gus Lucioni](http://www.youtube.com/watch?v=xC4tFjouZhU) (Publicado el 15 de octubre de 2026).
  * [Tenemos un nuevo sub soberano. Cupón del 9.55% anual en USD y ley Ny](http://www.youtube.com/watch?v=FsOv7TBEAh0) (Publicado el 13 de octubre de 2026).
  * [Cashflow mensual en USD Cable arriba del 7% Anual (2026) Gus Lucioni](http://www.youtube.com/watch?v=KoLLc-AHGG0) (Publicado el 6 de octubre de 2026).
  * [¿TX31 o DICP? (2026) Gus Lucioni](http://www.youtube.com/watch?v=UtqZ3XpyJHE) (Publicado el 28 de septiembre de 2026).
  * [Curva de Bonos duales como CER y TAMAR](http://www.youtube.com/watch?v=W82Ml-x-axM) (Publicado el 18 de septiembre de 2026).
  * [¿AO29 o AN29? (2026) Gus Lucioni](http://www.youtube.com/watch?v=iI_l2kb973c) (Publicado el 14 de septiembre de 2026).
  * [¿Se viene el Rebote? (2026) Gus Lucioni](http://www.youtube.com/watch?v=xbpulrQpAB4) (Publicado el 24 de agosto de 2026).
  * [TIR de la cartera de Bonos CER y TAMAR/TASA FIJA](http://www.youtube.com/watch?v=19qYECYckp0) (Publicado el 8 de agosto de 2026).
  * [TZXM9 arriba de 9% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=6b-217uVgoM) (Publicado el 6 de agosto de 2026).
  * [¿Como saber si estoy pagando caro o barato?](http://www.youtube.com/watch?v=sUSsj5h9Nxw) (Publicado el 2 de agosto de 2026).
  * [Los nuevos Bonos PBA 27 y 28 (2026) Gus Lucioni](http://www.youtube.com/watch?v=nQd8O7IoLxE) (Publicado el 31 de julio de 2026).
  * [AO29 nuevo Bono soberano en USD con renta mensual](http://www.youtube.com/watch?v=3rScqsNVfT4) (Publicado el 19 de julio de 2026).
  * [Nuevo Bono TZXO7 (2026) Gus Lucioni](http://www.youtube.com/watch?v=xjvXqUOxTLM) (Publicado el 2 de julio de 2026).
  * [Bonos del Tesoro (2026) Gus Lucioni](http://www.youtube.com/watch?v=25uYIk7URNs) (Publicado el 26 de mayo de 2026).
  * [Nuevo Bono de Chubut (2026) Gus Lucioni](http://www.youtube.com/watch?v=-PXxoj8HZFU) (Publicado el 13 de mayo de 2026).
  * [¿TZXS8 o TZX28? (2026) Gus Lucioni](http://www.youtube.com/watch?v=NKLjxmYOK4Q) (Publicado el 7 de mayo de 2026).
  * [¿Permanecer Líquido es Opción? (2026) Gus Lucioni](http://www.youtube.com/watch?v=Rh3t_OTUbwg) (Publicado el 15 de abril de 2026).
  * [PARP abajo de 8% de TIR (2026) Gus Lucioni](http://www.youtube.com/watch?v=KTQlxbVUPJI) (Publicado el 10 de abril de 2026).
  * [PR17 Alternativa en Pesos (2026) Gus Lucioni](http://www.youtube.com/watch?v=_oSDzanYRJk) (Publicado el 25 de marzo de 2026).
  * [¿Momento de rotar Bonos CER a Bonos en USD? (2026) Gus Lucioni](http://www.youtube.com/watch?v=_GG5fkS0xi8) (Publicado el 20 de marzo de 2026).
  * [Canje en ERF25 (2026) Gus Lucioni](http://www.youtube.com/watch?v=KPtQ2ROAtyo) (Publicado el 27 de febrero de 2026).
  * [Cartera de Cashflow ¿AE38 o GD46? (2026) Gus Lucioni](http://www.youtube.com/watch?v=wyUa64aHGcQ) (Publicado el 22 de enero de 2026).
  * [Sumamos Bonos en pesos a la Cartera de Cashflow (2025) Gus Lucioni](http://www.youtube.com/watch?v=CzfEpVxJ0_E) (Publicado el 29 de diciembre de 2025).
  * [Sumamos dos Nuevos Bonos a la Cartera (2025) Gus Lucioni](http://www.youtube.com/watch?v=ek111LGCrh8) (Publicado el 19 de diciembre de 2025).
  * [Agregamos dos nuevos bonos a la Cartera de Cashflow (2025) Gus Lucioni](http://www.youtube.com/watch?v=fys2jlXdSf4) (Publicado el 10 de diciembre de 2025).
  * [Cashflow Mensual ¿Volvimos? (2025) Gus Lucioni](http://www.youtube.com/watch?v=W5VDd02Q00c) (Publicado el 3 de diciembre de 2025).
  * [On de Sami ¿Oportunidad o alto Riesgo? (2025) Gus Lucioni](http://www.youtube.com/watch?v=wQGXzZaaOnM) (Publicado el 27 de noviembre de 2025).
  * [Bonos de la Provincia de Neuquén (2025) Gus Lucioni](http://www.youtube.com/watch?v=M426ASSqlww) (Publicado el 21 de noviembre de 2025).
  * [On de YPF + Simulación Globales y Bonos de PBA (2025) Gus Lucioni](http://www.youtube.com/watch?v=szbHhfNKLuw) (Publicado el 26 de septiembre de 2025).
  * [AE38 quedo Relegado Nuevamente (2025) Gus Lucioni](http://www.youtube.com/watch?v=Wuz2yBw8ECk) (Publicado el 16 de septiembre de 2025).
  * [ON de Cresud para Cashflow (2025) Gus Lucioni](http://www.youtube.com/watch?v=PT6FDlf28ro) (Publicado el 12 de septiembre de 2025).
  * [Rotar de HD a CER ¿Sigue siendo Oportunidad? (2025) Gus Lucioni](http://www.youtube.com/watch?v=GGXMEcxL7yY) (Publicado el 2 de septiembre de 2025).
  * [GD41 ¿El Mejor de los Globales? (2025) Gus Lucioni](http://www.youtube.com/watch?v=8yXP9CoAPGE) (Publicado el 19 de agosto de 2025).
  * [Bonos Hard Dólar: ¿Cuáles tienen mayor Potencial de Suba? (2025) Gus Lucioni](http://www.youtube.com/watch?v=RpRWXd7hXXo) (Publicado el 15 de agosto de 2025).
  * [¿Alternativa Interesante para quienes buscan Cashflow? (2025) Gus Lucioni](http://www.youtube.com/watch?v=F2Z5Cx36ilg) (Publicado el 5 de agosto de 2025).
  * [Alternativas al BPY26 (2025) Gus Lucioni](http://www.youtube.com/watch?v=0bdFQ0eRES0) (Publicado el 23 de julio de 2025).
  * [Planilla de Bonardos. Trading de Ratios](http://www.youtube.com/watch?v=OWagoKseHNc) (Publicado el 3 de julio de 2025).
  * [¿Tengo un Bono en USD favorito? (2025) Gus Lucioni](http://www.youtube.com/watch?v=ok2pA7OZer8) (Publicado el 25 de junio de 2025).
  * [¿Oportunidad para rotar de YMCJO a YFCJO? (2025) Gus Lucioni](http://www.youtube.com/watch?v=1c7nQR6f3V4) (Publicado el 17 de junio de 2025).
* **Artículos Técnicos de Mercap Abbaco y Planillas de Arbitraje en Google Workspace:**
  * [Mercap Software — ¿Oportunidad? Pasar de MR36O a LECH0](https://mercapsoftware.com/oportunidad-pasar-de-mr36o-a-lech0/) y [Correo de ABBACO del 20/01/2025](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1821783958137677943).
  * [Correo de ABBACO — ON de Pluspetrol, bonos provinciales y la brecha entre TX31 y DICP (06/11/2026)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1881153359753625721).
  * [Correo de ABBACO — Bonos en dólares y en pesos de cara a las elecciones: CO35, YM37D y PBA27 (04/11/2026)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1880960515560373717).
  * [Correo de ABBACO — Alternativas de inversión a corto plazo tras la amortización del TOP 26 (22/10/2026)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1879778499738269311).
  * [Correo de ABBACO — Cartera en dólares cable: cómo armar un flujo mensual superior al 7% anual (06/10/2026)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1878324733101280393).
  * [Correo de ABBACO — Bonos en baja: ¿hay desarbitraje entre TX31 y DICP, y oportunidad en la brecha ley local-extranjera? (03/10/2026)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1878047353635792822).
  * [Correo de ABBACO — Rebote en bonos en dólares: AL41 y GD46 como las mejores alternativas de la curva (26/08/2026)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1874613836321084270).
  * [Correo de ABBACO — Carry trade hasta agosto: ¿buena estrategia? y diferencial YM34O vs. YMCJO (12/05/2025)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1831955992915347520).
  * [Correo de ABBACO — Cash-flow en dólares: ¿momento de vender el GD46? (27/12/2024)](https://mail.google.com/mail/?authuser=marcelolauret@gmail.com#all/thread-f:1819617300032268661).
  * [Planilla de Google Sheets — Arbitraje Ratios (Martín Masella / Gus Lucioni)](https://docs.google.com/spreadsheets/d/1W2kTK4n10-fKWYRJmoffOnxdaibkL-7I5wduSHVlGvI/edit?usp=drivesdk&ouid=103928833983870106232).
  * [Planilla de Google Sheets — Copia de Arbitraje Ratios (Pestañas Ratio GD30/AL30, Intraday y MEPs)](https://docs.google.com/spreadsheets/d/13p_RLsTPMxfkBnbe7awyfw2cQGyAglh6O96Yhw0Y9dM/edit?usp=drivesdk&ouid=103928833983870106232).
