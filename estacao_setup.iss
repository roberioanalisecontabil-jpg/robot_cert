; Certguard Analise -- instalador do agente de certificados das estacoes.
; ADR 0003, adendo de 14/10/2026: 1.0 sem servico; este instalador (admin)
; prepara a chave da maquina chamando o exe com --preparar-chave.
; 1.1.0 (20/10/2026): atualizacao automatica. O instalador tranca a pasta de
; atualizacao, guarda a si mesmo como instalado.exe (a volta automatica da
; proxima versao usa essa copia) e cria as tarefas agendadas SYSTEM que
; conferem a versao publicada no portal (estacao/tarefa.py).
; Gravado em UTF-8 COM BOM: sem ele o ISCC le como ANSI e o "a" acentuado do
; nome vira lixo na tela. Mantenha o BOM ao editar.
#define MyAppName "CertGuard Análise"
#define MyInternalName "Certguard Analise"
#define MyAppVersion "1.1.1"
#define MyAppPublisher "Analise Group"
#define MyAppURL "https://certificado.analisegroup.cnt.br/"
#define MyAppExeName "certguard_analise.exe"
; Mesmo nome de estacao/tarefa.py (NOME_TAREFA); a segunda leva " 6h".
#define NomeTarefa "Certguard Analise - atualizacao"

[Setup]
; GUID proprio: nao e o do Hardlyze nem o do agente do servidor.
AppId={{6C1B7E52-3F0A-4D8B-9E21-5A7C4F2D8B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; Sem isto o recurso de versao do .exe diz 0.0.0.0.
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyInternalName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=admin
OutputDir=dist_estacao
OutputBaseFilename=Instalador_CertguardAnalise_{#MyAppVersion}
SetupIconFile=ico\certguard.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "dist_estacao\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{commonappdata}\CertguardAnalise"

[Registry]
; A bandeja sobe no logon de qualquer pessoa da estacao.
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyInternalName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
; Abre a bandeja como a pessoa que rodou o instalador (nao como o admin
; elevado): e no perfil dela que a conta fica e o certificado entra.
; skipifsilent desde a 1.1.0: em silencio quem instala e a atualizacao
; automatica, como SYSTEM, e a bandeja abriria na sessao invisivel dele. Quem
; reabre a bandeja nas sessoes e a tarefa da versao nova (estacao/sessoes.py);
; sem atualizacao, ela sobe no proximo logon pela chave Run.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall runasoriginaluser skipifsilent; Description: "Abrir o {#MyAppName}"

[Code]
procedure FecharBandejas;
var
  ResultCode: Integer;
begin
  // Toda bandeja aberta, de qualquer sessao: o exe em uso nao seria substituido.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  FecharBandejas;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // Copia a chave da maquina do Hardlyze (e apaga a original) ou gera uma.
    if not Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--preparar-chave', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      SuppressibleMsgBox('Nao foi possivel preparar a chave desta maquina. A bandeja funciona, mas o computador vai pedir autorizacao ao administrador. Detalhes em ' +
        ExpandConstant('{commonappdata}\CertguardAnalise\logs\instalacao.log'), mbError, MB_OK, IDOK);
    // Pasta trancada, copia deste instalador para voltar atras e as tarefas.
    if not Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--preparar-atualizacao "' + ExpandConstant('{srcexe}') + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      SuppressibleMsgBox('Nao foi possivel preparar a atualizacao automatica. A bandeja funciona, mas esta maquina nao vai se atualizar sozinha. Detalhes em ' +
        ExpandConstant('{commonappdata}\CertguardAnalise\logs\instalacao.log'), mbError, MB_OK, IDOK);
    // Roda a tarefa agora: numa atualizacao, e ela que confirma a versao nova
    // para o atualizador que esta esperando.
    Exec(ExpandConstant('{sys}\schtasks.exe'), '/Run /TN "{#NomeTarefa}"', '', SW_HIDE, ewNoWait, ResultCode);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  // A chave em ProgramData fica: reinstalar mantem o vinculo ja aprovado.
  if CurUninstallStep = usUninstall then
  begin
    FecharBandejas;
    Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /F /TN "{#NomeTarefa}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /F /TN "{#NomeTarefa} 6h"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
