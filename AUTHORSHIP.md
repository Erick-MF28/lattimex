# Autoría y procedencia

*[English version](docs/en/AUTHORSHIP.md)*

**Obra:** LATTIMEX — motor de ruteo con acomodo 3D de carga, servidor local y generador de mapas.
**Titular:** Erick Alan Martínez Fuentes, persona física, Querétaro, México. "LATTIMEX" es el nombre comercial con el que opera.
**Licencia de esta distribución:** MIT (ver LICENSE).

## Origen

Desarrollo independiente: el motor es producto de una línea de investigación propia del titular,
sin afiliación institucional ni cesión de derechos, contrato laboral o institucional que afecte al
código. La versión 1.0.0 de este repositorio contenía el mismo motor que corría en producción en el
LATTIMEX Planner (1.6.0); la versión 1.1.0 trae el motor 1.7.0, descrito abajo.

## Código de terceros incorporado

La implementación del motor es propia, con una excepción identificada: el generador
pseudoaleatorio Mulberry32 de Tommy Ettinger, adaptado en `native/pack3d.cpp` y
`lattimex/engine/loading3d.py`. El autor publicó el original bajo
[CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/), con dedicación al dominio público.
Fuente: [publicación original de Mulberry32](https://gist.github.com/tommyettinger/46a874533244883189143505d203312c).
Ver [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

Comparación textual del código, revisada el 30/09/2026 (referencias y expediente
de auditoría conservados en privado):

| Comparación | Líneas idénticas (≥30 caracteres) | Fragmentos de 12 tokens en común |
|---|---|---|
| Fuentes nativas del motor vs HGS-CVRP (MIT, 19 archivos) | 0 | 2, genéricos (`std::vector<std::pair<double,`) |
| Fuentes nativas del motor vs FILO2 (GPL-3.0, 56 archivos) | 0 | 11, genéricos (`std::shuffle(removed.begin(), removed.end())`) |
| Empacador C++ y módulos Python de la tubería vs SolutionValidator de Krebs (GPL-3.0, 84 archivos, incluidos Java) | 0 | 0 |

La comparación normaliza espacios y descarta comentarios. Los fragmentos de tokens se comparan
dentro de cada archivo. Estos resultados aportan evidencia de procedencia; no constituyen una
prueba exhaustiva de autoría ni permiten detectar por sí solos toda traducción o adaptación.

Ningún identificador distintivo de HGS-CVRP (`Individual`, `CircleSector`, `SwapStarElement`,
`penaltyCapacity`, …) aparece en el núcleo, ni identificadores o comentarios que aludan a otros
motores por su nombre. Las ideas publicadas que el motor implementa se citan en
[docs/ACADEMIC_NOTES.md](docs/ACADEMIC_NOTES.md).

## Versiones y huellas

### Versión 1.1.0

| Elemento | Valor |
|---|---|
| Versión del repositorio | 1.1.0 |
| Versión del motor | lattimex-engine-1.7.0 |
| SHA-256 de `native/senda2_core.cpp` (finales de línea LF) | `b2a5a730ea429e98112a07fc46737f7dfd19a01c5c48229c65f18edbd8090ad8` |
| SHA-256 de `native/p3l.cpp` (finales de línea LF) | `afb81b4cd9ddf3d145a58941267840ee649f11392079b535acdd012df48050ba` |
| `native/senda_core.cpp` y `native/pack3d.cpp` | sin cambios respecto de 1.0.0 (huellas abajo) |
| Huella determinista con zig/libc++ (`python -m lattimex probe`) | `1102c21c0192b381` (4 rutas, 8 857 m, 3 000 iteraciones) |
| Huella determinista con g++/libstdc++ (Linux, MinGW) | `78f0de0f9d88d82b` (4 rutas, 8 857 m, 3 000 iteraciones; publicada por el CI) |

Comparación textual de los archivos nuevos de 1.1.0 (`senda2_core.cpp` en lo que agrega a
`senda_core.cpp`, `p3l.cpp`, `p3l_packer.py`, `r3l.py`, `exact_fleet_repair.py`, `cvrp.py`), con la
misma metodología, revisada en octubre de 2026: 0 líneas idénticas con HGS-CVRP, FILO2, el
SolutionValidator de Krebs (C++ y Java) y el código de Tamke et al. (MIT); 0 fragmentos de 12 tokens
en común con el validador de Krebs y sólo fragmentos genéricos (`std::vector<std::pair<double,`) con
los demás. P3L implementa la semántica pública de Gendreau et al. (2006) para el orden de descarga; el
validador de Krebs se usó sólo como juez externo, sin incorporar su código.

### Versión 1.0.0

| Elemento | Valor |
|---|---|
| Versión del repositorio | 1.0.0 |
| Versión del motor | lattimex-engine-1.6.0 (en producción desde el 4/09/2026) |
| SHA-256 de `native/senda_core.cpp` (finales de línea LF) | `d63db4bc643628e196e24219a483ee99ef420d0596e1c927f1cdf9892e77fa01` |
| SHA-256 de `native/pack3d.cpp` (finales de línea LF) | `915f13dd6fbb1d1c3b1c8bb3b3f759b6b302070ff27c83d5cb87dd5443c56b6c` |
| Huella determinista con zig/libc++ (`python -m lattimex probe`) | `6457b2dd44660773` (4 rutas, 9 151 m, 3 000 iteraciones) |
| Huella determinista con g++/libstdc++ (Linux, MinGW) | `285bf1758e5dd6a1` (4 rutas, 8 857 m, 3 000 iteraciones) |

La huella no depende de la optimización (`-O0`, `-O2` y `-O3` dan la misma) ni del hash del archivo
binario, pero sí de la biblioteca estándar de C++: `std::shuffle` y las distribuciones aleatorias
están implementadas de forma distinta en libc++ (zig) y en libstdc++ (g++), así que la misma semilla
recorre otra trayectoria. Las dos son soluciones válidas y cada compilación es determinista. El
motor en producción se compila con g++ en Linux; el instalador de Windows, con zig. El manifiesto SHA-256 de los
archivos de esta copia se conserva en el expediente privado de auditoría y no se distribuye en
este repositorio.
