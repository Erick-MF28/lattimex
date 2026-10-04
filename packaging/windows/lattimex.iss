; Instalador de LATTIMEX para Windows (Inno Setup 6). Lo ejecuta build.ps1 después de PyInstaller.
; Se instala para el usuario actual (sin permisos de administrador) en %LOCALAPPDATA%\Programs\LATTIMEX.
; Los datos (mapas, base y resultados) quedan en %LOCALAPPDATA%\LATTIMEX y no se borran al desinstalar.

#define AppName "LATTIMEX"
#define AppVersion "1.0.0"

[Setup]
AppId={{6F3E2B1A-9C4D-4E7B-8A51-3D2C7F0B9E41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=LATTIMEX
AppPublisherURL=https://lattimex.com
AppSupportURL=https://github.com/Erick-MF28/lattimex
DefaultDirName={localappdata}\Programs\LATTIMEX
DefaultGroupName=LATTIMEX
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=LATTIMEX-{#AppVersion}-setup
SetupIconFile=..\..\lattimex\assets\lattimex.ico
UninstallDisplayIcon={app}\LATTIMEX.exe
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
es.LaunchApp=Iniciar LATTIMEX
en.LaunchApp=Start LATTIMEX
es.DesktopIcon=Crear un acceso directo en el escritorio
en.DesktopIcon=Create a desktop shortcut

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"

[Files]
Source: "..\..\dist\LATTIMEX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LATTIMEX"; Filename: "{app}\LATTIMEX.exe"
Name: "{autodesktop}\LATTIMEX"; Filename: "{app}\LATTIMEX.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LATTIMEX.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
