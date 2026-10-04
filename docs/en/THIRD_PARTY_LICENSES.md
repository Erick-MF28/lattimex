# Third-party licenses

*Translation of [THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md).*

The implementation of LATTIMEX is original, except for the adaptation of Mulberry32 noted below.
These are the dependencies installed separately (`pip install -r requirements.txt`) or involved in
building or running:

| Component | Use | License | Obligation when redistributing |
|---|---|---|---|
| [NumPy](https://numpy.org) | engine and server matrices | BSD-3-Clause (includes 0BSD, MIT, Zlib, CC0 components) | Keep its notices if packaged together with LATTIMEX |
| [SciPy](https://scipy.org) | shortest paths (Dijkstra) on the road network | BSD-3-Clause | Same |
| [NetworkX](https://networkx.org) | road graph | BSD-3-Clause | Same |
| [pyproj](https://pyproj4.github.io/pyproj/) (includes PROJ) | coordinate projection | MIT | Same |
| [ziglang](https://pypi.org/project/ziglang/) *(optional, build only)* | portable C++ compiler | MIT (Zig); libc++/LLVM: Apache-2.0 WITH LLVM-exception | None for compiled binaries (LLVM exception) |
| [osmium](https://osmcode.org/pyosmium/) *(optional)* | reading `.osm.pbf` extracts | BSD-2-Clause | Same |

## Incorporated algorithms

| Algorithm | Where | License |
|---|---|---|
| [Mulberry32 pseudorandom generator](https://gist.github.com/tommyettinger/46a874533244883189143505d203312c) (Tommy Ettinger) | Adapted in `native/pack3d.cpp` and `lattimex/engine/loading3d.py` | [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/), public domain dedication |

The published ideas the engine implements (ALNS, granular search, extreme points, etc.) are cited
in [ACADEMIC_NOTES.md](ACADEMIC_NOTES.md). The Mulberry32 adaptation keeps the provenance and the
CC0 dedication of the original; it does not change the MIT license of the original code.

## Data

| Data | License | Note |
|---|---|---|
| OpenStreetMap | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | Road graphs and street layers are generated on the user's computer. Public use of a derived database must comply with the ODbL attribution, share-alike and access conditions. |

An image or screenshot of a map is a work produced from the data, not necessarily a derived
database. Publishing it requires attributing
[© OpenStreetMap contributors](https://www.openstreetmap.org/copyright) and stating the data
license; ODbL does not automatically require licensing the whole image under ODbL. If the image comes
from a derived database, the share-alike and access conditions of that database also apply. See
sections 4.3–4.6 of [ODbL](https://opendatacommons.org/licenses/odbl/1-0/) and the
[attribution guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines).

## Services

`python -m lattimex map --bbox ...` makes **one** query to the public
[Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API) API to download the streets of a
rectangle. Respect its usage policy: download once per city; for large regions use an extract from
[Geofabrik](https://download.geofabrik.de/). Computation (distances, routes and placement) does not
connect to any external service.

In automatic mode, the fuel price comes from the
[CRE open price data](https://www.gob.mx/cre) (current prices per station and their location). The
lookup only downloads those public files; it sends no operational data. Check the CRE terms of use
if you redistribute the prices.

## The Planner

The LATTIMEX Planner (lattimex.com/planner) uses [Leaflet](https://leafletjs.com) 1.9.4 (BSD-2-Clause)
from cdnjs and, as background, the standard OpenStreetMap tiles (`tile.openstreetmap.org`), with the
attribution "© OpenStreetMap contributors" and subject to its
[tile usage policy](https://operations.osmfoundation.org/policies/tiles/). For intensive use
(large fleets, many users) a self-hosted tile server or a commercial provider is advisable. The
Planner is not part of this repository.
