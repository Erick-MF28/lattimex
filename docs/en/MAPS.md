# Your own maps

*[Versión en español](../MAPS.md)*

LATTIMEX does not depend on routing services: each installation builds its map from OpenStreetMap
data and stores it in `data/maps/`. The Planner uses the standard OpenStreetMap tiles as background
(with attribution, visible area only) and falls back to its own layer when there is no connection.

| File | Use |
|---|---|
| `<name>.gpickle` | Undirected road graph for the engine. Nodes in EPSG:6372 (meters), weight = segment length. |
| `<name>.roads.json` | Street layer `lattimex.roads.v1` drawn by the Planner (4 classes: motorway, primary, secondary, local). |
| `<name>.json` | Metadata: source, date, nodes, segments, attribution and SHA-256 of the graph. |

## Building a map

**Mid-size city (bounding box):**

```bash
python -m lattimex map --bbox 20.47,-100.52,20.82,-100.22 --name queretaro
```

Downloads the streets in the box once from the public Overpass API (≈ 40 MB for Querétaro) and keeps
them in `data/osm/`. Querétaro: ≈ 227 thousand nodes, 11 s to build, 2.6 MB street layer (0.9 MB
compressed).

**Large region or offline (extract):**

```bash
pip install osmium
python -m lattimex map --osm mexico-latest.osm.pbf --name mexico
```

Extracts can be downloaded from [Geofabrik](https://download.geofabrik.de/). `.osm` (XML) files
exported from JOSM or Overpass are also accepted.

Add `--data FOLDER` to store the map in another data folder (see [PLANNER.md](PLANNER.md)).

## Which streets are included

Roads usable by delivery vehicles: `motorway`, `trunk`, `primary`, `secondary`, `tertiary`,
`unclassified`, `residential`, `living_street`, `service` and `road` (and their links). Areas, ways
with `access=no|private` or `motor_vehicle=no|private`, and service ways of type parking aisle,
driveway, drive-through and emergency access are excluded. The largest connected component is kept.

## Data license

The maps are a database derived from OpenStreetMap: © OpenStreetMap contributors,
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/). Using them inside your company imposes no
additional obligations; if you publish a derived map, you must attribute it and offer it under ODbL.
The Planner shows the attribution on every map.
