#ifndef AppName
  #define AppName "Universal Crawler Pro"
#endif
#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.py
#endif
#ifndef AppPublisher
  #define AppPublisher "UCrawl Team"
#endif
#ifndef AppComments
  #define AppComments "Universal Crawler Pro Windows 安装程序"
#endif
#ifndef AppExeName
  #define AppExeName "UniversalCrawlerPro.exe"
#endif
#ifndef LauncherExeName
  #define LauncherExeName "UCrawlLauncher.exe"
#endif
#ifndef LauncherDisplayName
  #define LauncherDisplayName "Universal Crawler Pro 启动中心"
#endif
#ifndef CLILauncherExeName
  #define CLILauncherExeName "UCrawlCLI.exe"
#endif
#ifndef CLILauncherDisplayName
  #define CLILauncherDisplayName "Universal Crawler Pro 命令行"
#endif
#ifndef WebUIExeName
  #define WebUIExeName "CrawlerWebPortal.exe"
#endif
#ifndef WebUIDisplayName
  #define WebUIDisplayName "Crawler Web Portal"
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
#ifndef InstallDirName
  #define InstallDirName "UniversalCrawlerPro"
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
DefaultDirName={localappdata}\Programs\{#InstallDirName}
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
SetupIconFile=..\{#AppIconName}
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
ChangesAssociations=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "associatevideo"; Description: "视频文件默认使用 {#AppName} 打开（mp4、mkv、avi、mov、webm 等）"; GroupDescription: "文件关联（可选）:"
Name: "associateimage"; Description: "图片文件默认使用 {#AppName} 打开（jpg、png、gif、webp、bmp 等）"; GroupDescription: "文件关联（可选）:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\{#AppIconName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\{#WebUIIconName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#LauncherDisplayName}"; Filename: "{app}\{#LauncherExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{group}\{#CLILauncherDisplayName}"; Filename: "{app}\{#CLILauncherExeName}"; Parameters: "--mode interactive"; WorkingDir: "{app}"; IconFilename: "{app}\{#CLILauncherExeName}"
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{group}\{#WebUIDisplayName}"; Filename: "{app}\{#WebUIExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#WebUIIconName}"; AppUserModelID: "{#WebUIUserModelID}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{userdesktop}\{#WebUIDisplayName}"; Filename: "{app}\{#WebUIExeName}"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\{#WebUIIconName}"; AppUserModelID: "{#WebUIUserModelID}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\UniversalCrawlerPro\Capabilities"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\UniversalCrawlerPro\Capabilities"; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Tasks: associatevideo; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Tasks: associateimage; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Use {#AppName} to preview supported local videos and images."; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Use {#AppName} to preview supported local videos and images."; Tasks: associateimage
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Tasks: associatevideo; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Tasks: associateimage; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associatevideo
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associateimage
Root: HKCU; Subkey: "Software\Classes\UniversalCrawlerPro.Video"; ValueType: string; ValueName: ""; ValueData: "{#AppName} Video"; Tasks: associatevideo; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\UniversalCrawlerPro.Video\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\Classes\UniversalCrawlerPro.Video\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associatevideo
Root: HKCU; Subkey: "Software\Classes\.mp4"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.avi"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mkv"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mov"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.flv"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.wmv"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.m4v"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.webm"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.m3u8"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.ts"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.avi\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mkv\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mov\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.flv\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.wmv\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.m4v\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.webm\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.m3u8\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.ts\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Video"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mp4"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".avi"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mkv"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mov"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".flv"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".wmv"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".m4v"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".webm"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".m3u8"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".ts"; ValueData: ""; Tasks: associatevideo; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp4"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".avi"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mkv"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mov"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".flv"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wmv"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m4v"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".webm"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m3u8"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ts"; ValueData: "UniversalCrawlerPro.Video"; Tasks: associatevideo
Root: HKCU; Subkey: "Software\Classes\UniversalCrawlerPro.Image"; ValueType: string; ValueName: ""; ValueData: "{#AppName} Image"; Tasks: associateimage; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\UniversalCrawlerPro.Image\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Tasks: associateimage
Root: HKCU; Subkey: "Software\Classes\UniversalCrawlerPro.Image\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associateimage
Root: HKCU; Subkey: "Software\Classes\.jpg"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.jpeg"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.png"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.gif"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.webp"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.bmp"; ValueType: string; ValueName: ""; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.jpg\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Image"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.jpeg\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Image"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.png\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Image"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.gif\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Image"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.webp\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Image"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.bmp\OpenWithProgids"; ValueType: string; ValueName: "UniversalCrawlerPro.Image"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".jpg"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".jpeg"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".png"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".gif"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".webp"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".bmp"; ValueData: ""; Tasks: associateimage; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpg"; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".jpeg"; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".png"; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".gif"; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".webp"; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage
Root: HKCU; Subkey: "Software\UniversalCrawlerPro\Capabilities\FileAssociations"; ValueType: string; ValueName: ".bmp"; ValueData: "UniversalCrawlerPro.Image"; Tasks: associateimage
[Code]
function ShouldOpenAssociationSettings(): Boolean;
begin
  Result := WizardIsTaskSelected('associatevideo') or WizardIsTaskSelected('associateimage');
end;

function GetAssociationKinds(Param: String): String;
begin
  Result := '';
  if WizardIsTaskSelected('associatevideo') then
    Result := Result + ' video';
  if WizardIsTaskSelected('associateimage') then
    Result := Result + ' image';
end;

[Run]
Filename: "{app}\{#AppExeName}"; Parameters: "--app-name ""{#AppName}"" --register-file-associations{code:GetAssociationKinds} --set-default-file-associations"; StatusMsg: "正在配置默认打开方式..."; Flags: waituntilterminated runhidden skipifsilent; Check: ShouldOpenAssociationSettings
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent unchecked
