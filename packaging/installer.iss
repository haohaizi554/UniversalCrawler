#ifndef AppName
  #define AppName "Universal CrawlerPro"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "UCrawl Team"
#endif
#ifndef AppComments
  #define AppComments "Universal CrawlerPro Windows 安装程序"
#endif
#ifndef AppExeName
  #define AppExeName "UniversalCrawlerPro.exe"
#endif
#ifndef WebUIExeName
  #define WebUIExeName "CrawlerWebPortal.exe"
#endif
#ifndef AppIconName
  #define AppIconName "favicon.ico"
#endif
#ifndef WebUIIconName
  #define WebUIIconName "Web.ico"
#endif
#ifndef AppUserModelID
  #define AppUserModelID "ucrawl.universalcrawlerpro.main"
#endif
#ifndef WebUIUserModelID
  #define WebUIUserModelID "ucrawl.universalcrawlerpro.web"
#endif
#ifndef DistDir
  #define DistDir "..\dist\UniversalCrawlerPro"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "UniversalCrawlerPro_Setup"
#endif

[Setup]
AppId={{5A1DA9B4-0842-45D5-A4FA-E0E55E8A8C48}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\UniversalCrawlerPro
DefaultGroupName={#AppName}
UsePreviousAppDir=yes
DisableProgramGroupPage=no
DisableWelcomePage=no
DisableDirPage=no
AlwaysShowDirOnReadyPage=yes
AllowRootDirectory=no
DirExistsWarning=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename={#OutputBaseFilename}
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
AppComments={#AppComments}
VersionInfoProductName={#AppName} Setup
VersionInfoDescription={#AppComments}
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
