# Architecture

*[Versión en español](../ARCHITECTURE.md)*

LATTIMEX separates the **interface** (the Planner, served by lattimex.com) from **computation and
data** (this repository, running on the user's computer). The lattimex.com server only delivers
static files; it never receives addresses, orders, vehicles or results.

```text
Browser                                     User's computer (127.0.0.1)
───────                                     ───────────────────────────
lattimex.com/planner  (HTML/JS/CSS)         python -m lattimex serve  → lattimex/server.py
   │  CSP: connect-src 127.0.0.1 / localhost          │
   │                                                  ├── store.py    SQLite: fleet, drivers, shipments,
   └──── fetch + session token ──────────────────────►│               instances and runs
                                                      ├── network.py  road network: snap deliveries,
                                                      │               shortest-path matrix, geometries
                                                      └── Engine      worker thread (one at a time)
                                                            │
                                                            ├── map_preparation.py  road matrix of the job
                                                            └── engine_runtime.solve()
                                                                  ├── SENDA routing (native/senda_core.cpp, ctypes)
                                                                  ├── 3D packing (native/pack3d.cpp)
                                                                  ├── fixed-fleet mediation
                                                                  ├── unloading plan by door
                                                                  └── solution verification
```

## Flow of an optimization

1. The Planner sends `POST /api/engine/v1/solve` with coordinates, fleet, packages and constraints.
2. The server validates the request (same contract that production used) and creates a job.
3. `map_preparation` snaps each point to the road network and computes the street distance matrix.
4. `engine_runtime.solve` routes with effective capacity, packs each route in 3D, repairs with the
   fixed fleet and generates the unloading plan.
5. The Planner polls `GET /api/engine/v1/jobs/<id>` until the status is `done`, draws the routes on
   the street layer and stores the run in the local database.

## Why the engine was not modified

The modules in `lattimex/engine/` and `native/` are byte for byte those of the production version
`lattimex-engine-1.6.0`. The local server imports them unchanged (`lattimex.native.configure()`
exposes the libraries through `LATTIMEX_CORE` and `LATTIMEX_PACK3D`). This way the results of the
repository are the same that users of the service obtained.

## Maps

`lattimex/maps.py` builds two files from an OpenStreetMap extract: the graph used by the engine
(EPSG:6372, weight = meters) and the street layer (`lattimex.roads.v1`), which the Planner draws when
it cannot load the OpenStreetMap tiles. See [MAPS.md](MAPS.md).

## Current limits

- The EPSG:6372 projection is designed for Mexico; it works in other countries, but with more
  distortion over long distances.
- The graph is undirected: it does not consider one-way streets or forbidden turns.
- One job at a time; up to 1000 points per run and 300 s of computation.
