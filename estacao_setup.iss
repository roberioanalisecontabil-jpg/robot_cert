; Certguard Analise -- instalador do agente de certificados das estacoes.
; ADR 0003, adendo de 14/10/2026: 1.0 sem servico; este instalador (admin)
; prepara a chave da maquina chamando o exe com --preparar-chave.
; Gravado em UTF-8 COM BOM: sem ele o ISCC le como ANSI e o "a" acentuado do
; nome vira lixo na tela. Mantenha o BOM ao editar.
#define MyAppName "Certguard Análise"
#define MyInternalName "Certguard Analise"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Analise Group"
#define MyAppURL "https://certificado.analisegroup.cnt.br/"
#define MyAppExeName "certguard_analise.exe"

[Setup]
; GUID proprio: nao e o do Hardlyze nem o do agente do servidor.
AppId={{6C1B7E52-3F0A-4D8B-9E21-5A7C4F2D8B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyInternalName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=admin
OutputDir=dist_estacao
OutputBaseFilename=Instalador_CertguardAnalise_{#MyAppVersion}
SetupIconFile=ico\icone.ico
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
; Sem skipifsilent de proposito: na instalacao silenciosa tambem abre.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall runasoriginaluser; Description: "Abrir o {#MyAppName}"

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
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // A chave em ProgramData fica: reinstalar mantem o vinculo ja aprovado.
  if CurUninstallStep = usUninstall then
    FecharBandejas;
end;
