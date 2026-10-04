# LATTIMEX para Windows: aplicación autocontenida e instalador.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# Resultado:
#   dist\LATTIMEX\LATTIMEX.exe          aplicación (Python, motor compilado y dependencias incluidos)
#   dist\LATTIMEX-1.0.0-setup.exe       instalador (si está instalado Inno Setup 6)
#
# Requisitos para construir: Python 3.10+ de python.org (con tkinter). El compilador de C++ se instala
# solo (ziglang). Inno Setup 6 es opcional: https://jrsoftware.org/isinfo.php
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$Venv = Join-Path $Root ".venv-build"

if (-not (Test-Path $Venv)) { python -m venv $Venv }
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --upgrade pip | Out-Null
& $Py -m pip install -r requirements.txt pyinstaller ziglang
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }

# 1. Motor y empacador compilados para esta máquina (solo dependen del runtime universal de Windows).
& $Py -m lattimex build
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación del motor." }
& $Py -m lattimex probe

# 2. Aplicación autocontenida.
& $Py -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller packaging\windows\lattimex.spec
if ($LASTEXITCODE -ne 0) { throw "Falló PyInstaller." }

# 3. Instalador (opcional).
$Iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Iscc) {
  & $Iscc packaging\windows\lattimex.iss
  if ($LASTEXITCODE -ne 0) { throw "Falló Inno Setup." }
  Write-Host "Instalador listo en dist\"
} else {
  Write-Host "Aplicación lista en dist\LATTIMEX\. Para generar el instalador instale Inno Setup 6 y vuelva a ejecutar."
}
