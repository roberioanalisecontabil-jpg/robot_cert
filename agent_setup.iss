; Instalador CertGuard Agent — CertGuard_Agent.exe (bandeja / tarefa agendada)

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
Name: "desktopicon"; Description: "Atalho no ambiente de trabalho"; GroupDescription: "Atalhos"; Flags: unchecked
Name: "autostart"; Description: "Ao iniciar sessao: iniciar icone na bandeja (Tarefa Agendada)"; GroupDescription: "Bandeja"

[Files]
; Executável da bandeja (one-file)
Source: "dist\CertGuard_Agent.exe"; DestDir: "{app}"; Flags: ignoreversion
; Executável do serviço (one-dir) + todas as DLLs em _internal
Source: "dist\CertGuard_Agent_Service\CertGuard_Agent_Service.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\CertGuard_Agent_Service\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; Config: agent_config.json é a config primária (NÃO copiamos .env.example para
; evitar sobrescrever URL do portal com localhost)
Source: "agent\agent_config.example.json"; DestDir: "{app}"; DestName: "agent_config.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"
Name: "{group}\Desinstalar CertGuard Agent"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CertGuard Agent"; Filename: "{app}\CertGuard_Agent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CertGuard_Agent.exe"; Parameters: "--tray-only"; Description: "Iniciar o agente em bandeja agora"; Flags: nowait postinstall skipifsilent unchecked; Check: OfferTrayAfterInstall

[Code]
const
  TrayTaskName = 'CertGuard Agent (Tray)';
  ServiceName = 'CertGuardAgent';

var
  LastOperationError: string;

function OfferTrayAfterInstall: Boolean;
begin
  Result := not WizardSilent;
end;

function StopRunningAgent: Boolean;
var
  RC: Integer;
  Cmd: string;
begin
  LastOperationError := '';
  Cmd := '/C taskkill /F /IM "CertGuard_Agent.exe"';
  Log('Encerrando processo em execucao (se existir): ' + Cmd);

  if Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    Log('taskkill retornou codigo: ' + IntToStr(RC));
    { 0 = encerrado com sucesso, 128 = processo nao encontrado }
    Result := (RC = 0) or (RC = 128);
    if not Result then
    begin
      LastOperationError :=
        'taskkill retornou codigo ' + IntToStr(RC) + '.' + #13#10 +
        'Provavel causa: permissao insuficiente ou processo protegido.' + #13#10 +
        'Acao recomendada: execute como Administrador e feche o processo manualmente no Gerenciador de Tarefas.';
    end;
  end
  else
  begin
    Log('Falha ao executar taskkill.');
    Result := False;
    LastOperationError :=
      'Falha ao iniciar taskkill via cmd.exe.' + #13#10 +
      'Provavel causa: cmd indisponivel ou politica de sistema bloqueando execucao.' + #13#10 +
      'Acao recomendada: valide o ambiente Windows e tente novamente com privilegios de Administrador.';
  end;
end;

function StopServiceIfRunning: Boolean;
var
  RC: Integer;
  Cmd: string;
begin
  LastOperationError := '';
  Result := False;

  Cmd := '/C sc stop "' + ServiceName + '"';
  Log('Parando servico (se ativo): ' + Cmd);

  if Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    Log('sc stop retornou codigo: ' + IntToStr(RC));
    Result := (RC = 0) or (RC = 1060) or (RC = 1062);
  end
  else
  begin
    Log('Falha ao executar sc stop.');
    LastOperationError := 'Falha ao parar o servico antes de atualizar/remover.';
  end;
end;

function RemoveService: Boolean;
var
  RC: Integer;
  Cmd: string;
begin
  LastOperationError := '';
  Result := False;
  Cmd := '/C sc delete "' + ServiceName + '"';
  Log('Removendo servico (se existir): ' + Cmd);
  if Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    Log('sc delete retornou codigo: ' + IntToStr(RC));
    Result := (RC = 0) or (RC = 1060);
  end
  else
  begin
    Log('Falha ao executar sc delete.');
    LastOperationError := 'Falha ao remover servico.';
  end;
end;

function InstallOrUpdateService: Boolean;
var
  RC: Integer;
  Cmd: string;
  CreatedNow: Boolean;
  SvcExePath: string;
begin
  LastOperationError := '';
  Result := False;
  CreatedNow := False;

  { Verificar que o executavel do servico existe ANTES de registrar }
  SvcExePath := ExpandConstant('{app}\CertGuard_Agent_Service.exe');
  if not FileExists(SvcExePath) then
  begin
    LastOperationError :=
      'O executavel do servico nao foi encontrado:' + #13#10 +
      SvcExePath + #13#10 +
      'A build do PyInstaller pode nao ter sido executada antes de compilar o instalador.' + #13#10 +
      'Acao recomendada: execute "pyinstaller CertGuard_Service.spec --clean" e recompile o instalador.';
    Exit;
  end;
  Log('Executavel do servico encontrado: ' + SvcExePath);

  if not StopServiceIfRunning then
  begin
    Exit;
  end;

  if not RemoveService then
  begin
    Exit;
  end;

  Cmd :=
    '/C sc create "' + ServiceName + '" ' +
    'binPath= "\"' + SvcExePath + '\"" ' +
    'start= auto DisplayName= "CertGuard Agent Service"';
  Log('Criando servico: ' + Cmd);
  if not Exec(ExpandConstant('{cmd}'), Cmd, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    LastOperationError := 'Falha ao executar sc create.';
    Exit;
  end;
  Log('sc create retornou codigo: ' + IntToStr(RC));
  if RC = 0 then
  begin
    CreatedNow := True;
  end
  else if RC <> 1073 then
  begin
    LastOperationError :=
      'sc create retornou codigo ' + IntToStr(RC) + '.' + #13#10 +
      'Acao recomendada: execute como Administrador e verifique politicas locais de servico.';
    Exit;
  end;

  if CreatedNow then
  begin
    Cmd :=
      '/C sc config "' + ServiceName + '" ' +
      'binPath= "\"' + SvcExePath + '\"" ' +
      'start= auto obj= LocalSystem';
  end
  else
  begin
    Cmd :=
      '/C sc config "' + ServiceName + '" ' +
      'binPath= "\"' + SvcExePath + '\"" ' +
      'start= auto';
  end;
  Log('Configurando servico (auto/localSystem): ' + Cmd);
  if not Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    LastOperationError := 'Falha ao executar sc config.';
    Exit;
  end;
  Log('sc config retornou codigo: ' + IntToStr(RC));
  if RC <> 0 then
  begin
    LastOperationError :=
      'sc config retornou codigo ' + IntToStr(RC) + '.' + #13#10 +
      'Acao recomendada: revise permissao administrativa e politicas de servico.';
    Exit;
  end;

  Cmd := '/C sc description "' + ServiceName + '" "Servico CertGuard com operacoes administrativas em background."';
  Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC);

  Cmd := '/C sc start "' + ServiceName + '"';
  Log('Iniciando servico: ' + Cmd);
  if not Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    Log('Falha ao executar sc start; mantendo instalacao e seguindo.');
    LastOperationError :=
      'Servico instalado, mas falhou ao iniciar automaticamente nesta etapa.' + #13#10 +
      'Acao recomendada: abra o Services.msc e inicie o servico manualmente para diagnostico.';
    Result := True;
    Exit;
  end;
  Log('sc start retornou codigo: ' + IntToStr(RC));
  if (RC <> 0) and (RC <> 1056) then
  begin
    Log('sc start retornou erro nao fatal (' + IntToStr(RC) + '); mantendo instalacao e seguindo.');
    LastOperationError :=
      'Servico instalado, mas nao iniciou automaticamente (codigo ' + IntToStr(RC) + ').' + #13#10 +
      'Acao recomendada: verificar Event Viewer e iniciar manualmente em Services.msc.';
    Result := True;
    Exit;
  end;

  if CreatedNow then
    Log('Servico criado e iniciado com sucesso.')
  else
    Log('Servico existente reconfigurado para AUTO_START e iniciado com sucesso.');

  Result := True;
end;

function CreateTrayAutostartTask: Boolean;
var
  RC: Integer;
  Cmd: string;
begin
  LastOperationError := '';
  Result := False;

  Cmd :=
    '/C schtasks /Create ' +
    '/TN "' + TrayTaskName + '" ' +
    '/SC ONLOGON ' +
    '/RU "' + ExpandConstant('{username}') + '" ' +
    '/TR "\"' + ExpandConstant('{app}\CertGuard_Agent.exe') + '\" --tray-only" ' +
    '/RL HIGHEST /F';
  Log('Criando tarefa agendada de bandeja: ' + Cmd);

  if Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    Log('schtasks /Create retornou codigo: ' + IntToStr(RC));
    Result := (RC = 0);
    if not Result then
    begin
      LastOperationError :=
        'schtasks /Create retornou codigo ' + IntToStr(RC) + '.' + #13#10 +
        'Provavel causa: permissao insuficiente ou politica bloqueando tarefa no logon.' + #13#10 +
        'Acao recomendada: execute o instalador como Administrador.';
    end;
  end
  else
  begin
    Log('Falha ao executar schtasks para criar tarefa agendada.');
    LastOperationError :=
      'Falha ao iniciar schtasks para criacao da tarefa de bandeja.' + #13#10 +
      'Acao recomendada: valide cmd/schtasks e tente novamente.';
  end;
end;

function DeleteTrayAutostartTask: Boolean;
var
  RC: Integer;
  Cmd: string;
begin
  LastOperationError := '';
  Result := False;
  Cmd := '/C schtasks /Delete /TN "' + TrayTaskName + '" /F';
  Log('Removendo tarefa agendada de bandeja: ' + Cmd);
  if Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, RC) then
  begin
    Log('schtasks /Delete retornou codigo: ' + IntToStr(RC));
    Result := (RC = 0) or (RC = 1);
    if not Result then
      LastOperationError := 'schtasks /Delete retornou codigo ' + IntToStr(RC) + '.';
  end
  else
  begin
    LastOperationError := 'Falha ao executar schtasks /Delete.';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if not StopRunningAgent then
    begin
      MsgBox(
        'Nao foi possivel encerrar o CertGuard Agent antes da instalacao.' + #13#10 +
        LastOperationError,
        mbError, MB_OK
      );
      Abort;
    end;
  end;

  if CurStep = ssPostInstall then
  begin
    if not InstallOrUpdateService then
    begin
      MsgBox(
        'Nao foi possivel instalar/iniciar o servico "' + ServiceName + '".' + #13#10 +
        LastOperationError,
        mbError, MB_OK
      );
      Abort;
    end;
    if LastOperationError <> '' then
    begin
      MsgBox(
        LastOperationError,
        mbInformation, MB_OK
      );
    end;

    if WizardIsTaskSelected('autostart') then
    begin
      if not CreateTrayAutostartTask then
      begin
        MsgBox(
          'Nao foi possivel criar a tarefa agendada "' + TrayTaskName + '".' + #13#10 +
          LastOperationError,
          mbError, MB_OK
        );
      end;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if not StopRunningAgent then
    begin
      MsgBox(
        'Nao foi possivel encerrar o CertGuard Agent antes da desinstalacao.' + #13#10 +
        LastOperationError,
        mbError, MB_OK
      );
      Abort;
    end;

    StopServiceIfRunning;
    if not RemoveService then
    begin
      MsgBox(
        'Nao foi possivel remover o servico "' + ServiceName + '".' + #13#10 +
        LastOperationError,
        mbError, MB_OK
      );
      Abort;
    end;
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    if not DeleteTrayAutostartTask then
    begin
      MsgBox(
        'A desinstalacao foi concluida, mas a tarefa agendada "' + TrayTaskName + '" nao foi removida.' + #13#10 +
        LastOperationError,
        mbError, MB_OK
      );
    end;
  end;
end;
