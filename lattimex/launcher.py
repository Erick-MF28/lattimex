# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Ventana de inicio de LATTIMEX para quien no usa la terminal.

    python -m lattimex app

Arranca el servidor local, prepara el mapa de la ciudad la primera vez, abre el Planner y permite
elegir la carpeta de datos. Es la misma aplicación que instala el instalador de Windows.
"""
from __future__ import annotations

import json
import locale
import os
import queue
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__, ENGINE_VERSION

PLANNER_URL = "https://lattimex.com/planner"
PORT = 8765
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LATTIMEX"
SETTINGS = APP_DIR / "launcher.json"
DEFAULT_DATA = APP_DIR / "data" if FROZEN else Path(__file__).resolve().parent.parent / "data"
ASSETS = Path(__file__).resolve().parent / "assets"   # logotipo e ícono (marca LATTIMEX, ver NOTICE)

# Rectángulos aproximados (sur, oeste, norte, este); el usuario puede escribir otro.
CITIES = {
    "Querétaro": (20.47, -100.52, 20.82, -100.22),
    "Ciudad de México (centro)": (19.30, -99.25, 19.52, -99.05),
    "Guadalajara": (20.55, -103.50, 20.80, -103.23),
    "Monterrey": (25.55, -100.45, 25.80, -100.15),
    "Puebla": (18.95, -98.30, 19.12, -98.10),
    "León": (21.05, -101.75, 21.20, -101.60),
    "San Luis Potosí": (22.08, -101.05, 22.20, -100.90),
    "Aguascalientes": (21.80, -102.35, 21.95, -102.22),
    "Mérida": (20.90, -89.70, 21.07, -89.55),
    "Tijuana": (32.40, -117.15, 32.55, -116.85),
}

ES = locale.getdefaultlocale()[0] or ""
ES = ES.lower().startswith("es")
T = {
    "title": ("LATTIMEX", "LATTIMEX"),
    "subtitle": ("Motor de ruteo con acomodo 3D, en su computadora", "Vehicle routing with 3D loading, on your computer"),
    "starting": ("Iniciando el motor local…", "Starting the local engine…"),
    "running": ("Motor local listo en http://127.0.0.1:{port} · mapa {map}", "Local engine ready at http://127.0.0.1:{port} · map {map}"),
    "nomap": ("Falta el mapa de su ciudad. Elíjala y presione Preparar mapa (se descarga una sola vez).",
              "Your city map is missing. Choose it and press Prepare map (downloaded only once)."),
    "city": ("Ciudad", "City"), "other": ("Otra (rectángulo sur,oeste,norte,este)", "Other (box south,west,north,east)"),
    "prepare": ("Preparar mapa", "Prepare map"),
    "preparing": ("Descargando calles de OpenStreetMap y preparando el mapa… (puede tardar unos minutos)",
                  "Downloading OpenStreetMap streets and preparing the map… (may take a few minutes)"),
    "open": ("Abrir el Planner", "Open the Planner"), "folder": ("Abrir carpeta de datos", "Open data folder"),
    "change": ("Cambiar carpeta…", "Change folder…"), "quit": ("Detener y salir", "Stop and quit"),
    "data": ("Datos: {path}", "Data: {path}"),
    "already": ("LATTIMEX ya está en ejecución. Se abrirá el Planner.", "LATTIMEX is already running. The Planner will open."),
    "error": ("No se pudo iniciar el motor: {e}", "The engine could not start: {e}"),
    "bbox": ("Escriba el rectángulo como sur,oeste,norte,este (grados decimales).", "Enter the box as south,west,north,east (decimal degrees)."),
    "privacy": ("Sus datos se quedan en esta computadora. El Planner se abre en el navegador y se conecta solo a este motor.",
                "Your data stays on this computer. The Planner opens in the browser and connects only to this engine."),
    "license": ("Motor: licencia MIT · Planner: uso gratuito · Datos de calles © colaboradores de OpenStreetMap (ODbL)",
                "Engine: MIT license · Planner: free to use · Street data © OpenStreetMap contributors (ODbL)"),
}


def tr(key: str, **kw) -> str:
    return T[key][0 if ES else 1].format(**kw)


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def engine_running(port: int = PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as response:
            return response.status == 200
    except OSError:
        return False


class QueueWriter:
    """Recibe lo que el servidor imprime (en la app de Windows no hay consola)."""

    def __init__(self, sink: queue.Queue):
        self.sink = sink

    def write(self, text: str) -> int:
        if text.strip():
            self.sink.put(text.rstrip())
        return len(text)

    def flush(self) -> None:
        pass


class Launcher:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.settings = load_settings()
        self.data_dir = Path(self.settings.get("data_dir") or DEFAULT_DATA)
        self.server = None
        self.logs: queue.Queue = queue.Queue()
        sys.stdout = sys.stderr = QueueWriter(self.logs)

        _dpi_aware()
        self.root = tk.Tk()
        self.root.title("LATTIMEX")
        # Escala de Windows (100 %, 150 %, 200 %…): medidas y logotipo nítidos en cualquier pantalla.
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        px = lambda v: int(v * self.scale)
        self.root.geometry(f"{px(660)}x{px(500)}")
        self.root.minsize(px(580), px(440))
        icon = ASSETS / "lattimex.ico"
        if icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self._build()
        self.root.after(200, self.start_server)
        self.root.after(300, self._drain_logs)

    # --- interfaz ---------------------------------------------------------------------------------
    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        pad = {"padx": 18}
        head = tk.Frame(self.root, bg="#0a1222")
        head.pack(fill="x")
        logo = ASSETS / f"marca_{min((100, 150, 200), key=lambda v: abs(v - self.scale * 100))}.png"
        try:
            self.logo = tk.PhotoImage(file=str(logo))
            tk.Label(head, image=self.logo, bg="#0a1222", bd=0).pack(anchor="w", padx=10, pady=(10, 0))
        except tk.TclError:
            tk.Label(head, text="LATTIMEX", fg="white", bg="#0a1222", font=("Arial Black", 18)).pack(anchor="w", padx=18, pady=(14, 0))
        tk.Label(head, text=tr("subtitle"), fg="#9ba7c0", bg="#0a1222", font=("Segoe UI", 10)).pack(anchor="w", padx=18, pady=(2, 14))

        self.status = tk.StringVar(value=tr("starting"))
        ttk.Label(self.root, textvariable=self.status, wraplength=590, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 6), **pad)

        self.map_box = ttk.Frame(self.root)
        ttk.Label(self.map_box, text=tr("city")).grid(row=0, column=0, sticky="w")
        self.city = tk.StringVar(value=next(iter(CITIES)))
        values = [*CITIES, tr("other")]
        self.city_combo = ttk.Combobox(self.map_box, textvariable=self.city, values=values, state="readonly", width=34)
        self.city_combo.grid(row=0, column=1, padx=8)
        self.bbox = tk.StringVar()
        self.bbox_entry = ttk.Entry(self.map_box, textvariable=self.bbox, width=34)
        self.prepare_btn = ttk.Button(self.map_box, text=tr("prepare"), command=self.prepare_map)
        self.prepare_btn.grid(row=0, column=2)
        self.city_combo.bind("<<ComboboxSelected>>", self._city_changed)

        actions = ttk.Frame(self.root)
        actions.pack(fill="x", pady=8, **pad)
        self.open_btn = ttk.Button(actions, text=tr("open"), command=lambda: webbrowser.open(PLANNER_URL), state="disabled")
        self.open_btn.pack(side="left")
        ttk.Button(actions, text=tr("folder"), command=self.open_folder).pack(side="left", padx=6)
        ttk.Button(actions, text=tr("change"), command=self.change_folder).pack(side="left")
        ttk.Button(actions, text=tr("quit"), command=self.quit).pack(side="right")

        self.data_label = tk.StringVar(value=tr("data", path=self.data_dir))
        ttk.Label(self.root, textvariable=self.data_label, foreground="#4a5468").pack(anchor="w", **pad)
        ttk.Label(self.root, text=tr("privacy"), wraplength=590, foreground="#4a5468").pack(anchor="w", pady=(6, 6), **pad)

        self.log = tk.Text(self.root, height=9, wrap="word", font=("Consolas", 9), bg="#f6f5f1", relief="flat")
        self.log.pack(fill="both", expand=True, pady=(4, 6), **pad)
        ttk.Label(self.root, text=f"{tr('license')} · LATTIMEX {__version__} · {ENGINE_VERSION}",
                  foreground="#5f6779", font=("Segoe UI", 8), wraplength=590).pack(anchor="w", pady=(0, 10), **pad)

    def _city_changed(self, _event=None) -> None:
        if self.city.get() == tr("other"):
            self.bbox_entry.grid(row=1, column=1, padx=8, pady=6, sticky="we")
        else:
            self.bbox_entry.grid_forget()

    def _drain_logs(self) -> None:
        while not self.logs.empty():
            self.log.insert("end", self.logs.get() + "\n")
            self.log.see("end")
        self.root.after(300, self._drain_logs)

    # --- servidor ---------------------------------------------------------------------------------
    def maps(self) -> list[str]:
        folder = self.data_dir / "maps"
        return sorted(p.stem for p in folder.glob("*.json") if not p.name.endswith(".roads.json")) if folder.exists() else []

    def start_server(self) -> None:
        if not self.maps():
            self.status.set(tr("nomap"))
            self.map_box.pack(fill="x", padx=18, pady=(0, 6))
            return
        self.map_box.pack_forget()
        self.status.set(tr("starting"))
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        try:
            from . import native
            from .server import serve, DEFAULT_ORIGINS
            native.configure()
            name = self.settings.get("map") if self.settings.get("map") in self.maps() else self.maps()[0]
            self.server = serve(self.data_dir, PORT, name, DEFAULT_ORIGINS)
            self.root.after(0, lambda: self._ready(name))
            self.server.serve_forever()
        except Exception as exc:                    # noqa: BLE001 - se muestra al usuario
            self.root.after(0, lambda: self.status.set(tr("error", e=exc)))

    def _ready(self, name: str) -> None:
        self.status.set(tr("running", port=PORT, map=name))
        self.open_btn.configure(state="normal")
        if not self.settings.get("opened_once"):
            self.settings["opened_once"] = True
            save_settings(self.settings)
            webbrowser.open(PLANNER_URL)

    def stop_server(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def prepare_map(self) -> None:
        if self.city.get() == tr("other"):
            try:
                bbox = tuple(float(v) for v in self.bbox.get().split(","))
                assert len(bbox) == 4 and bbox[0] < bbox[2] and bbox[1] < bbox[3]
                name = "ciudad"
            except (ValueError, AssertionError):
                self.status.set(tr("bbox"))
                return
        else:
            bbox, name = CITIES[self.city.get()], _slug(self.city.get())
        self.prepare_btn.configure(state="disabled")
        self.status.set(tr("preparing"))

        def work() -> None:
            try:
                from . import maps
                source = self.data_dir / "osm" / f"{name}.osm"
                if not source.exists():
                    maps.download_osm(bbox, source)
                meta = maps.build_map(source, name, self.data_dir / "maps")
                print(f"Mapa listo: {meta['name']} ({meta['nodes']:,} nodos)")
                self.settings["map"] = name
                save_settings(self.settings)
                self.root.after(0, self.start_server)
            except Exception as exc:                # noqa: BLE001
                self.root.after(0, lambda: self.status.set(tr("error", e=exc)))
            finally:
                self.root.after(0, lambda: self.prepare_btn.configure(state="normal"))
        threading.Thread(target=work, daemon=True).start()

    # --- carpeta de datos -------------------------------------------------------------------------
    def open_folder(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.data_dir) if hasattr(os, "startfile") else webbrowser.open(self.data_dir.as_uri())

    def change_folder(self) -> None:
        from tkinter import filedialog
        chosen = filedialog.askdirectory(initialdir=str(self.data_dir), mustexist=False)
        if not chosen:
            return
        self.stop_server()
        self.data_dir = Path(chosen)
        self.settings["data_dir"] = str(self.data_dir)
        save_settings(self.settings)
        self.data_label.set(tr("data", path=self.data_dir))
        self.open_btn.configure(state="disabled")
        self.start_server()

    def quit(self) -> None:
        self.stop_server()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _dpi_aware() -> None:
    """En Windows: dibujar a la resolución real (sin borroso) y agrupar la ventana con su ícono."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LATTIMEX.Local")
    except (AttributeError, OSError):
        pass


def _slug(name: str) -> str:
    import unicodedata
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return "_".join("".join(c if c.isalnum() else " " for c in plain).split())


def main() -> None:
    if engine_running():
        try:
            import tkinter.messagebox as mb
            import tkinter as tk
            root = tk.Tk(); root.withdraw()
            mb.showinfo("LATTIMEX", tr("already")); root.destroy()
        except Exception:                           # noqa: BLE001
            pass
        webbrowser.open(PLANNER_URL)
        return
    Launcher().run()


if __name__ == "__main__":
    main()
