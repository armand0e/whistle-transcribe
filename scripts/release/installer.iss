#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef BundleDir
  #error BundleDir must point to the tested PyInstaller bundle
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif
[Setup]
AppId={code:ApplicationId}
UsePreviousLanguage=no
AppName=Whistle
AppVersion={#AppVersion}
AppPublisher=Whistle Transcribe contributors
AppPublisherURL=https://github.com/armand0e/whistle-transcribe
AppUpdatesURL=https://github.com/armand0e/whistle-transcribe/releases
DefaultDirName={localappdata}\Programs\Whistle
DefaultGroupName=Whistle
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.20348
OutputDir={#OutputDir}
OutputBaseFilename=Whistle-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
SetupIconFile={#BundleDir}\_internal\whistle.ico
UninstallDisplayIcon={app}\Whistle.exe
LicenseFile=..\..\LICENSE

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Whistle"; Filename: "{app}\Whistle.exe"; WorkingDir: "{app}"; Check: CreateShortcuts
Name: "{userdesktop}\Whistle"; Filename: "{app}\Whistle.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Check: CreateShortcuts

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\Whistle.exe"; Parameters: "--skip-update"; Description: "Launch Whistle"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Whistle.exe"; Parameters: "--skip-update"; Flags: nowait skipifnotsilent; Check: LaunchAfterUpdate

[Code]
var
  LegacyDataDir, LegacyConfigDir: String;

function ApplicationId(Param: String): String;
begin
  if ExpandConstant('{param:ISOLATEDTEST|0}') = '1' then
    Result := 'Whistle.IsolatedInstallerTest'
  else
    Result := '{D22EAEBB-A226-47C9-A8D7-D7E402A5A90E}';
end;

function CreateShortcuts(): Boolean;
begin
  Result := ExpandConstant('{param:NOSHORTCUTS|0}') <> '1';
end;

function OpenProcess(dwDesiredAccess: LongWord; bInheritHandle: Boolean; dwProcessId: LongWord): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(hHandle: THandle; dwMilliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function InitializeSetup(): Boolean;
var
  ParentPid: Integer;
  Handle: THandle;
  ShortcutFile, Candidate: String;
  Shell, Shortcut: Variant;
begin
  Result := True;
  LegacyConfigDir := ExpandConstant('{localappdata}\Whistle');
  ShortcutFile := ExpandConstant('{userprograms}\Whistle.lnk');
  if ExpandConstant('{param:ISOLATEDTEST|0}') = '1' then begin
    LegacyConfigDir := ExpandConstant('{param:CONFIGTESTDIR|}');
    ShortcutFile := ExpandConstant('{param:LEGACYSHORTCUTTEST|}');
  end;
  ParentPid := StrToIntDef(ExpandConstant('{param:WHISTLEPID|0}'), 0);
  if ParentPid > 0 then begin
    Handle := OpenProcess($00100000, False, ParentPid);
    if Handle <> 0 then begin
      Result := WaitForSingleObject(Handle, 30000) = 0;
      CloseHandle(Handle);
    end;
    if not Result then
      MsgBox('Whistle did not close. Quit Whistle from the tray and run the update again.', mbError, MB_OK);
  end;
  { Recognize the old source install before its shortcut is replaced. Keep using
    its data; never move/delete recordings or copy the user's model cache. }
  if Result and (LegacyConfigDir <> '') and
     not FileExists(AddBackslash(LegacyConfigDir) + 'bootstrap.json') then begin
    if FileExists(ShortcutFile) then begin
      try
        Shell := CreateOleObject('WScript.Shell');
        Shortcut := Shell.CreateShortcut(ShortcutFile);
        Candidate := Shortcut.WorkingDirectory;
        if (CompareText(ExtractFileName(Shortcut.TargetPath), 'wscript.exe') = 0) and
           (Pos('launch whistle.vbs', Lowercase(Shortcut.Arguments)) > 0) and
           (FileExists(AddBackslash(Candidate) + 'src\app.py') or
            FileExists(AddBackslash(Candidate) + 'app.py')) and
           DirExists(AddBackslash(Candidate) + 'transcripts') then
          LegacyDataDir := Candidate;
      except
        { New installations keep the normal per-user data folder. }
      end;
    end;
  end;
end;

function LaunchAfterUpdate(): Boolean;
begin
  Result := ExpandConstant('{param:RUNAPP|0}') = '1';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigDir, ConfigFile, JsonPath: String;
begin
  if CurStep = ssPostInstall then begin
    SaveStringToFile(ExpandConstant('{app}\version.json'), '{"version":"{#AppVersion}"}', False);
    if LegacyDataDir <> '' then begin
      ConfigDir := LegacyConfigDir;
      ConfigFile := AddBackslash(ConfigDir) + 'bootstrap.json';
      if not FileExists(ConfigFile) then begin
        ForceDirectories(ConfigDir);
        JsonPath := LegacyDataDir;
        StringChangeEx(JsonPath, '\', '\\', True);
        StringChangeEx(JsonPath, '"', '\"', True);
        SaveStringToFile(ConfigFile, UTF8Encode('{"data_dir":"' + JsonPath + '"}'), False);
      end;
    end;
  end;
end;
