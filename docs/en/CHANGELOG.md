# Changes

## Unreleased

- Build with MinGW g++ on Windows: the GCC runtime is linked into the DLLs
  (`-static-libgcc -static-libstdc++`). Before, the DLLs depended on `libstdc++-6.dll`, which Python
  3.8+ does not look up in the PATH, and the engine did not load.
- Documented the two deterministic fingerprints by C++ standard library (zig/libc++ and
  g++/libstdc++); CI publishes its own as an annotation.

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
