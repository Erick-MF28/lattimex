# Authorship and provenance

*Translation of [AUTHORSHIP.md](../../AUTHORSHIP.md); the Spanish version prevails.*

**Work:** LATTIMEX — routing engine with 3D load placement, local server and map builder.
**Rights holder:** Erick Alan Martínez Fuentes, individual, Querétaro, Mexico. "LATTIMEX" is the trade name under which he operates.
**License of this distribution:** MIT (see [LICENSE](../../LICENSE)).

## Origin

Independent development: the engine is the product of the rights holder's own line of research,
with no institutional affiliation and no assignment of rights, employment or institutional contract
affecting the code. This repository contains the same engine that runs in production in the
LATTIMEX Planner.

## Third-party code incorporated

The implementation of the engine is original, with one identified exception: the Mulberry32
pseudorandom generator by Tommy Ettinger, adapted in `native/pack3d.cpp` and
`lattimex/engine/loading3d.py`. The author published the original under
[CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/), dedicated to the public domain.
Source: [original Mulberry32 publication](https://gist.github.com/tommyettinger/46a874533244883189143505d203312c).
See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

Textual comparison of the code, reviewed on 30/09/2026 (references and audit file kept
privately):

| Comparison | Identical lines (≥30 characters) | 12-token fragments in common |
|---|---|---|
| Native engine sources vs HGS-CVRP (MIT, 19 files) | 0 | 2, generic (`std::vector<std::pair<double,`) |
| Native engine sources vs FILO2 (GPL-3.0, 56 files) | 0 | 11, generic (`std::shuffle(removed.begin(), removed.end())`) |
| C++ packer and Python pipeline modules vs Krebs' SolutionValidator (GPL-3.0, 84 files, including Java) | 0 | 0 |

The comparison normalizes whitespace and discards comments. Token fragments are compared within each
file. These results provide evidence of provenance; they are not an exhaustive proof of authorship
and cannot by themselves detect every translation or adaptation.

No distinctive HGS-CVRP identifier (`Individual`, `CircleSector`, `SwapStarElement`,
`penaltyCapacity`, …) appears in the core, nor identifiers or comments that refer to other engines by
name. The published ideas that the engine implements are cited in
[ACADEMIC_NOTES.md](ACADEMIC_NOTES.md).

## Versions and fingerprints

| Item | Value |
|---|---|
| Repository version | 1.0.0 |
| Engine version | lattimex-engine-1.6.0 (in production since 4/09/2026) |
| SHA-256 of `native/senda_core.cpp` (LF line endings) | `d63db4bc643628e196e24219a483ee99ef420d0596e1c927f1cdf9892e77fa01` |
| SHA-256 of `native/pack3d.cpp` (LF line endings) | `915f13dd6fbb1d1c3b1c8bb3b3f759b6b302070ff27c83d5cb87dd5443c56b6c` |
| Deterministic fingerprint with zig/libc++ (`python -m lattimex probe`) | `6457b2dd44660773` (4 routes, 9 151 m, 3 000 iterations) |
| Deterministic fingerprint with g++/libstdc++ (Linux, MinGW) | `285bf1758e5dd6a1` (4 routes, 8 857 m, 3 000 iterations) |

The fingerprint does not depend on optimization (`-O0`, `-O2` and `-O3` give the same one) or on the
hash of the binary file, but it does depend on the C++ standard library: `std::shuffle` and the random
distributions are implemented differently in libc++ (zig) and libstdc++ (g++), so the same seed follows
another trajectory. Both are valid solutions and each build is deterministic. The production engine is
built with g++ on Linux; the Windows installer, with zig. The SHA-256
manifest of the files in this copy is kept in the private audit file and is not distributed in this
repository.
