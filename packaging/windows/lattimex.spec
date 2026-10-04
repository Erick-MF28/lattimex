# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: aplicación de Windows autocontenida (Python, motor compilado y dependencias).
# Se usa desde build.ps1; las bibliotecas del motor deben existir en lattimex/_native/.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
PKG = ROOT / "lattimex"

# Los módulos del motor se importan por nombre desde lattimex/engine (native.configure() agrega la
# carpeta a sys.path), así que viajan como archivos, igual que las bibliotecas compiladas.
datas = [(str(p), "lattimex/engine") for p in (PKG / "engine").glob("*.py")]
datas += [(str(p), "lattimex/_native") for p in (PKG / "_native").glob("*.dll")]
datas += [(str(p), "lattimex/assets") for p in (PKG / "assets").iterdir()]

# Dependencias de los módulos del motor (PyInstaller no analiza los archivos que viajan como datos).
ENGINE_IMPORTS = ["array", "collections", "copy", "ctypes", "dataclasses", "hashlib", "itertools", "json",
                  "math", "pickle", "statistics", "networkx", "numpy", "pyproj", "scipy.sparse",
                  "scipy.sparse.csgraph"]
hiddenimports = (collect_submodules("lattimex", filter=lambda name: not name.startswith("lattimex.engine")) + collect_submodules("scipy.sparse.csgraph")
                 + collect_submodules("networkx") + ENGINE_IMPORTS
                 + ["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox"])

a = Analysis([str(Path(SPECPATH) / "lattimex_app.py")], pathex=[str(ROOT)], datas=datas,
             hiddenimports=hiddenimports, excludes=["matplotlib", "pytest", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LATTIMEX", console=False,
          icon=str(PKG / "assets" / "lattimex.ico"), version=None)
coll = COLLECT(exe, a.binaries, a.datas, name="LATTIMEX")
