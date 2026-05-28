#define AppName "UniversalCrawlerPro"
#define AppVersion "2026.05.27"
#define AppPublisher "UCP"
#define AppExeName "UniversalCrawlerPro.exe"
#define AppIconName "favicon.ico"
#define AppUserModelID "ucp.crawler.v1"
#define DistDir "..\dist\UniversalCrawlerPro"

[Setup]
AppId={{5A1DA9B4-0842-45D5-A4FA-E0E55E8A8C48}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
UsePreviousAppDir=no
DisableProgramGroupPage=no
DisableWelcomePage=no
DisableDirPage=no
AlwaysShowDirOnReadyPage=yes
AllowRootDirectory=no
DirExistsWarning=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=UniversalCrawlerPro_Setup
Compression=lzma2/normal
SolidCompression=no
WizardStyle=modern
SetupIconFile=..\favicon.ico
WizardImageFile=assets\installer_wizard.bmp
WizardSmallImageFile=assets\installer_small.bmp
WizardImageStretch=no
WizardImageBackColor=$00F8FAFC
WizardSmallImageBackColor=$00F8FAFC
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppComments=UniversalCrawlerPro Windows 安装程序
VersionInfoProductName={#AppName} Setup
VersionInfoDescription={#AppName} Windows 安装程序
VersionInfoVersion={#AppVersion}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\{#AppIconName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
