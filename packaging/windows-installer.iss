; Inno Setup script — builds Squeeze-Setup.exe, a normal Windows
; installer around the PyInstaller-built dist\Squeeze.exe: installs to
; the user's Programs folder, adds Start Menu (and optional desktop)
; shortcuts, and registers an uninstaller in Windows' "Installed apps".
;
; Build (after `pyinstaller packaging/squeeze.spec` has produced
; dist\Squeeze.exe), from the repo root on Windows:
;
;   iscc packaging\windows-installer.iss
;
; Output: dist\Squeeze-Setup.exe. GitHub Actions' windows runners have
; Inno Setup preinstalled, so .github/workflows/build.yml runs this
; automatically after every Windows build.

#define MyAppName "Squeeze"
#define MyAppVersion "1.0"
#define MyAppExeName "Squeeze.exe"

[Setup]
; Fixed AppId so a newer installer upgrades an existing install in place
; instead of creating a second entry in "Installed apps".
AppId={{C7A2E1D4-9B3F-4E6A-8C5D-2F1B7A9E4C63}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; lowest = per-user install (no admin/UAC prompt); {autopf} then resolves
; to %LocalAppData%\Programs instead of C:\Program Files.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Squeeze-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
