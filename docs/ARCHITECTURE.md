# Arquitectura

*[English version](en/ARCHITECTURE.md)*

LATTIMEX separa la **interfaz** (el Planner, servido por lattimex.com) del **cómputo y los datos**
(este repositorio, ejecutado en la computadora del usuario). El servidor de lattimex.com solo entrega
archivos estáticos; nunca recibe direcciones, pedidos, vehículos ni resultados.

```text
Navegador                                   Computadora del usuario (127.0.0.1)
─────────                                   ──────────────────────────────────
lattimex.com/planner  (HTML/JS/CSS)         python -m lattimex serve  → lattimex/server.py
   │  CSP: connect-src 127.0.0.1 / localhost          │
   │                                                  ├── store.py    SQLite: flota, operarios, guías,
   └──── fetch + token de sesión ────────────────────►│               instancias y corridas
                                                      ├── network.py  red vial: ubicar entregas,
                                                      │               matriz de caminos mínimos, geometrías
                                                      └── Engine      hilo de trabajo (uno a la vez)
                                                            │
                                                            ├── map_preparation.py  matriz vial del trabajo
                                                            └── engine_runtime.solve()
                                                                  ├── ruteo SENDA (native/senda_core.cpp, ctypes)
                                                                  ├── empaque 3D (native/pack3d.cpp)
                                                                  ├── mediación con flota fija
                                                                  ├── plan de descarga por puertas
                                                                  └── verificación de la solución
```

## Flujo de una optimización

1. El Planner envía `POST /api/engine/v1/solve` con coordenadas, flota, paquetes y restricciones.
2. El servidor valida la solicitud (mismo contrato que usaba producción) y crea un trabajo.
3. `map_preparation` ubica cada punto en la red vial y calcula la matriz de distancias por calle.
4. `engine_runtime.solve` rutea con capacidad efectiva, empaca cada ruta en 3D, repara con flota fija
   y genera el plan de descarga.
5. El Planner consulta `GET /api/engine/v1/jobs/<id>` hasta que el estado es `done`, dibuja las rutas
   sobre la capa de calles y guarda la corrida en la base local.

## Por qué el motor no se modificó

Los módulos de `lattimex/engine/` y `native/` son byte por byte los de la versión de producción
`lattimex-engine-1.6.0`. El servidor local los importa sin cambios (`lattimex.native.configure()`
expone las bibliotecas mediante `LATTIMEX_CORE` y `LATTIMEX_PACK3D`). Así los resultados del
repositorio son los mismos que obtuvieron los usuarios del servicio.

## Mapas

`lattimex/maps.py` construye dos archivos desde un extracto de OpenStreetMap: el grafo que usa el
motor (EPSG:6372, peso = metros) y la capa de calles (`lattimex.roads.v1`), que el Planner dibuja cuando
no puede cargar las teselas de OpenStreetMap. Ver [MAPS.md](MAPS.md).

## Límites actuales

- La proyección EPSG:6372 está pensada para México; en otros países funciona, pero con más
  distorsión en distancias largas.
- El grafo es no dirigido: no considera sentidos de circulación ni vueltas prohibidas.
- Un trabajo a la vez; hasta 1000 puntos por corrida y 300 s de cómputo.
