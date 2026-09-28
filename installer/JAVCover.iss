; JAVCover Inno Setup script
;
; Build the onedir distribution first:  .\build.ps1 -Mode onedir
; Then compile this script with Inno Setup 6 (https://jrsoftware.org/isinfo.php):
;   iscc installer\JAVCover.iss
; The installer produced in .\release does NOT require the user to have Python.

#define AppName "JAVCover"
#define AppVersion "1.0.0"
#define AppPublisher "JAVCover"
#define AppExeName "JAVCover.exe"

[Setup]
AppId={{8C1E2A54-7B3D-4F6A-9E21-0C1A2B3C4D5E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=JAVCover-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："

[Files]
Source: "..\dist\JAVCover\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
