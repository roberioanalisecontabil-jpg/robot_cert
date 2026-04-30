; Instalador CertGuard Agent — bandeja + opcional Serviços Windows (CertGuard_Agent_Service.exe / pywin32)
#define ServiceInternalName "CertGuardAgent"

[Setup]
AppName=CertGuard Agent
AppVersion=1.0.1
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
PrivilegesRequired=admin
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Atalho no ambiente de trabalho (modo bandeja)"; GroupDescription: "Atalhos"; Flags: unchecked
Name: "installservice"; Description: "Registar como serviço Windows (recomendado em servidor)"; GroupDescription: "Serviço"; Flags: unchecked
Name: "autostart"; Description: "Ao iniciar sessão: iniciar o agente em bandeja (Tarefa Agendada)"; GroupDescription: "Bandeja"; Flags: unchecked

[Files]
Source: "dist\CertGuard_Agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\CertGuard_Agent_Service.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist
Source: "agent\agent_config.example.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"
Name: "{group}\Desinstalar CertGuard Agent"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CertGuard_Agent.exe"; Description: "Iniciar o agente em bandeja agora"; Flags: nowait postinstall skipifsilent unchecked; Check: OfferTrayAfterInstall
Filename: "{sys}\sc.exe"; Parameters: "start {#ServiceInternalName}"; Flags: runhidden waituntilterminated; StatusMsg: "A iniciar o serviço..."; Check: WizardIsTaskSelected('installservice')

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C schtasks /Delete /TN ""CertGuard Agent"" /F"; Flags: runhidden
Filename: "{sys}\sc.exe"; Parameters: "stop {#ServiceInternalName}"; Flags: runhidden waituntilterminated; Check: ServiceIsPresent
Filename: "{sys}\sc.exe"; Parameters: "delete {#ServiceInternalName}"; Flags: runhidden waituntilterminated; Check: ServiceIsPresent

[Code]
function OfferTrayAfterInstall: Boolean;
begin
  Result := (not WizardIsTaskSelected('installservice')) and (not WizardSilent);
end;

function ServiceIsPresent: Boolean;
var RC: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query {#ServiceInternalName}', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RC) and (RC = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var RC: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('autostart') and (not WizardIsTaskSelected('installservice')) then
    begin
      Exec(ExpandConstant('{cmd}'), '/C schtasks /Create /TN ""CertGuard Agent"" /SC ONLOGON /TR "' + ExpandConstant('{app}\CertGuard_Agent.exe') + '" /F',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RC);
    end;

    if WizardIsTaskSelected('installservice') then
    begin
      Exec(ExpandConstant('{sys}\sc.exe'),
        'create {#ServiceInternalName} binPath= "' + ExpandConstant('{app}\CertGuard_Agent_Service.exe') + '" start= auto DisplayName= "CertGuard Agent"',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RC);
      Exec(ExpandConstant('{sys}\sc.exe'), 'failure {#ServiceInternalName} reset= 86400 actions= restart/60000/restart/60000/restart/60000', '', SW_HIDE, ewWaitUntilTerminated, RC);
      Exec(ExpandConstant('{sys}\sc.exe'), ExpandConstant('description {#ServiceInternalName} "Inventário de certificados PFX e envio ao portal CertGuard."'), ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RC);
    end;
  end;
end;
