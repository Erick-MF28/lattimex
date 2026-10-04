# Licencias de terceros

*[English version](docs/en/THIRD_PARTY_LICENSES.md)*

La implementación de LATTIMEX es propia, salvo la adaptación de Mulberry32 indicada abajo.
Estas son las dependencias que se instalan aparte (`pip install -r requirements.txt`) o que
intervienen al compilar o ejecutar:

| Componente | Uso | Licencia | Obligación al redistribuir |
|---|---|---|---|
| [NumPy](https://numpy.org) | matrices del motor y del servidor | BSD-3-Clause (incluye componentes 0BSD, MIT, Zlib, CC0) | Conservar sus avisos si se empaqueta junto con LATTIMEX |
| [SciPy](https://scipy.org) | caminos mínimos (Dijkstra) sobre la red vial | BSD-3-Clause | Idem |
| [NetworkX](https://networkx.org) | grafo vial | BSD-3-Clause | Idem |
| [pyproj](https://pyproj4.github.io/pyproj/) (incluye PROJ) | proyección de coordenadas | MIT | Idem |
| [ziglang](https://pypi.org/project/ziglang/) *(opcional, solo para compilar)* | compilador C++ portátil | MIT (Zig); libc++/LLVM: Apache-2.0 WITH LLVM-exception | Ninguna para los binarios compilados (excepción de LLVM) |
| [osmium](https://osmcode.org/pyosmium/) *(opcional)* | leer extractos `.osm.pbf` | BSD-2-Clause | Idem |

## Algoritmos incorporados

| Algoritmo | Dónde | Licencia |
|---|---|---|
| [Generador pseudoaleatorio Mulberry32](https://gist.github.com/tommyettinger/46a874533244883189143505d203312c) (Tommy Ettinger) | Adaptación en `native/pack3d.cpp` y `lattimex/engine/loading3d.py` | [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/), dedicación al dominio público |

Las ideas publicadas que implementa el motor (ALNS, búsqueda granular, puntos extremos, etc.) se
citan en [docs/ACADEMIC_NOTES.md](docs/ACADEMIC_NOTES.md). La adaptación de Mulberry32 conserva
la procedencia y la dedicación CC0 del original; no cambia la licencia MIT del código propio.

## Datos

| Datos | Licencia | Nota |
|---|---|---|
| OpenStreetMap | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | Los grafos viales y las capas de calles se generan en la computadora del usuario. El uso público de una base de datos derivada debe cumplir las condiciones de atribución, licencia compartida y acceso de ODbL. |

Una imagen o captura de un mapa es una obra producida a partir de los datos, no necesariamente
una base de datos derivada. Su publicación requiere atribuir
[© colaboradores de OpenStreetMap](https://www.openstreetmap.org/copyright) e informar de la
licencia de los datos; ODbL no exige automáticamente licenciar la imagen completa bajo ODbL.
Si la imagen procede de una base de datos derivada, también se aplican las condiciones de
licencia compartida y acceso a esa base. Ver las secciones 4.3–4.6 de
[ODbL](https://opendatacommons.org/licenses/odbl/1-0/) y las
[directrices de atribución](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines).

## Servicios

`python -m lattimex map --bbox ...` hace **una** consulta a la API pública de
[Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API) para descargar las calles de un
rectángulo. Respete su política de uso: descargue una vez por ciudad; para regiones grandes use un
extracto de [Geofabrik](https://download.geofabrik.de/). El cálculo (distancias, rutas y acomodo) no se conecta
a ningún servicio externo.

En modo automático, el precio del combustible se obtiene de los
[datos abiertos de precios de la CRE](https://www.gob.mx/cre) (precios vigentes por estación y su
ubicación). La consulta solo descarga esos archivos públicos; no envía datos de la operación.
Revise los términos de uso de la CRE si redistribuye los precios.

## El Planner

El LATTIMEX Planner (lattimex.com/planner) usa [Leaflet](https://leafletjs.com) 1.9.4 (BSD-2-Clause)
desde cdnjs y, como fondo, las teselas estándar de OpenStreetMap (`tile.openstreetmap.org`), con la
atribución "© colaboradores de OpenStreetMap" y sujetas a su
[política de uso de teselas](https://operations.osmfoundation.org/policies/tiles/). Para uso intensivo
(flotas grandes, muchos usuarios) conviene un servidor de teselas propio o un proveedor comercial.
El Planner no forma parte de este repositorio.
