# Changes

## 1.1.0 — not yet released

An advance over 1.0.0: a better routing core, a new 3D packer and the integration of both. Version
1.0.0 remains available at its `v1.0.0` tag. The measurements are in the new guide,
[paper/senda2_guide_en.pdf](../../paper/senda2_guide_en.pdf); the SENDA guide
([paper/senda_guide_en.pdf](../../paper/senda_guide_en.pdf)) is kept unchanged.

**Three ways to use the engine** (try them separately or together):

- **SENDA2 alone, classic CVRP:** `python -m lattimex cvrp X-n101-k25.vrp --time 4`. Reads CVRPLIB files
  and splits the time as in the guide's comparison. Against HGS-CVRP, on the same machine and clock:
  +0.33 gap points on 41 X instances (4 s) and +0.07 on 60 A/B/E (2 s, fixed fleet). FILO2 is stronger
  on X (0.72 % versus 1.74 % for SENDA2).
- **The packer alone:** `python -m lattimex pack boxes.json` packs one route (P3L) and checks the result
  against the constraints of Gendreau et al. (2006).
- **The full engine** (what the Planner uses): routing, packing, mediation and unloading plan.

**Engine changes (`lattimex-engine-1.7.0`):**

- **SENDA2 routing by default** (`native/senda2_core.cpp`): cached regret repair, discarding repairs that
  do not fit, and a 0.02 s polish cap per new best. With fewer than 6 deliveries per vehicle the engine
  uses the 1.0.0 SENDA core (`native/senda_core.cpp`), which was better there. It can be forced with
  `"router": "senda2" | "senda"` in the request or `LATTIMEX_ROUTER`.
- **P3L packer by default** (`native/p3l.cpp`). On the optimal routes of Tamke et al. (2025), which are
  known to fit, the 1.0.0 packer rejected 34 % to 61 % depending on the variant; P3L, 24 % to 36 %. On
  product routes of 60–97 boxes with all constraints, from at least 71 % to at least 15 % (4 % when given
  500 ms per route). If P3L does not
  place everything, the 1.0.0 packer is tried in the same variant.
- **Strict, verified unloading order:** every packing goes through a checker with Gendreau's semantics
  (it agrees with Krebs's validator on 2,436 of 2,436 packings). Fixes a 1.0.0 defect: a box of a later
  delivery could end up on top of an earlier one.
- **Transparency fix:** in 1.0.0, if a route did not fit with the unloading order, the engine relaxed it
  silently, route by route, before trying mediation. Now mediation first works with the strict order
  and only if a route still does not fit is it relaxed **and reported**: new `lifo_estricto` and
  `advertencias` fields in the response (besides the existing per-route `lifo_respetado`). On the 12
  product instances with all constraints, 1.0.0 returned 24 of 24 "feasible" plans without unloading
  order; 1.1.0 returns 19 of 24 with strict order and warns on the other 5.
- **Fleet "up to k"** (`"fleet_mode": "up_to"`, optional): the engine may use fewer vehicles than
  available. On small instances (up to 60 deliveries and 30 boxes per vehicle) it enables **R3L**, a
  routing search that checks whether the load fits at every step: on the 19 Gendreau instances with
  Tamke's optima, 284 of 285 valid solutions and +8.1 % distance at 10 s (1.0.0: 81 of 285 valid, +26 %).
  By default the fleet stays exact, as in 1.0.0.
- **Exact-fleet constructor fallback:** when the load barely fits in k vehicles, the 1.0.0 constructor
  could fail (11 of 41 X instances); it now assigns accepting overload and removes it with local search.
- Build with MinGW g++ on Windows: the GCC runtime is linked into the DLLs
  (`-static-libgcc -static-libstdc++`). Before, the DLLs depended on `libstdc++-6.dll`, which Python
  3.8+ does not look up in the PATH, and the engine did not load.
- Documented the two deterministic fingerprints by C++ standard library (zig/libc++ and
  g++/libstdc++); CI publishes its own as an annotation.
- 3D packer: with identical boxes, if the extreme-point greedy does not place them all, a layered
  pattern is tried (optimal guillotine base layout, repeated in height) and whichever places more is
  kept. Example: 40 × 30 × 30 cm boxes in a 337 × 137 × 178 cm van go from 160 to 175. Mixed loads
  do not change; neither does the deterministic fingerprint.
- New deterministic fingerprint; from this version on it includes the engine version, so it never
  matches another version's.

*Translation of [CHANGELOG.md](../../CHANGELOG.md).*

## 1.0.0 — September 30, 2026

First public release.

- Engine `lattimex-engine-1.6.0`, the same one running in production: SENDA routing in C++ with a
  parallel portfolio, effective capacity, native 3D packer, fixed-fleet mediation and unloading plan
  by door. Deterministic fingerprint: `6457b2dd44660773` with zig/libc++ (see [AUTHORSHIP.md](AUTHORSHIP.md)).
- Local server (`python -m lattimex serve`) for the LATTIMEX Planner: listens on 127.0.0.1 only,
  accepts only the Planner's origin, validates Host and uses a session token per start.
  - A single server per port (on Windows, `SO_EXCLUSIVEADDRUSE`): a second server fails with a clear
    error instead of silently sharing the port.
  - `--allow-origin` adds allowed origins; lattimex.com is always allowed.
  - The portfolio uses up to 4 threads (configurable with `LATTIMEX_THREADS`).
  - The distance matrix is computed in the background when the shipments are placed and reused while
    the deliveries do not change (300 deliveries: ~24 s per run in the Planner, versus ~60 s if it
    were recomputed every time).
  - The active operation and shipments captured but not saved (draft) are kept when the Planner is
    closed or the server restarts.
  - Automatic fuel price (median of current CRE prices near the distribution center) or manual
    (`/api/settings/fuel`).
  - `--data FOLDER` chooses the data folder (database, results and maps) in any command.
  - Deletion of shipments and saved runs (`DELETE /api/instances/<id>/guides/<shipment>`,
    `DELETE /api/planning-runs[/id]`).
- Own maps from OpenStreetMap (`python -m lattimex map`): road graph for the engine and own street
  layer; computation uses no external services (the Planner only requests OpenStreetMap tiles as a
  visual background).
- Portable build (`python -m lattimex build`) with g++, clang++ or `ziglang`.
- Start window without a terminal (`python -m lattimex app`): starts the engine, prepares the city
  map, opens the Planner and changes the data folder. Packaged as a Windows application and installer
  (`packaging/windows/`).
- Educational guide to the routing core in `paper/` (CC BY 4.0), in Spanish and English, with a
  section on computational complexity and one for repeating the measurements.
- Provenance notices for Mulberry32 (Tommy Ettinger, CC0-1.0), distinction between OpenStreetMap
  data and images, and license notice of the guide included in the PDF and its metadata.
- Tests: 42 for the engine, 72 C++/Python equivalence cases for the packer, 13 for the server and the
  deterministic fingerprint (`python -m lattimex probe`).
