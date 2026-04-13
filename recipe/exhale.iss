#define MyAppName "EXHALE"
#ifndef MyAppVersion
  #define MyAppVersion "dev"
#endif
#define MyAppPublisher "CIPA / Lund University"
#define MyAppExeName "exhale.exe"

[Setup]
AppId={{C0B9C2F3-8D76-4E78-9D76-6C2A6D6C1234}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename=exhale-{#MyAppVersion}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\exhale\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\EXHALE"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\EXHALE"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch EXHALE"; Flags: nowait postinstall skipifsilent
