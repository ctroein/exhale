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
; The per-user uv runtime setup inherits this mitigation and can fail on junctions.
RedirectionGuard=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=EXHALEDesktopRuntime
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "standard"; Description: "StarDist segmentation"
Name: "full"; Description: "StarDist, Cellpose, MONAI U-Net and SMP U-Net"
Name: "compact"; Description: "Viewing and composition without segmentation"
Name: "custom"; Description: "Choose segmentation backends"; Flags: iscustom

[Components]
Name: "core"; Description: "EXHALE, private Python and application libraries"; Types: standard full compact custom; Flags: fixed; ExtraDiskSpaceRequired: {#SpaceCore}
Name: "stardist"; Description: "StarDist (TensorFlow)"; Types: standard full; ExtraDiskSpaceRequired: {#SpaceStarDist}
Name: "cellpose"; Description: "Cellpose, MONAI U-Net and SMP U-Net (PyTorch and DINOv3)"; Types: full; ExtraDiskSpaceRequired: {#SpacePyTorch}

[Files]
; Temporary copies prepare dependencies before installed launcher files are replaced.
Source: "..\dist\windows-payload\exhale.exe"; Flags: dontcopy
Source: "..\dist\windows-payload\uv.exe"; Flags: dontcopy
Source: "..\dist\windows-payload\setup.json"; Flags: dontcopy
Source: "..\dist\windows-payload\{#WheelFile}"; Flags: dontcopy
Source: "..\dist\windows-payload\requirements-cellpose.txt"; Flags: dontcopy
Source: "..\dist\windows-payload\*"; DestDir: "{app}"; Excludes: "release.iss"; Flags: ignoreversion

[Icons]
Name: "{group}\EXHALE"; Filename: "{app}\exhale.exe"; WorkingDir: "{app}"
Name: "{group}\EXHALE Setup"; Filename: "{app}\exhale.exe"; Parameters: "--setup"; WorkingDir: "{app}"
Name: "{autodesktop}\EXHALE"; Filename: "{app}\exhale.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; Flags: unchecked

[Run]
Filename: "{app}\exhale.exe"; Description: "Launch EXHALE"; Flags: nowait postinstall skipifsilent; Check: RuntimeActivated

[InstallDelete]
; Obsolete PyInstaller runtime from older installations; never user data.
Type: filesandordirs; Name: "{app}\_internal"
; Rendering is now selected within Exhale; remove the old dedicated shortcuts.
Type: files; Name: "{group}\EXHALE (Software OpenGL).lnk"
Type: files; Name: "{autodesktop}\EXHALE (Software OpenGL).lnk"

[UninstallDelete]
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

function SizeText(Bytes: Int64): String;
begin
  if Bytes < 1073741824 then Result := Format('%.0f MB', [Bytes / 1048576.0])
  else Result := Format('%.1f GB', [Bytes / 1073741824.0]);
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  RuntimeBytes, ModelBytes: Int64;
begin
  RuntimeBytes := {#RuntimeNone};
  ModelBytes := 0;
  if SelectedBackends = 'both' then RuntimeBytes := {#RuntimeBoth}
  else if SelectedBackends = 'stardist' then RuntimeBytes := {#RuntimeStarDist}
  else if SelectedBackends = 'cellpose' then RuntimeBytes := {#RuntimePyTorch};
  if WizardIsComponentSelected('stardist') then ModelBytes := ModelBytes + {#ModelsStarDist};
  if WizardIsComponentSelected('cellpose') then ModelBytes := ModelBytes + {#ModelsPyTorch};
  Result := MemoUserInfoInfo + NewLine + MemoDirInfo + NewLine + MemoTypeInfo +
    NewLine + MemoComponentsInfo + NewLine + MemoGroupInfo + NewLine + MemoTasksInfo +
    NewLine + NewLine + 'Estimated application and dependencies: ' + SizeText(RuntimeBytes) + NewLine +
    'The space requirement includes a download/cache and temporary-file reserve.';
  if ModelBytes > 0 then
    Result := Result + NewLine + 'Model downloads on first use: up to ' + SizeText(ModelBytes) + ' (additional).';
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


procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExitCode: Integer;
  Removed: Boolean;
  Parameters: String;
begin
  if CurUninstallStep = usUninstall then begin
    { After user confirmation, before Inno removes the native launcher. }
    Log('Removing private runtime using the launcher long-path cleanup.');
    Parameters := '--remove-runtime --quiet';
    if not UninstallSilent then Parameters := Parameters + ' --prompt-models'
    else if ExpandConstant('{param:REMOVEMODELS|0}') = '1' then
      Parameters := Parameters + ' --remove-models';
    Removed := Exec(ExpandConstant('{app}\exhale.exe'), Parameters,
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
    if (not Removed) or (ExitCode <> 0) or DirExists(ExpandConstant('{app}\runtime')) then begin
      Log('Private runtime cleanup failed; stopping uninstall. Launcher exit code: ' + IntToStr(ExitCode));
      if not UninstallSilent then
        MsgBox('EXHALE could not remove its private runtime. Close EXHALE and try again. See ' +
          ExpandConstant('{app}\runtime.log'), mbError, MB_OK);
      Abort;
    end;
    Log('Private runtime removed successfully.');
  end;
end;
