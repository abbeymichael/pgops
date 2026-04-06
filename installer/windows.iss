; PGOps - Inno Setup Installer Script
; Produces: PGOps-Setup.exe
; Requirements: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Build: ISCC.exe installer\windows.iss

#define MyAppName      "PGOps"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "PGOps"
#define MyAppURL       "https://github.com/yourname/pgops"
#define MyAppExeName   "PGOps.exe"
#define BuildDir       "..\dist\PGOps"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Installer output
OutputDir=..\dist\installer
OutputBaseFilename=PGOps-Setup-{#MyAppVersion}-Windows
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; UI
WizardStyle=modern
; Privileges — no admin needed (installs to user profile if not admin)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Architecture
ArchitecturesInstallIn64BitMode=x64compatible
; Uninstaller
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "{cm:CreateDesktopIcon}";  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon";    Description: "Start PGOps when Windows starts";                               Flags: unchecked

[Files]
; Copy entire PyInstaller output folder
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";                Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}";      Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}";          Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop PostgreSQL before uninstalling
Filename: "{localappdata}\PGOps\pgsql\bin\pg_ctl.exe"; Parameters: "stop -D ""{localappdata}\PGOps\pgdata"" -m fast"; Flags: runhidden; Check: FileExists(ExpandConstant('{localappdata}\PGOps\pgdata\PG_VERSION')); RunOnceId: "StopPostgres"

[Code]
// Optional: check for existing pgdata and warn user on uninstall
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    if DirExists(ExpandConstant('{localappdata}\PGOps\pgdata')) then begin
      if MsgBox(
        'Your database files are stored in:' + #13#10 +
        ExpandConstant('{localappdata}\PGOps') + #13#10#13#10 +
        'These will NOT be deleted by the uninstaller.' + #13#10 +
        'Delete them manually if you want to remove all data.',
        mbInformation, MB_OK
      ) = IDOK then begin
        // just inform, do not delete data automatically
      end;
    end;
  end;
end;
