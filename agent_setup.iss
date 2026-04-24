[Setup]
AppName=CertGuard Agent
AppVersion=1.0.0
DefaultDirName={autopf}\CertGuard Agent
DefaultGroupName=CertGuard
OutputDir=dist
OutputBaseFilename=Instalador_CertGuard_Agente
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\CertGuard_Agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; DestName: ".env"; Flags: ignoreversion

[Icons]
Name: "{group}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"
Name: "{group}\Desinstalar CertGuard Agent"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CertGuard_Agent.exe"; Description: "Iniciar CertGuard Agent"; Flags: nowait postinstall skipifsilent

[Code]
// Permite que o instalador crie arquivos se precisar, ou validar configurações
