; Inno Setup: trình cài đặt ClipVault cho Windows. Build qua packaging\build.ps1 (truyền /DAppVersion=...).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; GUID cố định: giữ nguyên qua các phiên bản để bản mới nâng cấp đè lên bản cũ.
AppId={{6B0F3C52-7E0A-4B8E-9C61-2D5A1F4E7A93}
AppName=ClipVault
AppVersion={#AppVersion}
AppPublisher=ClipVault
; Cài theo từng người dùng: không cần quyền Administrator, không ghi vào Program Files.
PrivilegesRequired=lowest
DefaultDirName={autopf}\ClipVault
DefaultGroupName=ClipVault
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ClipVault-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\ClipVault.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start ClipVault with &Windows (runs in the background)"; Flags: unchecked

[Files]
Source: "..\dist\ClipVault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ClipVault"; Filename: "{app}\ClipVault.exe"
Name: "{group}\Uninstall ClipVault"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ClipVault"; Filename: "{app}\ClipVault.exe"; Tasks: desktopicon

[Registry]
; Chạy cùng Windows ở chế độ nền (--background: không hiện cửa sổ, chỉ có icon ở khay).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ClipVault"; \
  ValueData: """{app}\ClipVault.exe"" --background"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\ClipVault.exe"; Description: "Launch ClipVault"; Flags: nowait postinstall skipifsilent

; Dữ liệu clipboard của người dùng (%LOCALAPPDATA%\ClipVault) KHÔNG nằm trong thư mục cài đặt và KHÔNG bị gỡ khi uninstall.
