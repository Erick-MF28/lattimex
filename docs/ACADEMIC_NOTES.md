# Notas académicas

*[English version](en/ACADEMIC_NOTES.md)*

LATTIMEX proviene de una línea de investigación independiente sobre ruteo de vehículos con
restricciones de carga tridimensional (3L-CVRP). Este repositorio contiene el motor tal como corría
en producción; los experimentos, bitácoras y comparaciones completas no se publican aquí. Quien
quiera validar resultados puede reproducirlos en su computadora con las instrucciones de abajo.

## Componentes y la literatura en que se apoyan

| Componente | Idea | Referencia |
|---|---|---|
| Búsqueda de ruteo (SENDA: una trayectoria de búsqueda por corrida, sin población ni cruce) | Búsqueda de vecindario grande adaptativa (ALNS): destruir y reparar con operadores cuya probabilidad se ajusta según su éxito | Ropke y Pisinger (2006); Shaw (1998) |
| Infactibilidad penalizada | Se permite explorar soluciones que exceden la capacidad con una penalización que se adapta para mantener una fracción objetivo de candidatos factibles | Vidal et al. (2012) |
| Vecindarios granulares | Los movimientos se restringen a los *k* vecinos más cercanos de cada cliente | Toth y Vigo (2003) |
| SWAP* | Intercambio de dos clientes entre rutas, reinsertando cada uno en su mejor posición | Vidal (2022) |
| Portafolio en paralelo | Dos configuraciones × dos semillas en hilos, con reducción determinista | — |
| Capacidad efectiva | Se rutea con una fracción α del volumen nominal, calibrada por variante de restricciones, y se relaja por pasos si la carga no cabe | — |
| Empaque 3D | Heurística de puntos extremos con reinicios, asentado por gravedad, soporte mínimo, fragilidad y orientación | Crainic, Perboli y Tadei (2008); Gendreau et al. (2006) |
| Plan de descarga | Para cada parada, puerta de salida y cajas que deben apartarse temporalmente | — |

La implementación es propia; ver [AUTHORSHIP.md](../AUTHORSHIP.md).

## Resultados publicados

En 60 instancias de referencia de las familias A, B y E (CVRPLIB), con 2 s de cómputo en un hilo y
flota fija verificada, el gap medio contra la mejor solución conocida fue **0.111 %** para SENDA y
**0.004 %** para HGS-CVRP (Vidal, 2022): 37 empates, 23 casos favorables a HGS y ninguno a SENDA.
En la variante con carga 3D, la ventaja de un solver en ruteo puro deja de determinar por sí sola la
mejor solución. Análisis completo en la guía educativa ([paper/guia_senda.pdf](../paper/guia_senda.pdf)).

## Reproducir comparaciones en su computadora

1. Descargue instancias de [CVRPLIB](http://vrp.galgos.inf.puc-rio.br/) (familias A, B, E o X).
2. Construya la matriz de distancias con la convención de CVRPLIB (distancia euclidiana redondeada).
3. Llame al motor directamente. Para un CVRP clásico, use una caja de vehículo muy grande y paquetes
   de 1 cm: así el volumen nunca limita y la capacidad la da el peso (`max_weight_kg` = capacidad).

```python
from lattimex import native; native.configure()
import engine_runtime as er

res = er.solve({
    "matrix_m": matriz,                          # n × n, nodo 0 = depósito
    "fleet": [{"cargo_cm": [10000, 10000, 10000], "max_weight_kg": capacidad}] * k,
    "fleet_count": k,                            # el motor usa exactamente k unidades
    "packages": [{"id": f"C{i}", "node": i, "dims_cm": [1, 1, 1], "weight_kg": demanda[i]}
                 for i in range(1, n)],
    "budget_sec": 5, "seed": 1,
})
distancia = sum(matriz[a][b] for r in res["routes"]
                for a, b in zip([0, *r["sequence"]], [*r["sequence"], 0]))
```

   Verificado con X-n101-k25 (mejor conocida 27 591): con `k = 26` la solución es factible y queda a
   0.64 % en 5 s. Con `k = 25` el motor rechaza la instancia porque su construcción inicial no logra
   repartir la carga en exactamente 25 unidades: el motor de producto prioriza flota exacta y
   factibilidad sobre la distancia. En instancias muy ajustadas use `k + 1` o repórtelas como no resueltas.

4. La comparación publicada (A, B y E) se hizo con un arnés de experimentos que llama al núcleo de
   ruteo con presupuesto por instancia y varias réplicas; ese arnés no forma parte del repositorio.
   Para comparar contra HGS-CVRP, compílelo desde su repositorio oficial, use el mismo presupuesto de
   tiempo por instancia y reporte el promedio de varias semillas.

## Referencias

- Crainic, T. G., Perboli, G., y Tadei, R. (2008). Extreme point-based heuristics for three-dimensional bin packing. *INFORMS Journal on Computing*, 20(3), 368–384.
- Gendreau, M., Iori, M., Laporte, G., y Martello, S. (2006). A tabu search algorithm for a routing and container loading problem. *Transportation Science*, 40(3), 342–350.
- Ropke, S., y Pisinger, D. (2006). An adaptive large neighborhood search heuristic for the pickup and delivery problem with time windows. *Transportation Science*, 40(4), 455–472.
- Shaw, P. (1998). Using constraint programming and local search methods to solve vehicle routing problems. En *Principles and Practice of Constraint Programming — CP98*, 417–431.
- Toth, P., y Vigo, D. (2003). The granular tabu search and its application to the vehicle-routing problem. *INFORMS Journal on Computing*, 15(4), 333–346.
- Uchoa, E., Pecin, D., Pessoa, A., Poggi, M., Vidal, T., y Subramanian, A. (2017). New benchmark instances for the capacitated vehicle routing problem. *European Journal of Operational Research*, 257(3), 845–858.
- Vidal, T., Crainic, T. G., Gendreau, M., Lahrichi, N., y Rei, W. (2012). A hybrid genetic algorithm for multidepot and periodic vehicle routing problems. *Operations Research*, 60(3), 611–624.
- Vidal, T. (2022). Hybrid genetic search for the CVRP: Open-source implementation and SWAP* neighborhood. *Computers & Operations Research*, 140, 105643.

## Otras líneas de investigación

El blog de LATTIMEX documenta líneas exploratorias que no forman parte del motor, por ejemplo el uso
de un circuito del conectoma de la mosca de la fruta como regla de balance lateral de carga
(<https://lattimex.com/blog/la-mosca-que-acomoda-carga>).
