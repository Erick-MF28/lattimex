# Autoría y procedencia

*[English version](docs/en/AUTHORSHIP.md)*

**Obra:** LATTIMEX — motor de ruteo con acomodo 3D de carga, servidor local y generador de mapas.
**Titular:** Erick Alan Martínez Fuentes, persona física, Querétaro, México. "LATTIMEX" es el nombre comercial con el que opera.
**Licencia de esta distribución:** MIT (ver LICENSE).

## Origen

Desarrollo independiente: el motor es producto de una línea de investigación propia del titular,
sin afiliación institucional ni cesión de derechos, contrato laboral o institucional que afecte al
código. Este repositorio contiene el mismo motor que corre en producción en el LATTIMEX Planner.

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

| Elemento | Valor |
|---|---|
| Versión del repositorio | 1.0.0 |
| Versión del motor | lattimex-engine-1.6.0 (en producción desde el 4/09/2026) |
| SHA-256 de `native/senda_core.cpp` (finales de línea LF) | `d63db4bc643628e196e24219a483ee99ef420d0596e1c927f1cdf9892e77fa01` |
| SHA-256 de `native/pack3d.cpp` (finales de línea LF) | `915f13dd6fbb1d1c3b1c8bb3b3f759b6b302070ff27c83d5cb87dd5443c56b6c` |
| Huella determinista (`python -m lattimex probe`) | `6457b2dd44660773` (4 rutas, 9 151 m, 3 000 iteraciones) |

La huella determinista no depende del compilador: dos binarios compilados del mismo fuente deben
dar la misma huella aunque el hash del archivo binario sea distinto. El manifiesto SHA-256 de los
archivos de esta copia se conserva en el expediente privado de auditoría y no se distribuye en
este repositorio.
