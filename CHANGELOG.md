# Cambios

## 1.1.0 — 23 de octubre de 2026

Avance sobre la 1.0.0: un núcleo de ruteo mejor, un acomodador 3D nuevo y la integración de ambos. La
versión 1.0.0 sigue disponible en su etiqueta `v1.0.0`. Las mediciones están en la guía nueva,
[paper/guia_senda2.pdf](paper/guia_senda2.pdf); la guía de SENDA ([paper/guia_senda.pdf](paper/guia_senda.pdf))
se conserva sin cambios.

**Tres formas de usar el motor** (pruébelas por separado o juntas):

- **SENDA2 solo, CVRP clásico:** `python -m lattimex cvrp X-n101-k25.vrp --time 4`. Lee archivos de
  CVRPLIB y reparte el tiempo como en la comparación de la guía. Frente a HGS-CVRP, en la misma máquina
  y con el mismo reloj: +0.33 puntos de gap en 41 instancias X (4 s) y +0.07 en 60 A/B/E (2 s, flota
  fija). FILO2 es más fuerte en X (0.72 % contra 1.74 % de SENDA2).
- **El acomodador solo:** `python -m lattimex pack cajas.json` acomoda una ruta (P3L) y verifica el
  resultado con las restricciones de Gendreau et al. (2006).
- **El motor completo** (lo que usa el Planner): ruteo, acomodo, mediación y plan de descarga.

**Cambios en el motor (`lattimex-engine-1.7.0`):**

- **Ruteo SENDA2 por omisión** (`native/senda2_core.cpp`): reparación regret con caché, descarte de
  reparaciones que no caben y tope de pulido de 0.02 s por nuevo mejor. Con menos de 6 entregas por
  unidad el motor usa el núcleo SENDA de 1.0.0 (`native/senda_core.cpp`), que fue mejor ahí. Se puede
  forzar con `"router": "senda2" | "senda"` en la petición o `LATTIMEX_ROUTER`.
- **Acomodador P3L por omisión** (`native/p3l.cpp`). Con las rutas óptimas de Tamke et al. (2026), que se
  sabe que caben, el empacador de 1.0.0 rechazaba entre 34 % y 61 % según la variante; P3L, entre 24 % y
  36 %. En rutas de producto de 60–97 cajas con todas las restricciones, de al menos 71 % a al menos
  15 % (4 % si se le dan 500 ms por ruta). Si P3L no coloca todo, se intenta el empacador de 1.0.0 en la misma variante.
- **Orden de descarga estricto y verificado:** todo acomodo pasa por un verificador con la semántica de
  Gendreau (coincide con el validador de Krebs en 2,436 de 2,436 acomodos). Corrige un defecto de 1.0.0:
  una caja de una entrega posterior podía quedar encima de una anterior.
- **Corrección de transparencia:** en 1.0.0, si una ruta no cabía respetando el orden de descarga, el
  motor lo relajaba en silencio, ruta por ruta, antes de intentar la mediación. Ahora la mediación trabaja
  primero con el orden estricto y, sólo si una ruta sigue sin caber, se relaja **y se informa**: campos
  nuevos `lifo_estricto` y `advertencias` en la respuesta (además de `lifo_respetado` por ruta, que ya
  existía). En las 12 instancias de producto con todas las restricciones, la 1.0.0 entregaba 24 de 24
  planes "factibles" sin orden de descarga; la 1.1.0 entrega 19 de 24 con orden estricto y avisa en las
  otras 5.
- **Flota "hasta k"** (`"fleet_mode": "up_to"`, opcional): el motor puede usar menos unidades de las
  disponibles. En instancias pequeñas (hasta 60 entregas y 30 cajas por unidad) activa **R3L**, un ruteo
  que revisa si la carga cabe en cada paso de la búsqueda: en las 19 instancias de Gendreau con
  óptimos de Tamke, 284 de 285 soluciones válidas y +8.1 % de distancia a 10 s (1.0.0: 81 de 285 válidas,
  +26 %). Por omisión la flota sigue siendo exacta, como en 1.0.0.
- **Respaldo del constructor de flota exacta:** cuando la carga apenas cabe en k unidades, el constructor
  de 1.0.0 podía fallar (11 de 41 instancias X); ahora se reparte aceptando sobrecarga y se elimina con
  búsqueda local.
- Compilación con MinGW g++ en Windows: el runtime de GCC queda dentro de las DLL
  (`-static-libgcc -static-libstdc++`). Antes las DLL dependían de `libstdc++-6.dll`, que Python
  3.8+ no busca en el PATH, y el motor no cargaba.
- Documentadas las dos huellas deterministas según la biblioteca estándar de C++ (zig/libc++ y
  g++/libstdc++); el CI publica la suya como anotación.
- Empacador 3D: con cajas idénticas, si el voraz de puntos extremos no las coloca todas, se
  prueba un patrón por capas (guillotina óptima de la base, repetida en altura) y se conserva el
  que coloque más. Ejemplo: cajas de 40 × 30 × 30 cm en una van de 337 × 137 × 178 cm pasan de
  160 a 175. Las cargas mixtas no cambian; la huella determinista tampoco.
- Huella determinista nueva; desde esta versión incluye la versión del motor, para que nunca coincida con
  la de otra versión.

*[English version](docs/en/CHANGELOG.md)*

## 1.0.0 — 30 de septiembre de 2026

Primera versión pública.

- Motor `lattimex-engine-1.6.0`, el mismo que corre en producción: ruteo SENDA en C++ con portafolio
  en paralelo, capacidad efectiva, empacador 3D nativo, mediación con flota fija y plan de descarga
  por puertas. Huella determinista: `6457b2dd44660773` con zig/libc++ (ver [AUTHORSHIP.md](AUTHORSHIP.md)).
- Servidor local (`python -m lattimex serve`) para el LATTIMEX Planner: escucha solo en 127.0.0.1,
  acepta únicamente el origen del Planner, valida Host y usa un token de sesión por arranque.
  - Un solo servidor por puerto (en Windows, `SO_EXCLUSIVEADDRUSE`): un segundo servidor falla con
    un error claro en lugar de compartir el puerto en silencio.
  - `--allow-origin` agrega orígenes permitidos; lattimex.com siempre está permitido.
  - El portafolio usa hasta 4 hilos (configurable con `LATTIMEX_THREADS`).
  - La matriz de distancias se calcula en segundo plano al ubicar las guías y se reutiliza mientras
    las entregas no cambien (300 entregas: ~24 s por corrida en el Planner, frente a ~60 s si se
    recalculara cada vez).
  - La operación activa y las guías capturadas sin guardar (borrador) se conservan al cerrar el
    Planner o reiniciar el servidor.
  - Precio del combustible automático (mediana de los precios vigentes de la CRE cerca del centro de
    distribución) o manual (`/api/settings/fuel`).
  - `--data CARPETA` elige la carpeta de datos (base, resultados y mapas) en cualquier comando.
  - Borrado de guías y de ejecuciones guardadas (`DELETE /api/instances/<id>/guides/<guía>`,
    `DELETE /api/planning-runs[/id]`).
- Mapas propios desde OpenStreetMap (`python -m lattimex map`): grafo vial para el motor y capa de
  calles propia; el cálculo no usa servicios externos (el Planner solo pide teselas de OpenStreetMap
  como fondo visual).
- Compilación portátil (`python -m lattimex build`) con g++, clang++ o `ziglang`.
- Ventana de inicio sin terminal (`python -m lattimex app`): arranca el motor, prepara el mapa de la
  ciudad, abre el Planner y cambia la carpeta de datos. Se empaqueta como aplicación e instalador de
  Windows (`packaging/windows/`).
- Guía educativa del núcleo de ruteo en `paper/` (CC BY 4.0), en español y en inglés, con una
  sección de complejidad computacional y otra para repetir las mediciones.
- Avisos de procedencia de Mulberry32 (Tommy Ettinger, CC0-1.0), distinción entre datos e imágenes
  de OpenStreetMap y aviso de licencia de la guía incluido en el PDF y sus metadatos.
- Pruebas: 42 del motor, 72 casos de equivalencia C++/Python del empacador, 13 del servidor y huella
  determinista (`python -m lattimex probe`).
