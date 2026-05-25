; =============================================================================
; instalador_windows.iss — Inno Setup — Monitor de Postura v4
; Genera instalador .exe con un clic para Windows 10/11
; =============================================================================

#define AppName "Monitor de Postura"
#define AppVersion "4.0.0"
#define AppPublisher "Tu Nombre"
#define AppURL "https://github.com/tu-usuario/postura-monitor"
#define AppExeName "postura-monitor.exe"
#define DistDir "..\dist\postura-monitor"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=..\build_output
OutputBaseFilename=postura-monitor_{#AppVersion}_setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0.18362
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon";  Description: "Crear acceso directo en el &escritorio"; GroupDescription: "Iconos adicionales:"; Flags: unchecked
Name: "startupicon";  Description: "Iniciar con &Windows (modo producción)";  GroupDescription: "Inicio automático:";  Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";             Filename: "{app}\{#AppExeName}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";     Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#AppName}"; \
  ValueData: """{app}\{#AppExeName}"" --modo produccion"; \
  Flags: uninsdeletevalue; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; \
  Description: "Iniciar {#AppName} ahora"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'Este asistente instalará {#AppName} en tu computadora.' + #13#10 + #13#10 +
    'En el primer inicio se abrirá un asistente de configuración ' +
    'donde solo necesitas ingresar tu Chat ID de Telegram.' + #13#10 + #13#10 +
    'Se recomienda cerrar otras aplicaciones antes de continuar.';
end;
