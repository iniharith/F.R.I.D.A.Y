#define MyAppName "F.R.I.D.A.Y. AI"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "INI HARITH"
#define MyAppExeName "FRIDAY-HUD.exe"

[Setup]
AppId={{2A72F9AF-43A0-4C79-A7A3-A8401B984AF1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\FridayKit
DefaultGroupName=F.R.I.D.A.Y.
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\installer-output
OutputBaseFilename=FRIDAY-Setup
SetupIconFile=..\launcher\build\icon.ico
UninstallDisplayIcon={app}\dist-launcher\{#MyAppExeName}
Compression=none
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=2000000000
WizardStyle=modern dynamic
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
MinVersion=10.0.17763
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist-launcher\FRIDAY-HUD.exe"; DestDir: "{app}\dist-launcher"; Flags: ignoreversion
Source: "..\core\*"; DestDir: "{app}\core"; Excludes: "__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\hud\*"; DestDir: "{app}\hud"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\persona\*"; DestDir: "{app}\persona"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\models\*"; DestDir: "{app}\models"; Excludes: ".cache\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.venv\*"; DestDir: "{app}\.venv"; Excludes: "__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\py312\*"; DestDir: "{app}\py312"; Excludes: "__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHECK-AUDIO.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\EXPORT-MEMORY.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\RESET-MEMORY.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\F.R.I.D.A.Y. HUD"; Filename: "{app}\dist-launcher\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\F.R.I.D.A.Y. HUD"; Filename: "{app}\dist-launcher\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autoprograms}\Uninstall F.R.I.D.A.Y."; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\dist-launcher\{#MyAppExeName}"; Description: "Launch F.R.I.D.A.Y. now"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /IM &quot;F.R.I.D.A.Y. HUD.exe&quot; /T /F"; Flags: runhidden; RunOnceId: "StopFridayHud"
Filename: "{cmd}"; Parameters: "/c taskkill /IM python.exe /T /F"; Flags: runhidden; RunOnceId: "StopFridayBackend"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  AppPath: String;
  VenvConfig: String;
begin
  if CurStep = ssPostInstall then
  begin
    AppPath := ExpandConstant('{app}');
    VenvConfig :=
      'home = ' + AppPath + '\py312' + #13#10 +
      'include-system-site-packages = false' + #13#10 +
      'version = 3.12.10' + #13#10 +
      'executable = ' + AppPath + '\py312\python.exe' + #13#10 +
      'command = ' + AppPath + '\py312\python.exe -m venv ' + AppPath + '\.venv' + #13#10;
    SaveStringToFile(AppPath + '\.venv\pyvenv.cfg', VenvConfig, False);

    if not FileExists(AppPath + '\models\Qwen3-4B\config.json') or
       not FileExists(AppPath + '\.venv\Scripts\python.exe') or
       not FileExists(AppPath + '\dist-launcher\{#MyAppExeName}') then
    begin
      MsgBox('Installation verification failed. Please run setup again.', mbError, MB_OK);
    end;
  end;
end;
