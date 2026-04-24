[Setup]
AppName=CertGuard Agent
AppVersion=1.0.0
AppId={{E2D4A8D2-9D26-4A0D-9AB2-7E2E8F4B0D17}
DefaultDirName={autopf}\CertGuard Agent
DefaultGroupName=CertGuard
WizardStyle=modern
OutputDir=dist\installer
OutputBaseFilename=Instalador_CertGuard_Agente
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Iniciar automaticamente com o Windows (Tarefa Agendada)"; Flags: unchecked

[Files]
Source: "dist\CertGuard_Agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist
Source: "agent\agent_config.example.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"
Name: "{group}\Desinstalar CertGuard Agent"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CertGuard_Agent.exe"; Description: "Iniciar CertGuard Agent"; Flags: nowait postinstall skipifsilent
Filename: "{cmd}"; Parameters: "/C schtasks /Create /TN ""CertGuard Agent"" /SC ONSTART /RU ""SYSTEM"" /TR """"""{app}\CertGuard_Agent.exe"""""" /F"; Flags: runhidden; Tasks: autostart

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C schtasks /Delete /TN ""CertGuard Agent"" /F"; Flags: runhidden; RunOnceId: "DeleteCertGuardTask"

[Code]
// Permite que o instalador crie arquivos se precisar, ou validar configurações
