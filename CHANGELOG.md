# Cambios

## Sin publicar

- Compilación con MinGW g++ en Windows: el runtime de GCC queda dentro de las DLL
  (`-static-libgcc -static-libstdc++`). Antes las DLL dependían de `libstdc++-6.dll`, que Python
  3.8+ no busca en el PATH, y el motor no cargaba.
- Documentadas las dos huellas deterministas según la biblioteca estándar de C++ (zig/libc++ y
  g++/libstdc++); el CI publica la suya como anotación.

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
