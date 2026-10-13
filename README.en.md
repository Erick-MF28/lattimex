# LATTIMEX

**Vehicle routing with 3D load placement, on your own computer.**

[Español](README.md) · English

[![License: MIT](https://img.shields.io/badge/engine-MIT-2747d9)](LICENSE)
[![Web](https://img.shields.io/badge/web-lattimex.com-0d1628)](https://lattimex.com)
[![Planner](https://img.shields.io/badge/Planner-lattimex.com%2Fplanner-f59e0b)](https://lattimex.com/planner)

LATTIMEX decides which vehicle serves each delivery, in what order, and where every box goes inside
the vehicle, on the real road network of your city. This repository contains the **optimization
engine**, the **local server** and the **map builder**. The graphical interface is the
[LATTIMEX Planner](https://lattimex.com/planner), which opens in the browser and works with the
engine you run yourself: **your data never leaves your computer**.

[![LATTIMEX: fewer kilometers, better loading, only the fleet you need](docs/img/lattimex-web.jpg)](https://lattimex.com)

<p align="center"><a href="https://lattimex.com"><b>Discover LATTIMEX at lattimex.com →</b></a></p>

## Try it in five minutes

Requirements: Python 3.10 or later and a C++ compiler (g++ or clang++). On Windows without a
compiler, `pip install ziglang` installs a portable one that LATTIMEX picks up automatically (clone
into a short path such as `C:\lattimex`: `ziglang` fails with paths longer than 260 characters).

```bash
git clone https://github.com/Erick-MF28/lattimex.git
cd lattimex
pip install -r requirements.txt        # Windows without a compiler: pip install ziglang
python -m lattimex build               # compiles the engine and the 3D packer
python -m lattimex map --bbox 20.47,-100.52,20.82,-100.22 --name queretaro
python -m lattimex serve               # http://127.0.0.1:8765
```

Open **https://lattimex.com/planner** in Chrome, Edge or Firefox. The first time, the browser asks
for permission to access services on this device: accept it. In **Guías** (shipments), the
**Cargar ejemplo** button adds 300 synthetic deliveries in Querétaro, six vans and five drivers; in
**Planificación** (planning), a single button, **Optimizar**, computes the routes and the placement
of every box. The Planner interface is currently in Spanish.

**Your data stays where you decide.** Fleet, shipments, instances and runs are stored in
`data/lattimex.sqlite3`; if you close the Planner, your last operation is there when you come back,
and shipments you captured but had not saved yet are recovered automatically. To work with another
folder (for example, one per customer or a shared network folder):

```bash
python -m lattimex serve --data D:\operations\customer_a
```

`python -m lattimex doctor` checks the installation and `python -m lattimex probe` prints the
engine's deterministic fingerprint. It depends on the C++ standard library used to build it. Version
1.1.0: `1102c21c0192b381` with zig/libc++ (the Windows installer and `pip install ziglang`); the g++/libstdc++
fingerprint (Linux and MinGW) is published by the repository's CI for every version. If your build gives
the fingerprint of its library, it computes exactly what the published engine computes. Version 1.0.0
fingerprints were `6457b2dd44660773` (zig/libc++) and `285bf1758e5dd6a1` (g++/libstdc++); since 1.1.0
the fingerprint includes the engine version, so it never matches another version's.

## Three ways to use the engine

Since version 1.1.0 each piece can be tried on its own:

```bash
python -m lattimex cvrp X-n101-k25.vrp --time 4     # SENDA2 alone, classic CVRP (CVRPLIB files)
python -m lattimex pack boxes.json                  # the 3D packer alone, for one route
python -m lattimex serve                            # the full engine, for the Planner
```

- **SENDA2 alone** splits the time and verifies every solution as in the comparison of guide 2: against
  HGS-CVRP, +0.33 gap points on 41 X instances (4 s) and +0.07 on A/B/E (2 s, fixed fleet).
- **The packer alone** (P3L) takes a JSON with the container and the boxes (`stop` = delivery order)
  and returns the position of each box and whether the packing meets support, fragility and unloading
  order.
- **The full engine** routes with SENDA2, packs with P3L keeping the unloading order and, if a route
  does not fit that way, says so in the response (`lifo_estricto`, `advertencias`). With
  `"fleet_mode": "up_to"` it may use fewer vehicles than available.

**Rather not use the terminal?** `python -m lattimex app` opens a window that starts the engine,
prepares your city map and opens the Planner. The same window is packaged as a Windows application
with an installer and no prerequisites: see [packaging/windows](packaging/windows/README.md).

## What it looks like

Planner screenshots with the bundled example: 300 deliveries in Querétaro, six vans and five
drivers.

**Routes on real streets.** One color per route on the
[OpenStreetMap](https://www.openstreetmap.org/copyright) map and, on the right, each vehicle with its
stops, kilometers, driver and cost.

<img src="docs/img/planner-rutas.webp" alt="Six routes on the map of Querétaro and the vehicle list" width="100%">

**One route at a time.** Selecting a route frames it on the map; the panel shows its cost breakdown
and the sequence of stops.

<img src="docs/img/planner-ruta-detalle.webp" alt="Selected route with its sequence of stops" width="100%">

**3D load placement.** Every box inside the vehicle, from the cab to the door in reverse delivery
order, together with the driver, the cost breakdown and the unloading plan.

<img src="docs/img/planner-acomodo-3d.webp" alt="3D placement diagram with cost and unloading plan" width="100%">

**Indicators for the whole run and for each route.**

<img src="docs/img/planner-indicadores.webp" alt="Indicators: routes, deliveries, kilometers, cost and utilization" width="100%">

**Route sheet for the driver**, with dimensions, weight, cost per delivery, unloading door and which
boxes to set aside first.

<img src="docs/img/planner-hoja-ruta.webp" alt="Printable route sheet" width="100%">

**Fleet and shipments.** Interior dimensions, doors, maximum load and costs of each vehicle;
shipments entered by hand, from CSV or with the example.

<img src="docs/img/planner-flota.webp" alt="Fleet cards" width="100%">

<img src="docs/img/planner-guias.webp" alt="Shipments loaded for planning" width="100%">

Map data in the screenshots: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
available under ODbL 1.0.

## How it works

```text
 lattimex.com/planner  ──(interface only)──►  browser
                                                │  http://127.0.0.1:8765
                                                ▼
                         ┌───────────── your computer ─────────────┐
                         │  local server  →  SENDA2 (C++)          │
                         │  SQLite store  →  P3L packer (C++)      │
                         │  own map       →  verifier              │
                         └─────────────────────────────────────────┘
```

1. **Own map.** `python -m lattimex map` builds, once, the road graph of your city from
   OpenStreetMap. Distances and routes are computed on real streets, without external services.
2. **Routing.** The routing core, SENDA2, is SENDA (*Single-trajectory ENgine with Destroy-and-repair
   Adaptive search*) with a cached repair and a polish cap: it follows a single search trajectory per
   run, with no population and no crossover, builds routes, improves them with granular local search
   and restructures them with an adaptive large neighborhood search (ALNS), in a portfolio of parallel
   runs. With few deliveries per vehicle it uses the 1.0.0 SENDA core.
3. **3D loading.** The P3L packer places each box respecting support, fragility and unloading order,
   and a strict checker reviews every packing; if something does not fit, a mediator readjusts the
   routes with the fixed fleet and, as a last resort, relaxes that route's unloading order and reports
   it.
4. **Verification.** An independent verifier rechecks distances, capacity, coverage and the geometry
   of every box before the plan is delivered.

Details in [docs/en/ARCHITECTURE.md](docs/en/ARCHITECTURE.md), [docs/en/MAPS.md](docs/en/MAPS.md) and
[docs/en/SECURITY.md](docs/en/SECURITY.md).

## Learn how the engine works

The educational guide [**paper/senda_guide_en.pdf**](paper/senda_guide_en.pdf) explains from
scratch, with worked examples, every component of SENDA, its computational complexity, how it was
evaluated against reference solvers from the literature and which evaluation mistakes to avoid. It
ends with a section for repeating the measurements on your computer. The Spanish original is
[paper/guia_senda.pdf](paper/guia_senda.pdf).

The second guide, [**paper/senda2_guide_en.pdf**](paper/senda2_guide_en.pdf) (version 1.1.0), reports
the advance in the same spirit: SENDA2 against HGS-CVRP and FILO2, how a packer was measured against the
published optima of Tamke et al. (2025), which 1.0.0 defects that measurement uncovered and how routing
and packing were integrated. Spanish original: [paper/guia_senda2.pdf](paper/guia_senda2.pdf). The
programs used for comparison are not part of this repository; notes and references are in [docs/en/ACADEMIC_NOTES.md](docs/en/ACADEMIC_NOTES.md).

## What is in this repository

| Folder | Contents |
|---|---|
| `native/` | Routing cores SENDA2 (`senda2_core.cpp`, default) and SENDA (`senda_core.cpp`, version 1.0.0); 3D packers P3L (`p3l.cpp`, default) and extreme points (`pack3d.cpp`, version 1.0.0) |
| `lattimex/engine/` | Engine pipeline: effective capacity, 3D packing and strict checker, fixed-fleet mediation, R3L ("up to k" fleet on small instances), unloading plan by door |
| `lattimex/cvrp.py` | SENDA2 alone on CVRPLIB files (`python -m lattimex cvrp`) |
| `lattimex/server.py` | Local server for the Planner (listens on 127.0.0.1 only) |
| `lattimex/maps.py` | Builds your own map from OpenStreetMap |
| `tests/` | Engine tests, C++/Python equivalence of the packer and server tests |
| `paper/` | Educational guides 1 (SENDA, 1.0.0) and 2 (SENDA2 and 3D loading, 1.1.0), in Spanish and English (LaTeX and PDF) |
| `packaging/windows/` | Windows application and installer (start window, no terminal) |
| `docs/` | Architecture, Planner connection, security, maps, local API and academic notes (`docs/en/` in English) |

Source code identifiers and comments are mostly in Spanish.

## Tests

```bash
python -m unittest discover -s tests/engine        # engine, packer and `cvrp`/`pack` tests
python -m unittest tests.test_local_api -v         # full flow and server defenses
python tests/native/test_pack3d_equivalencia.py    # 72 cases: C++ identical to Python (~10 min)
python -m lattimex probe                           # deterministic engine fingerprint
```

## Licenses

- **Engine, local server and map builder:** [MIT](LICENSE). You may use, modify and distribute them,
  including commercially, keeping the copyright and license notices.
- **LATTIMEX Planner** (lattimex.com/planner): free to use; it is not distributed in this repository
  and may not be redistributed or commercially exploited by third parties. See
  [its license](https://lattimex.com/planner/licencia.html).
- **Educational guides** (`paper/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). You may
  share and adapt it, including commercially, citing the source ([CITATION.cff](CITATION.cff)),
  linking the license and indicating the changes made.
- **Street data:** © OpenStreetMap contributors, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/).
- **Trademark:** "LATTIMEX" and its logo are not covered by the MIT license. See [NOTICE](NOTICE).
- Dependencies: see [docs/en/THIRD_PARTY_LICENSES.md](docs/en/THIRD_PARTY_LICENSES.md). Code
  provenance: [docs/en/AUTHORSHIP.md](docs/en/AUTHORSHIP.md). Changes:
  [docs/en/CHANGELOG.md](docs/en/CHANGELOG.md).

## Implementation services

The engine is offered free of charge under MIT. Implementation, configuration, integration and
training services are quoted separately.

Would you rather have us install it and integrate it with your operation (map, fleet, loading rules,
ERP/WMS/TMS, training)? Visit [lattimex.com](https://lattimex.com) or write to
**contacto@lattimex.com**.

## Donations

The LATTIMEX engine is free and open source. If the engine, the guide or the Planner are useful to
you, you can support their development with a donation: every contribution funds maintenance, new
cities and more educational material.

<p align="center"><a href="https://www.paypal.com/donate/?hosted_button_id=ZAAQQDBG2C4ZE"><b>♥ Donate to LATTIMEX with PayPal</b></a></p>

One-time, monthly or yearly donations, by card or PayPal account.

Would your company like to sponsor a feature or an integration? Write to contacto@lattimex.com.
