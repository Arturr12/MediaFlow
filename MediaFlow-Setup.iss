#define MyAppName "MediaFlow"
#ifndef MyAppVersion
  #define MyAppVersion "0.5.0"
#endif
#define MyAppPublisher "MediaFlow"
#define MyAppExeName "MediaFlow.exe"

[Setup]
AppId={{B46A88F2-31B1-4E2D-A846-3D4D83C762F1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\MediaFlow
DefaultGroupName=MediaFlow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=Output
OutputBaseFilename=MediaFlow-Setup-{#MyAppVersion}
SetupIconFile=mediaflow.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany=MediaFlow
VersionInfoDescription=Centro de descarga y conversion multimedia
VersionInfoProductName=MediaFlow

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "payload\MediaFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "support\Install-Dependencies.ps1"; DestDir: "{app}\support"; Flags: ignoreversion
Source: "support\Install-Update.ps1"; DestDir: "{app}\support"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\MediaFlow"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\MediaFlow"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\support\Install-Dependencies.ps1"""; StatusMsg: "Comprobando e instalando FFmpeg y Deno..."; Flags: waituntilterminated runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir MediaFlow"; Flags: postinstall nowait skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsWin64 then
  begin
    MsgBox('MediaFlow 0.5.0 requiere Windows de 64 bits.', mbError, MB_OK);
    Result := False;
  end;
end;
