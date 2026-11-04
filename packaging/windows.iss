#ifndef AppVersion
  #define AppVersion "0.10.0"
#endif
[Setup]
AppId={{54C25A23-44CD-4AB2-8492-FC794F2F7783}
AppName=Soovee Commander
AppVersion={#AppVersion}
AppPublisher=Soovee
DefaultDirName={localappdata}\Programs\SooveeCommander
DefaultGroupName=Soovee Commander
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SourceDir=..
OutputDir=dist
OutputBaseFilename=SooveeCommander-{#AppVersion}-windows-x86_64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=packaging\SooveeCommander.ico
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=yes
AppMutex=SooveeCommander,StereoCommander
SetupMutex=SooveeCommanderSetup
UninstallDisplayIcon={app}\SooveeCommander.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\SooveeCommander\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\StereoCommander.exe"
Type: filesandordirs; Name: "{app}\_internal\stereo_commander"

[Icons]
Name: "{group}\Soovee Commander"; Filename: "{app}\SooveeCommander.exe"
Name: "{autodesktop}\Soovee Commander"; Filename: "{app}\SooveeCommander.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SooveeCommander.exe"; Description: "Start Soovee Commander"; Flags: nowait postinstall skipifsilent
Filename: "{app}\SooveeCommander.exe"; Flags: nowait; Check: IsSilentInstall

[Code]
function IsSilentInstall: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:NOLAUNCH|0}') <> '1');
end;
