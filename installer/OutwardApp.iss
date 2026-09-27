#ifndef AppName
#define AppName "Outward App"
#endif

#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

#ifndef ProjectRoot
#define ProjectRoot ".."
#endif

[Setup]
AppId={{D2F067F3-B670-45D2-995D-FD1564712C8C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#ProjectRoot}\installer-output
OutputBaseFilename={#AppName} Setup-{#AppVersion}
SetupIconFile={#ProjectRoot}\assets\outward.ico
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"; Flags: unchecked

[Files]
Source: "{#ProjectRoot}\dist\{#AppName}.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppName}.exe"; Flags: nowait skipifnotsilent


