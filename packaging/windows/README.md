# LATTIMEX para Windows (sin terminal)

*English below.*

Para quien no usa la terminal: un instalador que deja en el menú Inicio el acceso **LATTIMEX**.
Al abrirlo, una ventana arranca el motor local, prepara el mapa de su ciudad la primera vez (se
descarga una sola vez de OpenStreetMap) y abre el Planner en el navegador. Desde la misma ventana se
cambia la carpeta de datos o se detiene el motor.

- Se instala para el usuario actual, sin permisos de administrador.
- Incluye Python, el motor compilado y sus dependencias; no hace falta instalar nada más.
- Los datos quedan en `%LOCALAPPDATA%\LATTIMEX` (o en la carpeta que elija) y no se borran al desinstalar.

## Construir el instalador

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Requiere Python 3.10+ de python.org. Genera `dist\LATTIMEX\LATTIMEX.exe` y, si está instalado
[Inno Setup 6](https://jrsoftware.org/isinfo.php), `dist\LATTIMEX-1.0.0-setup.exe`.

La misma ventana existe sin instalador: `python -m lattimex app`.

El logotipo y el ícono de `lattimex/assets/` son parte de la marca LATTIMEX y no están cubiertos por
la licencia MIT (ver [NOTICE](../../NOTICE)).

---

## English

For people who do not use the terminal: an installer that adds a **LATTIMEX** entry to the Start menu.
When opened, a window starts the local engine, prepares your city map the first time (downloaded once
from OpenStreetMap) and opens the Planner in the browser. The same window changes the data folder or
stops the engine.

- Installs for the current user, without administrator rights.
- Bundles Python, the compiled engine and its dependencies; nothing else needs to be installed.
- Data lives in `%LOCALAPPDATA%\LATTIMEX` (or the folder you choose) and is kept when uninstalling.

Build it with `packaging\windows\build.ps1` (Python 3.10+ from python.org; Inno Setup 6 optional for
the setup file). The same window is available without the installer: `python -m lattimex app`.

The logo and icon in `lattimex/assets/` are part of the LATTIMEX trademark and are not covered by the
MIT license (see [NOTICE](../../NOTICE)).
