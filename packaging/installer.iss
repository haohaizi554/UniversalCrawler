#define AppName "Universal CrawlerPro"
#define AppVersion "2026.05.27"
#define AppPublisher "UCP"
#define AppExeName "UniversalCrawlerPro.exe"
#define WebUIExeName "CrawlerWebPortal.exe"
#define AppIconName "favicon.ico"
#define WebUIIconName "Web.ico"
#define AppUserModelID "ucp.crawler.v1"
#define WebUIUserModelID "ucp.crawler.webui.v1"
#define DistDir "..\dist\UniversalCrawlerPro"

[Setup]
AppId={{5A1DA9B4-0842-45D5-A4FA-E0E55E8A8C48}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\UniversalCrawlerPro
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
WizardImageFile=wizard_image.bmp
WizardSmallImageFile=wizard_small_image.bmp
WizardImageStretch=yes
WizardImageBackColor=clWhite
WizardSmallImageBackColor=clWhite
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppComments={#AppName} Windows 安装程序
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
Source: "..\{#WebUIIconName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{group}\Crawler WebPortal"; Filename: "{app}\{#WebUIExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#WebUIIconName}"; AppUserModelID: "{#WebUIUserModelID}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{userdesktop}\Crawler WebPortal"; Filename: "{app}\{#WebUIExeName}"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\{#WebUIIconName}"; AppUserModelID: "{#WebUIUserModelID}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
