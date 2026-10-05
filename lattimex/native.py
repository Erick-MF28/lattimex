# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Compilación y localización de las bibliotecas nativas del motor.

El motor de ruteo (native/senda_core.cpp) y el empacador 3D (native/pack3d.cpp)
se compilan en la computadora del usuario. Se usa, en este orden:
  1. el compilador indicado en la variable CXX,
  2. g++ o clang++ del sistema,
  3. el compilador zig distribuido por PyPI (`pip install ziglang`), útil en Windows
     cuando no hay Visual Studio ni MinGW.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIVE_SRC = ROOT / "native"
NATIVE_DIR = Path(__file__).resolve().parent / "_native"
ENGINE_DIR = Path(__file__).resolve().parent / "engine"

SUFFIX = {"Windows": ".dll", "Darwin": ".dylib"}.get(platform.system(), ".so")
CORE_LIB = NATIVE_DIR / f"libsenda{SUFFIX}"
PACK_LIB = NATIVE_DIR / f"liblattimex_pack3d{SUFFIX}"
TARGETS = ((NATIVE_SRC / "senda_core.cpp", CORE_LIB), (NATIVE_SRC / "pack3d.cpp", PACK_LIB))


def _compiler() -> list[str]:
    if os.environ.get("CXX"):
        return os.environ["CXX"].split()
    for name in ("g++", "clang++"):
        if shutil.which(name):
            return [name]
    try:
        import ziglang  # noqa: F401,PLC0415
        return [sys.executable, "-m", "ziglang", "c++"]
    except ImportError as exc:
        raise RuntimeError(
            "No se encontró un compilador de C++. Instale g++/clang++ o ejecute "
            "`pip install ziglang` y vuelva a intentar."
        ) from exc


def build(verbose: bool = True) -> list[Path]:
    """Compila ambas bibliotecas en lattimex/_native/."""
    NATIVE_DIR.mkdir(parents=True, exist_ok=True)
    cxx = _compiler()
    zig = "ziglang" in " ".join(cxx)
    flags = ["-O3", "-std=c++17", "-shared", "-Wno-nullability-completeness" if zig else "-Wall"]
    if platform.system() != "Windows":
        flags += ["-fPIC", "-pthread"]
    elif zig:
        flags += ["-target", "x86_64-windows-gnu"]
    elif "g++" in os.path.basename(cxx[0]).lower():
        # MinGW: sin esto la DLL depende de libstdc++-6.dll y libgcc_s_seh-1.dll, que Python 3.8+
        # no busca en el PATH, y el motor no carga ("Could not find module ... or one of its
        # dependencies"). Enlazar el runtime de GCC dentro de la DLL la deja autónoma.
        flags += ["-static", "-static-libgcc", "-static-libstdc++"]
    built = []
    for source, target in TARGETS:
        cmd = [*cxx, *flags, "-o", str(target), str(source)]
        if verbose:
            print("compilando", source.name, "->", target.name)
        subprocess.run(cmd, check=True, cwd=NATIVE_DIR)
        built.append(target)
    for extra in NATIVE_DIR.glob("*.pdb"):
        extra.unlink()
    for extra in NATIVE_DIR.glob("*.lib"):
        extra.unlink()
    return built


def configure() -> None:
    """Expone el motor a Python: rutas de las bibliotecas y módulos del motor.

    Los módulos de lattimex/engine se conservan idénticos a los de producción y
    se importan por nombre (import engine_runtime), por eso se agregan a sys.path.
    """
    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    if CORE_LIB.exists():
        os.environ.setdefault("LATTIMEX_CORE", str(CORE_LIB))
    if PACK_LIB.exists():
        os.environ.setdefault("LATTIMEX_PACK3D", str(PACK_LIB))


def status() -> dict:
    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "python": sys.version.split()[0],
        "core": str(CORE_LIB) if CORE_LIB.exists() else None,
        "pack3d": str(PACK_LIB) if PACK_LIB.exists() else None,
    }
