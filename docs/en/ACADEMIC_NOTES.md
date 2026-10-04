# Academic notes

*[Versión en español](../ACADEMIC_NOTES.md)*

LATTIMEX comes from an independent line of research on vehicle routing with three-dimensional
loading constraints (3L-CVRP). This repository contains the engine as it ran in production; the
experiments, logs and complete comparisons are not published here. Anyone who wants to validate
results can reproduce them on their own computer with the instructions below.

## Components and the literature behind them

| Component | Idea | Reference |
|---|---|---|
| Routing search (SENDA: one search trajectory per run, no population and no crossover) | Adaptive large neighborhood search (ALNS): destroy and repair with operators whose probability adapts to their success | Ropke and Pisinger (2006); Shaw (1998) |
| Penalized infeasibility | Solutions that exceed capacity may be explored with a penalty that adapts to keep a target fraction of feasible candidates | Vidal et al. (2012) |
| Granular neighborhoods | Moves are restricted to the *k* nearest neighbors of each customer | Toth and Vigo (2003) |
| SWAP* | Exchange of two customers between routes, reinserting each at its best position | Vidal (2022) |
| Parallel portfolio | Two configurations × two seeds on threads, with deterministic reduction | — |
| Effective capacity | Routing uses a fraction α of the nominal volume, calibrated per constraint variant, relaxed step by step if the load does not fit | — |
| 3D packing | Extreme-point heuristic with restarts, gravity settling, minimum support, fragility and orientation | Crainic, Perboli and Tadei (2008); Gendreau et al. (2006) |
| Unloading plan | For each stop, exit door and boxes that must be temporarily set aside | — |

The implementation is original; see [AUTHORSHIP.md](AUTHORSHIP.md).

## Published results

On 60 reference instances from families A, B and E (CVRPLIB), with 2 s of computation on one thread
and a verified fixed fleet, the mean gap to the best known solution was **0.111 %** for SENDA and
**0.004 %** for HGS-CVRP (Vidal, 2022): 37 ties, 23 cases in favor of HGS and none in favor of SENDA.
In the variant with 3D loading, an advantage in pure routing no longer determines the best solution
by itself. Full analysis in the educational guide
([paper/senda_guide_en.pdf](../../paper/senda_guide_en.pdf)).

## Reproducing comparisons on your computer

1. Download instances from [CVRPLIB](http://vrp.galgos.inf.puc-rio.br/) (families A, B, E or X).
2. Build the distance matrix with the CVRPLIB convention (rounded Euclidean distance).
3. Call the engine directly. For a classic CVRP, use a very large vehicle box and 1 cm packages: this
   way volume never binds and capacity is given by weight (`max_weight_kg` = capacity).

```python
from lattimex import native; native.configure()
import engine_runtime as er

res = er.solve({
    "matrix_m": matrix,                          # n × n, node 0 = depot
    "fleet": [{"cargo_cm": [10000, 10000, 10000], "max_weight_kg": capacity}] * k,
    "fleet_count": k,                            # the engine uses exactly k vehicles
    "packages": [{"id": f"C{i}", "node": i, "dims_cm": [1, 1, 1], "weight_kg": demand[i]}
                 for i in range(1, n)],
    "budget_sec": 5, "seed": 1,
})
distance = sum(matrix[a][b] for r in res["routes"]
               for a, b in zip([0, *r["sequence"]], [*r["sequence"], 0]))
```

   Verified with X-n101-k25 (best known 27 591): with `k = 26` the solution is feasible and 0.64 %
   away in 5 s. With `k = 25` the engine rejects the instance because its initial construction cannot
   split the load into exactly 25 vehicles: the product engine puts exact fleet and feasibility ahead
   of distance. On very tight instances use `k + 1` or report them as unsolved.

4. The published comparison (A, B and E) was made with an experiment harness that calls the routing
   core with a per-instance budget and several replicates; that harness is not part of the
   repository. To compare against HGS-CVRP, build it from its official repository, use the same time
   budget per instance and report the average of several seeds.

## References

- Crainic, T. G., Perboli, G., and Tadei, R. (2008). Extreme point-based heuristics for three-dimensional bin packing. *INFORMS Journal on Computing*, 20(3), 368–384.
- Gendreau, M., Iori, M., Laporte, G., and Martello, S. (2006). A tabu search algorithm for a routing and container loading problem. *Transportation Science*, 40(3), 342–350.
- Ropke, S., and Pisinger, D. (2006). An adaptive large neighborhood search heuristic for the pickup and delivery problem with time windows. *Transportation Science*, 40(4), 455–472.
- Shaw, P. (1998). Using constraint programming and local search methods to solve vehicle routing problems. In *Principles and Practice of Constraint Programming — CP98*, 417–431.
- Toth, P., and Vigo, D. (2003). The granular tabu search and its application to the vehicle-routing problem. *INFORMS Journal on Computing*, 15(4), 333–346.
- Uchoa, E., Pecin, D., Pessoa, A., Poggi, M., Vidal, T., and Subramanian, A. (2017). New benchmark instances for the capacitated vehicle routing problem. *European Journal of Operational Research*, 257(3), 845–858.
- Vidal, T., Crainic, T. G., Gendreau, M., Lahrichi, N., and Rei, W. (2012). A hybrid genetic algorithm for multidepot and periodic vehicle routing problems. *Operations Research*, 60(3), 611–624.
- Vidal, T. (2022). Hybrid genetic search for the CVRP: Open-source implementation and SWAP* neighborhood. *Computers & Operations Research*, 140, 105643.

## Other lines of research

The LATTIMEX blog (in Spanish) documents exploratory lines that are not part of the engine, for
example the use of a circuit from the fruit fly connectome as a lateral load-balancing rule
(<https://lattimex.com/blog/la-mosca-que-acomoda-carga>).
