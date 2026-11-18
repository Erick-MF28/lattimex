# SENDA5: versión actual y resultados auditados

*[English](en/SENDA5.md)*

La versión 1.3.0 incorpora **SENDA5 con reloj corregido** (motor `lattimex-engine-1.9.0`).
Es el candidato medido el 15 de noviembre de 2026: búsqueda local sobre los clientes reinsertados
cada tres iteraciones y eliminación de rutas en flota libre cuando el arranque tiene menos de siete
clientes por ruta. El pulido inicial cuenta dentro del presupuesto; el pulido final reserva como
máximo 0.5 s y devuelve al bucle el tiempo sobrante. Los parámetros quedan fijos en el fuente.
SENDA4 es un antecedente experimental; el núcleo integrado es SENDA5.

## Evidencia principal: la última versión, a 4 s

100 instancias X, 100–1,000 clientes, CVRP sin ventanas, flota libre, un hilo, una corrida por
herramienta e instancia (700 ensayos). Se midió desde antes de leer la instancia hasta disponer de
las rutas: incluye procesos externos/JVM, excluye iniciar Python e importar bibliotecas. La
calibración por herramienta e instancia resta su exceso de tiempo y 0.02 s de margen al límite.
SENDA5 usa SENDA2 por debajo de 125 nodos, incluido el depósito.

**SENDA5 presenta menor brecha que FILO2, HGS, PyVRP, OR-Tools y vecino más cercano; frente a AILS-II
no se detecta diferencia significativa.** El término «empate» del contrato no demuestra equivalencia.
Las afirmaciones corresponden a esta muestra y configuración, con una corrida por instancia.

La tabla principal usa las referencias de [CVRPLIB consultadas el 17 de noviembre de 2026](https://galgos.inf.puc-rio.br/cvrplib/en/instances).
Se recalcularon los gaps de los mismos costos; no son corridas nuevas. Se conserva la columna del
contrato para distinguir el resultado original del recálculo con referencias actuales.

| Herramienta | Brecha media, BKS actual (%) | Brecha media, contrato (%) | Sin solución / 100 |
|---|---:|---:|---:|
| **SENDA5** | **0.534** | **0.531** | **0** |
| AILS-II | 0.581 | 0.578 | 0 |
| FILO2 | 0.707 | 0.704 | 0 |
| HGS | 1.694 | 1.691 | 2 |
| PyVRP | 2.210 | 2.207 | 0 |
| OR-Tools | 7.810 | 7.806 | 0 |
| Vecino más cercano | 25.105 | 25.102 | 0 |

**Denominador de ambas medias: 98 instancias comunes a las siete herramientas.** HGS no entregó
solución en X-n670-k130 ni X-n936-k151. Sobre sus 100 soluciones, SENDA5 tiene brecha **0.549 %**
con las BKS actuales (0.547 % con las congeladas); AILS-II, 0.593 % (0.590 %). No debe describirse
0.534 % como una media de 100 instancias.

| SENDA5 − rival (BKS actuales) | n pareado | Diferencia (pp) | IC95 bootstrap (pp) | Gana / empata / pierde |
|---|---:|---:|---|---|
| AILS-II | 100 | −0.043 | [−0.117, +0.024] | 54 / 3 / 43 |
| FILO2 | 100 | −0.187 | [−0.263, −0.114] | 63 / 3 / 34 |
| HGS | 98 | −1.161 | [−1.407, −0.925] | 76 / 5 / 17 |
| PyVRP | 100 | −1.746 | [−1.966, −1.536] | 95 / 3 / 2 |
| OR-Tools | 100 | −7.548 | [−8.431, −6.722] | 100 / 0 / 0 |
| Vecino más cercano | 100 | −24.927 | [−27.797, −22.179] | 100 / 0 / 0 |

Los pares usan todas las instancias resueltas por ambos brazos, por eso su diferencia no siempre
es la resta de las medias de la primera tabla. Bootstrap percentil: 10,000 remuestreos de instancias,
semilla 12345, índices 249 y 9749; sin corrección por comparaciones múltiples. Las doce BKS
actualizadas no cambian los veredictos. Las cifras completas están en [el resumen de auditoría](senda5_auditoria.json).

El reloj cumple las dos condiciones predefinidas sobre las medianas: 3.980 s para SENDA5 y
3.974–3.980 s para los demás brazos con límite. **No es una garantía de terminar siempre antes de
4.000 s:** el máximo de SENDA5 fue 4.124 s y una corrida superó 4.10 s. El vecino más cercano termina
antes y no agota cuatro segundos. La mediana de la sentinela de velocidad fue 1.001.

## Antecedentes: SENDA4 y SENDA5 antes de corregir el reloj

| Experimento | Diseño | Resultado primario original |
|---|---|---|
| SENDA4 frente a SENDA3 | 9,600 ensayos; 100 X; seis brazos; 0.5–4 s; dos réplicas; primario en 68 instancias no usadas para desarrollar SENDA4 | A 4 s: −0.128 pp, IC95 [−0.186, −0.072] |
| SENDA5 frente a SENDA4 | 9,000 ensayos; 100 X; tres brazos; 0.5–5 s; tres réplicas | A 4 s: −0.033 pp, IC95 [−0.067, −0.002]; rutas cortas: −0.119 pp |

Cumplen sus reglas originales, pero usaban el límite nominal de cada optimizador, sin igualar la
pared. En el segundo contrato, a 4 s nominales, las medianas medidas fueron 4.055 s para SENDA4/SENDA5
y 4.253 s para AILS-II; SENDA5 llegó a 4.543 s. No se trasladan sus afirmaciones de liderazgo por
presupuesto a la versión de reloj corregido. Todas las instancias de rutas cortas de SENDA5 ya
se habían observado: son réplicas nuevas, no validación en un banco independiente.

En la exploración posterior con reloj corregido (16 X, 384 ensayos), SENDA5 − AILS-II a 10 s fue
+0.089 pp, IC95 [−0.041, +0.215]; a 30 y 60 s los intervalos también cruzan cero. A 120 s fue
+0.107 pp [ +0.013, +0.203 ], con una réplica. Eso respalda una desventaja exploratoria a 120 s;
**no demuestra que AILS-II gane en todo presupuesto desde 10 s**. Los ensayos de agrupamiento
e-means y de 3,000–10,000 clientes no se usan para justificar este lanzamiento: son exploratorios,
con una semilla y referencias no verificadas en su informe original.

## Alcance y trazabilidad de la auditoría

Auditoría del 17 de noviembre: 19,300 ensayos de contratos y 384 de reloj corregido. Se comprobaron
hashes de contratos y dependencias declaradas, cobertura completa de celdas, semillas, ausencia de
duplicados, costos contra referencias, medias, 236 comparaciones bootstrap y sentinelas. No se
modificaron los contratos. La solución local antigua de X-n384-k52 costaba 65,940; la solución
oficial descargada y revalidada cuesta 65,928, que coincide con la referencia congelada.

- Los registros guardan costo, número de rutas y `verified`, **pero no las rutas históricas**.
  Se audita su integridad y aritmética; no se puede repetir hoy la validación geométrica de cada
  una de esas soluciones. Las pruebas de integración sí conservan sus propias rutas nuevas.
- Una corrida por instancia en la evidencia principal. El intervalo estima variación entre
  instancias, no entre ejecuciones. AILS-II no recibió la semilla del arnés.
- El contrato público deja vacía la versión de PyVRP y no congela sus paquetes ni los de OR-Tools.
  El campo JSON de P2 sólo almacena una de las dos condiciones; esta auditoría comprobó ambas.
- El algoritmo se desarrolló sobre estas instancias. No se midieron personas ni Excel: el brazo
  de vecino más cercano no representa a un «experto». Las figuras históricas que lo rotulan así
  no sustentan una comparación con personas.
- La mejora de CVRP no prueba mejoras en ventanas de tiempo, acomodo 3D, flota fija o red vial.
  Las pruebas de producto comprueban integración y factibilidad en esos caminos, no superioridad.

## Uso e integración

```bash
python -m lattimex build
python -m lattimex cvrp X-n1001-k43.vrp --time 4 --router senda5
python -m unittest tests.test_senda5 tests.test_senda3 -v
```

`cvrp` usa SENDA5 por omisión y conserva `--router senda3`, `senda2` y `senda` para ejecutar los
núcleos anteriores. El comando reserva el 80 % de `--time` para el núcleo: **`--time 4` no reproduce
exactamente la calibración experimental de cuatro segundos de pared** descrita arriba.

El motor completo carga `libsenda5` mediante `LATTIMEX_CORE5`; mantiene la política anterior de
usar SENDA 1.0 cuando `router=auto` tiene menos de seis destinos por unidad. En la API, `senda5`,
`senda3` y `senda2` conservan la semántica de alias del núcleo actual cargado; `senda` fuerza el antiguo.
La respuesta informa el núcleo utilizado. El portafolio paralelo ahora incluye el pulido inicial
en el presupuesto por corrida y elimina el descuento adicional de 12 % para SENDA5. Esa extensión
al producto se prueba separadamente y no se presenta como otro benchmark confirmado.
