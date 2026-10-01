# robot_cert — Portal de Certificados Digitais

Portal da Análise Group que inventaria os certificados digitais dos clientes guardados no servidor, mostra validade e histórico, e instala o certificado certo na estação da pessoa certa. O vocabulário abaixo é o de negócio; o identificador do código aparece entre parênteses só quando diverge do termo.

## Pessoas e papéis

**Usuário**:
Qualquer pessoa com login no portal, de qualquer papel.
_Avoid_: usar "usuário" para designar o Operador

**Papel** (`role`):
O nível de acesso de um Usuário. Há três: Administrador, Gestor e Operador.
_Avoid_: nível, perfil, tipo de usuário

**Administrador** (`admin`):
Papel com alcance total: vê e instala qualquer Certificado, edita qualquer Carteira e configura o portal. É o único Papel escolhido à mão; os outros dois derivam da liderança de Departamento.

**Gestor** (`gestor`):
Papel de quem lidera um ou mais Departamentos. O Papel deriva da liderança: nomear alguém Gestor de um Departamento o torna Gestor, e perder a última liderança o rebaixa a Operador. Alcança todos os Documentos do Inventário, menos as Exceções registradas pelo Administrador. Um Administrador pode liderar um Departamento sem deixar de ser Administrador.
_Avoid_: líder, gerente, chefe

**Operador** (`user`):
Papel de quem é liderado. Alcança apenas os Documentos atribuídos à sua Carteira e nasce com ela vazia. Nunca edita a Carteira de outra pessoa.
_Avoid_: usuário, liderado, colaborador

**Departamento** (`departamento`):
Agrupamento de Usuários pela área da empresa (Fiscal, Contábil, Pessoal...). Todo Usuário pertence a exatamente um Departamento, obrigatório desde a criação. Um Departamento pode ter vários Gestores, e um Gestor pode liderar vários Departamentos.
_Avoid_: setor, grupo

## Certificados e alcance

**Certificado**:
Um arquivo de certificado digital (PFX) de um cliente, identificado pela impressão digital e ligado a um Documento. Um Documento tem vários Certificados ao longo do tempo (renovações).

**Documento** (`documento`):
O CNPJ ou CPF do titular do Certificado, só dígitos. É a chave pela qual o Cliente existe no portal; não há cadastro de cliente. Atribuições e Exceções são sobre Documentos do Inventário.
_Avoid_: cliente, empresa (quando se refere à chave)

**Cliente**:
O titular de um Documento, como as telas o nomeiam: nome e CNPJ/CPF. Quem opera pensa em cliente; a regra de negócio trabalha com o Documento.
_Avoid_: empresa, titular (nas telas)

**Inventário** (`cert_snapshots`):
A última foto dos Certificados encontrados na pasta do servidor. É o universo sobre o qual as Carteiras atuam.
_Avoid_: snapshot, pasta

**Carteira** (`carteira`):
O conjunto de Documentos que um Usuário alcança. Todo Usuário tem uma Carteira ao ser criado, e o comportamento dela depende do Papel: a do Operador é feita de Atribuições (começa vazia, só alcança o que recebeu); a do Gestor é feita de Exceções (começa cheia, alcança todo o Inventário menos o que lhe foi retirado). A Carteira nunca guarda estado dormente: mudar de Papel ou Desativar a esvazia.

**Atribuição** (`atribuido_por`):
Um Documento posto na Carteira de um Operador pelo Gestor do seu Departamento ou pelo Administrador. O Gestor só atribui Documentos que estão no próprio Alcance. Verbos nas telas: atribuir, retirar.
_Avoid_: inclusão, liberação, liberar

**Exceção**:
Um Documento retirado da Carteira de um Gestor pelo Administrador. Só o Administrador registra Exceções; um Gestor não limita outro. Verbos nas telas: retirar (registra), devolver (remove).
_Avoid_: restrição, bloqueio, acesso restrito

**Estação** (`machine_id` da pessoa):
A máquina em que a pessoa está com o Hardlyze Agent vivo, onde o Certificado é instalado. Cada pessoa tem uma Estação: a atual. Se trocar de máquina, a nova passa a ser a padrão. Não confundir com o servidor da varredura, dono do Inventário e do Cofre.
_Avoid_: máquina, computador, dispositivo (quando se refere ao destino da instalação)

**Alcance**:
Os Certificados que um Usuário pode ver e instalar. Ver e instalar são um único direito: quem vê, instala.
_Avoid_: permissão de certificado, acesso (ambíguo com o acesso às páginas)

**Desativar**:
Tirar o login de um Usuário sem apagá-lo. Desativar esvazia a Carteira; a reativação começa do zero.
_Avoid_: bloquear, excluir

## Páginas

**Módulo** (`modulo`):
Uma página ou área do portal (Início, Dashboard, Histórico, Carteiras...). O que cada Papel pode fazer em cada Módulo é a Matriz de Permissões, independente do Alcance sobre Certificados.

**Matriz de Permissões** (`permissoes`):
Tabela Papel × Módulo com o nível nenhum, ler ou editar. Só o Administrador a altera.
