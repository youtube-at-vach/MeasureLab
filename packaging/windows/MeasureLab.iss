; Build with scripts/build_windows_installer.ps1 and Inno Setup 6.3+ (6.x).
#if Ver < EncodeVer(6, 3, 0) || Ver >= EncodeVer(7, 0, 0)
  #error Inno Setup 6.3+ (6.x) is required
#endif
#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif
#ifndef AppFileVersion
  #error AppFileVersion must be supplied by the build script
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by the build script
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by the build script
#endif

[Setup]
; Stable Rust-edition ID, deliberately separate from Python's installation.
AppId={{97AA1A5C-BB05-4DC8-A791-1259F0622CE5}
AppName=MeasureLab
AppVerName=MeasureLab {#AppVersion} (Rust)
AppVersion={#AppVersion}
VersionInfoVersion={#AppFileVersion}
AppPublisher=MeasureLab maintainers
AppPublisherURL=https://github.com/youtube-at-vach/MeasureLab
AppSupportURL=https://github.com/youtube-at-vach/MeasureLab/issues
AppUpdatesURL=https://github.com/youtube-at-vach/MeasureLab/releases
DefaultDirName={localappdata}\Programs\MeasureLab Rust
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
UninstallDisplayName=MeasureLab (Rust)
UninstallDisplayIcon={app}\measurelab.exe
SetupIconFile=app_icon.ico
LicenseFile=..\..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=MeasureLab-v{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UsePreviousTasks=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\measurelab.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\build-info.json"; DestDir: "{app}"; Flags: ignoreversion

; Never recursively delete the application directory or user measurement data.
[Icons]
Name: "{userprograms}\MeasureLab (Rust)"; Filename: "{app}\measurelab.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\MeasureLab (Rust)"; Filename: "{app}\measurelab.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\measurelab.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,MeasureLab}"; Flags: nowait postinstall skipifsilent unchecked
