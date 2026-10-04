# Mapas propios

*[English version](en/MAPS.md)*

LATTIMEX no depende de servicios de ruteo: cada instalación construye su mapa a partir de datos de
OpenStreetMap y lo guarda en `data/maps/`. El Planner usa como fondo las teselas estándar de
OpenStreetMap (con atribución, solo el área visible) y recurre a la capa propia si no hay conexión.

| Archivo | Uso |
|---|---|
| `<nombre>.gpickle` | Grafo vial no dirigido para el motor. Nodos en EPSG:6372 (metros), peso = longitud del tramo. |
| `<nombre>.roads.json` | Capa de calles `lattimex.roads.v1` que dibuja el Planner (4 clases: autopista, principal, secundaria, local). |
| `<nombre>.json` | Metadatos: fuente, fecha, nodos, tramos, atribución y SHA-256 del grafo. |

## Construir un mapa

**Ciudad mediana (rectángulo):**

```bash
python -m lattimex map --bbox 20.47,-100.52,20.82,-100.22 --name queretaro
```

Descarga una sola vez las calles del rectángulo desde la API pública de Overpass (≈ 40 MB para
Querétaro) y las guarda en `data/osm/`. Querétaro: ≈ 227 mil nodos, 11 s de construcción,
capa de calles de 2.6 MB (0.9 MB comprimida).

**Región grande o sin conexión (extracto):**

```bash
pip install osmium
python -m lattimex map --osm mexico-latest.osm.pbf --name mexico
```

Los extractos se descargan de [Geofabrik](https://download.geofabrik.de/). También acepta `.osm`
(XML) exportado de JOSM o de Overpass.

Agregue `--data CARPETA` para guardar el mapa en otra carpeta de datos (ver [PLANNER.md](PLANNER.md)).

## Qué calles entran

Vías transitables para vehículos de reparto: `motorway`, `trunk`, `primary`, `secondary`, `tertiary`,
`unclassified`, `residential`, `living_street`, `service` y `road` (y sus enlaces). Se excluyen áreas,
vías con `access=no|private` o `motor_vehicle=no|private`, y servicios de tipo estacionamiento,
cochera, autoservicio y acceso de emergencia. Se conserva el componente conexo más grande.

## Licencia de los datos

Los mapas son una base de datos derivada de OpenStreetMap: © colaboradores de OpenStreetMap,
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/). Usarlos dentro de su empresa no le impone
obligaciones adicionales; si publica un mapa derivado, debe atribuirlo y ofrecerlo bajo ODbL.
El Planner muestra la atribución en cada mapa.
