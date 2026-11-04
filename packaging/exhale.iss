; Native launcher + private uv environment. Build with packaging/win_build.py.
#include "..\dist\windows-payload\release.iss"
#define MyAppName "EXHALE"
#define MyAppPublisher "CIPA / Lund University"

[Setup]
AppId={{C0B9C2F3-8D76-4E78-9D76-6C2A6D6C1234}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Exhale
DefaultGroupName=EXHALE
OutputDir=..\dist
OutputBaseFilename=exhale-{#MyAppVersion}-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icons\xrf.ico
UninstallDisplayIcon={app}\exhale.exe
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=EXHALEDesktopRuntime
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "standard"; Description: "StarDist segmentation"
Name: "full"; Description: "StarDist and Cellpose segmentation"
Name: "compact"; Description: "Viewing and composition without segmentation"
Name: "custom"; Description: "Choose segmentation backends"; Flags: iscustom

[Components]
Name: "core"; Description: "EXHALE, private Python and application libraries"; Types: standard full compact custom; Flags: fixed
Name: "stardist"; Description: "StarDist (TensorFlow)"; Types: standard full
Name: "cellpose"; Description: "Cellpose (PyTorch and DINOv3)"; Types: full

[Files]
; Temporary copies validate the runtime before installed launcher files are replaced.
Source: "..\dist\windows-payload\exhale.exe"; Flags: dontcopy
Source: "..\dist\windows-payload\uv.exe"; Flags: dontcopy
Source: "..\dist\windows-payload\setup.json"; Flags: dontcopy
Source: "..\dist\windows-payload\{#WheelFile}"; Flags: dontcopy
Source: "..\dist\windows-payload\requirements-cellpose.txt"; Flags: dontcopy
Source: "..\dist\windows-payload\*"; DestDir: "{app}"; Excludes: "release.iss"; Flags: ignoreversion

[Icons]
Name: "{group}\EXHALE"; Filename: "{app}\exhale.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\EXHALE"; Filename: "{app}\exhale.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; Flags: unchecked

[Run]
Filename: "{app}\exhale.exe"; Description: "Launch EXHALE"; Flags: nowait postinstall skipifsilent; Check: RuntimeActivated

[InstallDelete]
; Obsolete PyInstaller runtime from older installations; never user data.
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: files; Name: "{app}\runtime.lock"
Type: files; Name: "{app}\runtime.log"

[Code]
var
  Prepared: Boolean;
  Activated: Boolean;
  PreparedSelection: String;
  SetupFailed: Boolean;

function SelectedBackends: String;
begin
  if WizardIsComponentSelected('stardist') then begin
    if WizardIsComponentSelected('cellpose') then Result := 'both'
    else Result := 'stardist';
  end else begin
    if WizardIsComponentSelected('cellpose') then Result := 'cellpose'
    else Result := 'none';
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Parameters: String;
begin
  Result := '';
  if CheckForMutexes('EXHALEDesktopRuntime') then begin
    Result := 'Please close EXHALE before continuing.';
    Exit;
  end;
  if Prepared and (PreparedSelection = SelectedBackends) then Exit;
  Prepared := False;
  ExtractTemporaryFile('exhale.exe');
  ExtractTemporaryFile('uv.exe');
  ExtractTemporaryFile('setup.json');
  ExtractTemporaryFile('{#WheelFile}');
  ExtractTemporaryFile('requirements-cellpose.txt');
  Parameters := '--prepare-install ' + SelectedBackends +
    ' --install-root "' + ExpandConstant('{app}') + '"';
  if WizardSilent then Parameters := Parameters + ' --quiet';
  WizardForm.StatusLabel.Caption := 'Downloading Python and selected libraries. This may take several minutes.';
  if not Exec(ExpandConstant('{tmp}\exhale.exe'), Parameters, '', SW_SHOWNORMAL,
      ewWaitUntilTerminated, ExitCode) then
    Result := 'Could not start EXHALE runtime setup.'
  else if ExitCode <> 0 then
    Result := 'EXHALE runtime setup failed. See ' + ExpandConstant('{app}\runtime.log') + '. You can retry.'
  else begin
    Prepared := True;
    PreparedSelection := SelectedBackends;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    Activated := Exec(ExpandConstant('{app}\exhale.exe'), '--activate-install --quiet',
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
    Activated := Activated and (ExitCode = 0);
    if not Activated then begin
      SetupFailed := True;
      if not WizardSilent then
        MsgBox('EXHALE could not activate its runtime. Please rerun setup. See ' +
          ExpandConstant('{app}\runtime.log'), mbError, MB_OK);
    end;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if SetupFailed then Result := 9 else Result := 0;
end;

procedure DeinitializeSetup;
var
  ExitCode: Integer;
begin
  if not Activated and FileExists(ExpandConstant('{tmp}\exhale.exe')) then
    Exec(ExpandConstant('{tmp}\exhale.exe'), '--discard-install --quiet --install-root "' +
      ExpandConstant('{app}') + '"', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
end;

function RuntimeActivated: Boolean;
begin
  Result := Activated;
end;
