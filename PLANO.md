# Plano: Esteira (codinome)

Versão de 15/11/2026. Este documento registra as decisões já tomadas e o caminho de construção. As decisões da seção 3 estão fechadas; o que ainda depende de confirmação está nas seções 10 e 11.

## 1. O produto em uma página

**O que é.** Uma plataforma em que a pessoa conecta o GitHub ou GitLab e a própria conta Claude, monta "menus" de automação a partir de módulos prontos (QA, UX, Design e outros) e esses menus passam a rodar como etapas da esteira de CI dela. Tudo o que a automação faz aparece ao vivo num escritório em pixel art, em vez de linhas de log.

**Para quem.** Startups, pessoas com uma ideia e empresas grandes que queiram automatizar uma parte da esteira, por exemplo só o QA.

**Como começa.** A primeira versão tem um único cliente: o dono do produto, usando a própria assinatura Claude. O produto é gratuito. O sistema já nasce preparado para várias contas, mas a entrada de outras pessoas fica fechada até a Anthropic confirmar por escrito que o uso é permitido (seção 9).

**O que a pessoa faz, em ordem:**
1. Conecta Claude, GitHub e GitLab na tela "Conexões".
2. Escolhe módulos no catálogo e escreve o que quer, criando um menu (exemplo: módulo QA + "teste toda a funcionalidade").
3. Decide onde o menu roda: manual, num projeto ou em todos.
4. Acompanha a execução ao vivo no escritório e aprova ou reprova quando for chamada.

## 2. Vocabulário

| Termo | Significado |
|---|---|
| **Skill** | A peça atômica: uma pasta com instruções (`SKILL.md`). |
| **Módulo** | Pacote de skills publicado no catálogo, com instruções base e prompts de exemplo. |
| **Menu** | O que o cliente monta: um ou mais módulos, um prompt e um nome. Cada menu vira uma etapa na pipeline. |
| **Esteira** | Sequência ordenada de menus, pensada para um papel (Dev, Tech Lead) e ligada a um ou mais repositórios. |
| **Orquestrador** | O aplicativo de desktop que faz as execuções rodarem no computador do cliente. |
| **Executor** | A imagem com o Claude Code oficial, o navegador e o nosso programa, que roda dentro do job de CI. |

**Modos de um menu:**
- **Manual**: roda só quando alguém dispara pelo painel.
- **Por projeto**: etapa automática nos projetos escolhidos.
- **Global**: etapa automática em todos os projetos conectados da conta.

**Tipos de módulo:**
- **De esteira**: roda na CI.
- **Avulso**: tem a ver com o projeto, mas não faz parte da esteira de desenvolvimento (exemplo: Ads).

## 3. Decisões fechadas

### 3.1 Contas, acesso e idioma

- Cada conta é uma organização, com três papéis: **Admin** (conecta provedores e cria menus), **Membro** (dispara e acompanha) e **Leitor** (acompanha e aprova ou reprova).
- **Criador de módulos** é uma permissão à parte, concedida pelo dono do produto.
- Na primeira versão existe uma organização, a do dono, e só ele dispara execuções. Convidados veem o painel e aprovam ou reprovam.
- O login é por GitHub, GitLab ou e-mail, para o leitor não técnico não precisar de conta de Git.
- O painel de administração da plataforma já é construído na primeira versão: aprovar contas (que ficam em "aguardando aprovação"), conceder a permissão de criador, ver o uso e a taxa de acerto dos módulos.
- O produto é gratuito e não tem sistema de cobrança.
- O painel nasce em português e inglês, com estrutura de tradução (i18n). Português é o padrão, e os relatórios do agente saem no idioma da conta.

### 3.2 Provedores de Git

- Entram na primeira versão: **GitHub.com, GitLab.com e GitLab self-managed**.
- O GitLab self-managed se conecta por um **conector de saída**, sem VPN: um programa dentro da rede do cliente abre a conexão de dentro para fora até a plataforma. O conector faz parte do Orquestrador.
- GitHub Enterprise Server fica para depois.
- O gatilho automático padrão é todo Merge Request ou Pull Request, não todo push.

### 3.3 Onde as execuções rodam

Tudo roda na CI do próprio cliente, inclusive os menus manuais e os módulos avulsos, que são disparados sob demanda pelo painel. A plataforma não paga máquina. O cliente escolhe entre duas opções:

| Opção | Como funciona | Custo para o cliente |
|---|---|---|
| **Orquestrador** | App de desktop que instala e gerencia o runner oficial do GitHub/GitLab no computador dele. | Nenhum. |
| **Runners hospedados** | Os runners do próprio GitHub ou GitLab. | Minutos de CI além da cota gratuita. |

**Regras do Orquestrador:**
- Feito em Electron, para sair em Mac, Windows e Linux a partir do mesmo código.
- Inicia junto com o computador e mostra o status num ícone na barra do sistema.
- Instala o isolamento sozinho (um runtime de contêiner gratuito), para o agente rodar sem acesso aos arquivos pessoais.
- Só aceita repositórios privados. Em repositório público, um fork poderia executar código na máquina do cliente.
- Com o computador desligado, as execuções esperam e o painel avisa.
- É distribuído por um link de download no painel, sem assinatura digital por enquanto.

### 3.4 Motor e autenticação

1. O motor é sempre o **Claude Code oficial, sem modificação**, em modo headless. O Agent SDK não é usado, porque os termos da Anthropic só permitem assinatura no Claude Code oficial.
2. O login é do próprio usuário, com a assinatura Claude dele. No Orquestrador ele usa o login feito na própria máquina. Na CI hospedada ele mesmo gera o token (`claude setup-token`, validade de um ano) e guarda como segredo no GitHub/GitLab dele.
3. **Nenhuma credencial da Anthropic passa pelos servidores da plataforma.**
4. Não há opção de chave de API por enquanto.
5. Antes de aprovar contas de outras pessoas, o dono pede confirmação por escrito à Anthropic.

### 3.5 Módulos e catálogo

**Campos de um módulo:**
- Nome, descrição e ícone.
- Imagem opcional. O layout do cartão muda quando há imagem.
- Skills, por upload de pasta ou zip, importação de repositório Git ou link do skills.sh, com edição do texto no painel.
- Instruções base e prompts de exemplo.
- Nível de permissão: **leitura** (valida e reporta) ou **desenvolvimento** (altera código).
- Ferramentas exigidas, como navegador.
- Tipo: de esteira ou avulso.
- Modelo padrão: Opus ou Fable, definido pelo criador do módulo. Quem monta o menu pode trocar.

**Modelo padrão de cada módulo:**

| Módulo | Modelo | Motivo |
|---|---|---|
| QA, UX, Design, Pré-app | Opus | Validam, reportam ou prototipam, e um erro aparece no relatório ou na tela. |
| Módulos de desenvolvimento e Tech Lead | Fable | Escrevem ou aprovam código do cliente, e precisam acertar de primeira. |

O Fable consome o limite da assinatura mais rápido que o Opus. Falta confirmar quais planos da assinatura Claude dão acesso a cada modelo; isso entra na prova técnica da etapa 1. O botão "Testar" do estúdio permite rodar o mesmo rascunho nos dois modelos e comparar antes de publicar.

**Sugestão de modelo no estúdio.** Ao criar um módulo, o estúdio já sugere o modelo, em dois momentos:
1. Antes do teste, pela permissão: leitura sugere Opus, desenvolvimento sugere Fable.
2. Depois do teste nos dois modelos, pelo resultado: mostra o acerto e o consumo de cada um e recomenda o mais barato que atingiu o acerto exigido.

### 3.5.1 Economia de tokens

Medidas que entram na primeira versão, da mais barata de fazer para a mais trabalhosa:

| Medida | O que faz |
|---|---|
| **Checagens sem IA primeiro** | Lint, testes e as regras automáticas (como as 62 do `impeccable`) rodam antes do agente. Se já barrarem, o agente nem inicia. |
| **Foco no que mudou** | O agente recebe o diff do MR e a descrição, em vez de explorar o repositório inteiro. |
| **Não repetir trabalho** | Se o commit não mudou desde a última execução, o menu reaproveita o resultado. |
| **Teto por execução** | Cada menu tem um limite de rodadas do agente. Ao atingir, ele para e reporta. |
| **Nível de esforço por módulo** | Além do modelo, o módulo define o esforço de raciocínio. Tarefas simples rodam com esforço baixo. |
| **Mapa do repositório** | Um índice do código, gerado uma vez e atualizado a cada MR, que o agente consulta em vez de ler arquivos. O Graphify é o candidato; ele ajuda na leitura, não na edição. |
| **Navegador econômico** | O agente lê a página como uma lista compacta de elementos, em vez do HTML inteiro. Candidatos: `playwright-cli` (Microsoft) e `agent-browser` (Vercel Labs, Apache-2.0). Os dois fazem print e vídeo. A etapa 1 mede qual gasta menos no mesmo teste, e o módulo QA fica com o vencedor. |
| **Consumo visível** | O painel mostra quanto cada menu e cada módulo gastou, para o dono ver onde cortar. |

O ganho do Graphify precisa ser medido nos projetos do dono na etapa 1. O número divulgado, 71 vezes menos tokens, vem de um único teste num repositório grande; relatos de uso falam em 5 a 10 vezes na exploração, e o ganho é pequeno em repositórios com menos de 100 arquivos. A licença também precisa ser conferida no repositório dele.

**Regras:**
- Só contas com permissão de criador criam e publicam módulos.
- Todo módulo publicado vai para um catálogo único, visível a todas as contas.
- Cada módulo tem versão rascunho e versão publicada. Editar um módulo não muda menus que já estão em uso.
- O botão **Testar** roda o rascunho num projeto de teste, com a mesma visualização ao vivo que o cliente vê.
- Cada skill de terceiros fica fixada numa versão revisada. Uma atualização só entra depois de passar pelo teste do estúdio.

### 3.6 Comportamento dos módulos de leitura

- Validam e reportam: painel, comentário no MR com link para o painel, e job que passa ou falha.
- Cada menu escolhe se uma falha bloqueia a pipeline ou só avisa.
- Evidências (prints, vídeos, eventos) ficam nos servidores da plataforma por 30 dias. O código do cliente não sai da infraestrutura dele.

### 3.7 Stack

- TypeScript de ponta a ponta.
- Painel e API em Next.js, dados em Postgres, atualização ao vivo por streaming do servidor.
- Orquestrador em Electron.
- Repositório novo, dedicado ao produto. O repositório `Landing` serviu só para criar este plano.

## 4. Arquitetura

### 4.1 Peças

| Peça | Papel |
|---|---|
| Painel web + API | Contas, conexões, catálogo, estúdio, menus, esteiras, escritório ao vivo, administração. |
| Banco de dados | Organizações, usuários e papéis, conexões, projetos, skills, módulos e versões, menus, esteiras, execuções, eventos, evidências, aprovações. |
| Armazenamento de evidências | Prints e vídeos, com limpeza automática após 30 dias. |
| Executor | Imagem com o Claude Code oficial, navegador e o programa que traduz e envia os eventos. |
| Orquestrador | Runner local, conector para GitLab self-managed e login opcional do Figma. |
| Configuração de CI | Workflow no GitHub e include no GitLab, instalados por um MR automático. |

### 4.2 O caminho de uma execução

1. Um MR é aberto e a CI do cliente dispara o job do menu.
2. O job sobe o Executor.
3. O programa do Executor busca na API a configuração do menu (módulos, skills, prompt), identificando-se com um token do projeto emitido pela plataforma.
4. Ele grava as skills em `.claude/skills/` e chama `claude -p` com saída `stream-json`.
5. Cada evento é traduzido num passo em linguagem simples e enviado à API. Prints e vídeos sobem para o armazenamento.
6. O painel recebe por streaming e anima o escritório.
7. No fim, o resultado vai como comentário no MR, e o job passa ou falha conforme a configuração do menu.

### 4.3 Pausa para aprovação

Quando um menu precisa de uma pessoa (por exemplo, aprovar o design), o job termina no estado "aguardando aprovação". Ao aprovar, a plataforma dispara a etapa seguinte. Assim nenhum runner fica ligado gastando minutos enquanto espera alguém.

### 4.4 Várias pessoas ao mesmo tempo

| Situação | Como o produto trata |
|---|---|
| Várias pessoas abrindo MRs no mesmo repositório | Cada MR tem a sua própria execução, isolada das outras. |
| Pessoa faz push enquanto o menu ainda roda no mesmo MR | A execução antiga é cancelada e uma nova começa no commit mais recente. O resultado sempre se refere ao último commit. |
| Módulo de desenvolvimento e pessoa mexendo na mesma branch | Antes do push, o agente confere se a branch mudou. Se mudou, ele não força nada: refaz a correção em cima do código novo. Nunca usa push forçado. |
| Dois MRs aprovados separadamente que quebram juntos | O menu pode exigir que o MR esteja atualizado com a branch principal antes de aprovar, usando o recurso do próprio GitHub/GitLab. |
| Duas pessoas editando o mesmo menu ou módulo no painel | Quem salvar por último é avisado de que houve mudança e vê o que mudou, em vez de apagar o trabalho do outro. |
| Mais execuções do que o Orquestrador aguenta | As execuções entram numa fila, e o painel mostra a posição. |

Todas as execuções de uma conta consomem a mesma assinatura Claude. Com várias pessoas disparando execuções, o limite acaba mais rápido e volta a dúvida dos termos (seção 10). Por isso, na primeira versão, várias pessoas podem mexer no código e abrir MRs, mas as execuções rodam só nos projetos do dono.

### 4.5 Cuidados técnicos já conhecidos

- Não usar o modo `--bare` do Claude Code: ele não lê o token de assinatura e não executa hooks.
- O caminho mais confiável para os eventos é ler o `stream-json` e reenviar. Hooks HTTP servem de complemento.
- A hospedagem do painel e do armazenamento ainda não foi escolhida (seção 11).

## 5. Módulos padrão

Os quatro módulos abaixo saem na primeira versão. O dono pode acrescentar skills a qualquer momento pelo estúdio.

### 5.1 QA (leitura)

| Skill | Origem | Função |
|---|---|---|
| `playwright-cli` | Microsoft, oficial | Testa no navegador com prints, vídeo e trace. |
| `qa-only` | gstack | Explora o que mudou no MR e gera relatório com evidências, sem alterar código. |
| `accessibility` | Addy Osmani | Auditoria WCAG 2.2. |
| `playwright-best-practices` | Currents | Teste de API e regressão visual. |
| `diagnosing-bugs` | Matt Pocock | Diagnóstico da causa do defeito. |
| Plano de teste a partir do MR | Escrita por nós | Decide o que testar com base no diff e na descrição. |
| Relatório de bug com evidências | Escrita por nós | Padroniza o que o cliente lê quando algo falha. |

**Ambiente de teste.** Cada projeto tem a configuração "como acessar o app": a URL de preview ou staging, ou o comando para subir o app dentro do job. O onboarding detecta e sugere, e o cliente confirma.

### 5.2 UX (leitura)

| Skill | Origem | Função |
|---|---|---|
| `ux-heuristics` | wondelai | As 10 heurísticas de Nielsen, com grau de severidade. |
| `design-critique` | Anthropic | Crítica de interface. |
| `ux-copy` | Anthropic | Revisão dos textos da interface. |
| `impeccable` | Paul Bakaus | Crítica e auditoria, mais 62 regras automáticas que rodam sem IA. |
| Comparar o comportamento com o esperado | Escrita por nós | Responde "era esse o comportamento?". |

**Referência do esperado.** Descrição do MR, issue ligada, link do Figma (opcional) e o design aprovado pelo módulo de Design. Quando não der para concluir, o painel mostra o comportamento observado com os botões "Era isso" e "Não era isso".

### 5.3 Design

**Fluxo:**
1. Roda antes do código, a partir da descrição do MR ou da issue.
2. Entrega um protótipo navegável, com imagens das telas, no painel.
3. A esteira pausa até alguém clicar "Aprovar" ou "Pedir ajuste".
4. O design aprovado vira a referência do módulo UX.

**Skills:** `frontend-design` (Anthropic), `prototype` (Matt Pocock) e `ui-ux-pro-max`.

**Figma.** "Enviar para o Figma" é um extra opcional, não o padrão. Só funciona para quem tem assento pago e usa o Orquestrador, onde o login do Figma é feito uma vez. O motivo está na seção 10.

### 5.4 Pré-app (avulso)

**O que faz.** Prepara um projeto que ainda não existe, para quem quer começar do zero:
1. Cria o repositório no GitHub ou GitLab do usuário.
2. Faz o versionamento inicial.
3. Instala a configuração de CI e conecta o projeto à plataforma.
4. Cria os menus padrão do projeto.

**Como roda.** A criação do repositório é feita pela própria plataforma, usando a conexão do usuário, porque nesse momento ainda não existe uma CI onde rodar. Os passos seguintes já rodam na CI do repositório novo.

**O que não faz.** Não escreve o app. Isso é o Criador de Apps (seção 8.3), que parte do repositório preparado pelo Pré-app.

## 6. Painel ao vivo: o escritório

**A cena:**
- Um escritório em pixel art, visto de cima.
- O corredor é a esteira, e as mesas ficam na ordem dos menus. Cada mesa é um menu criado pelo usuário.
- O pedido (o MR) passa de mesa em mesa.
- Pessoas de verdade, como o dono e um dev humano, também têm mesa.
- O "chefe" é o personagem do usuário: ele anda até uma mesa quando o usuário clica nela ou quando ela pede aprovação.
- Com mais de uma esteira, cada uma vira um corredor do mesmo escritório.

**Do evento à cena:**

| O que acontece na pipeline | O que aparece |
|---|---|
| O menu começa | O personagem senta e trabalha. |
| Teste no navegador | A tela da mesa mostra o print mais recente. |
| Problema encontrado | O personagem anda até a mesa de quem escreveu o código. |
| Aprovação necessária | O personagem levanta a mão. |
| Menu barrou | Animação de "barrado", e o pedido volta pelo corredor. |
| Menu passou | O personagem comemora, e o pedido segue para a próxima mesa. |

**Animações da primeira versão:** trabalhando, andando até outra mesa, pedindo ajuda, barrado e comemorando.

**Detalhes.** Clicar num personagem abre o que ele fez, com prints, vídeo e diff. Uma visão **Lista** fica ao lado: linha do tempo em linguagem simples, evidências clicáveis e detalhes técnicos recolhidos.

**Arte.** Pacote profissional de pixel art comprado, sem arte gerada por IA. A referência mais próxima é o Pixel Agents, uma extensão do VS Code que mostra agentes do Claude Code num escritório em pixel art.

## 7. Etapas da primeira versão

A ordem coloca primeiro o protótipo para os sócios e, logo depois, a prova das partes tecnicamente incertas.

### Etapa 0: identidade e protótipo (neste chat)

1. Três direções visuais: cores, tipografia e uma tela de exemplo de cada, todas simples e com o escritório como peça central.
2. O dono escolhe uma.
3. Protótipo navegável da experiência completa, aberto por link no navegador:
   - Primeira versão inteira: Conexões, catálogo, estúdio de módulos, criação de menu, esteira, Pré-app, escritório ao vivo com uma execução simulada, administração e o Orquestrador.
   - Uma ou duas telas de cada parte futura, marcadas "em breve": Criador de Apps, Ads, esteiras Dev e Tech Lead.

O protótipo é entregue só por link. O dono não tem assento pago no Figma, então não há envio das telas para lá.

É feito para ser simples e rápido: uma página com dados simulados, sem a stack do produto, e descartável. O que passa para o produto real é a identidade visual e o desenho das telas, não o código.

**Pronto quando:** os sócios conseguem abrir o link e percorrer o fluxo de ponta a ponta sem explicação.

### Etapa 1: prova técnica

Um repositório de teste, sem painel, para tirar as quatro dúvidas que podem mudar o desenho:
1. Claude Code oficial com token de assinatura rodando no GitHub Actions, com as skills carregadas e os eventos saindo em `stream-json`.
2. O mesmo no GitLab CI, onde o token de assinatura não está documentado.
3. Navegador em modo headless tirando prints e vídeo dentro do job, comparando o consumo de tokens do `playwright-cli` com o do `agent-browser`.
4. Criação de repositório pela conexão do usuário, no GitHub e no GitLab, para o módulo Pré-app.

**Pronto quando:** uma execução de teste em cada provedor entrega eventos e prints num endpoint de teste, e um repositório novo é criado por API em cada um.

### Etapa 2: fundação

- Repositório novo, organizado em painel, Orquestrador, Executor e código compartilhado.
- Banco de dados já multi-conta.
- Login por GitHub, GitLab e e-mail.
- Tradução em português e inglês.
- Sistema visual derivado da direção escolhida na etapa 0.

**Pronto quando:** dá para entrar, criar a organização e alternar o idioma.

### Etapa 3: conexões

- Tela "Conexões", a primeira depois do login, com passo a passo para Claude, GitHub e GitLab.
- Botão "Testar" em cada conexão, que roda uma execução mínima e mostra se funcionou.
- Validade do token do Claude visível, com aviso antes de vencer.
- O token do Claude é colado pelo usuário direto nos segredos do GitHub/GitLab, por um link que leva à página certa. Ele nunca passa pela plataforma.
- Onboarding de projeto: detecta "como acessar o app" e instala a configuração de CI por um MR automático.

**Pronto quando:** as três conexões ficam verdes e um projeto recebe a configuração de CI. Nada mais é liberado enquanto as conexões não estiverem verdes.

### Etapa 4: Executor

- Imagem com o Claude Code oficial, o navegador e o programa de eventos.
- Tradução dos eventos em passos em linguagem simples.
- Upload de evidências e limpeza após 30 dias.
- Comentário no MR e resultado do job.

**Pronto quando:** um menu de teste disparado à mão aparece ao vivo numa lista simples no painel.

### Etapa 5: estúdio de módulos e catálogo

- Criação e edição de módulos com todos os campos da seção 3.5.
- Importação de skills por upload, repositório Git e link do skills.sh.
- Versões rascunho e publicada, e fixação de versão das skills de terceiros.
- Botão "Testar" num projeto de teste.
- Catálogo com cartões, com e sem imagem.

**Pronto quando:** um módulo criado do zero é testado, publicado e aparece no catálogo.

### Etapa 6: menus e esteiras

- Criação de menu: módulos, prompt, nome, modo (manual, por projeto, global) e se a falha bloqueia ou só avisa.
- Esteira: menus em ordem, ligados a repositórios.
- Sincronização com a CI e disparo manual pelo painel.
- Pausa para aprovação, como descrito na seção 4.3.

**Pronto quando:** um MR aberto num projeto conectado dispara a esteira sozinho, na ordem certa.

### Etapa 7: módulos padrão

- Montagem dos módulos QA, UX e Design com as skills da seção 5.
- Escrita das três skills próprias.
- Bateria de testes em projetos de exemplo.
- Botões "Era isso" e "Não era isso" do UX, e "Aprovar" e "Pedir ajuste" do Design.
- Módulo Pré-app: criação de repositório, versionamento inicial, configuração de CI e menus padrão.

**Pronto quando:** QA, UX e Design rodam num projeto real do dono com relatórios que fazem sentido para quem não é técnico, e o Pré-app entrega um repositório novo já com a esteira funcionando.

### Etapa 8: escritório ao vivo

- Visão Lista completa.
- Escritório: corredor, mesas, personagens, as cinco animações e o mapeamento da seção 6.
- Painel de detalhes com prints, vídeo e diff.

**Pronto quando:** dá para acompanhar uma execução real do começo ao fim só olhando o escritório.

### Etapa 9: Orquestrador

- Instaladores para Mac, Windows e Linux, gerados juntos.
- Login na plataforma, registro do runner oficial, início automático e ícone de status.
- Instalação do isolamento e bloqueio de repositório público.
- Conector para GitLab self-managed.
- Link de download no painel e aviso de computador desligado.

**Pronto quando:** num computador limpo, baixar, abrir e fazer login basta para uma execução rodar localmente.

### Etapa 10: administração e fechamento

- Painel de administração da plataforma.
- Papéis da organização e convite de leitores.
- Teste de ponta a ponta nos projetos reais do dono, nos três provedores.
- Envio do pedido de confirmação à Anthropic.

**Pronto quando:** o dono usa o produto no dia a dia sem precisar de ajuda.

## 8. O que vem depois (resumo)

### 8.1 Módulos de desenvolvimento e esteiras Dev e Tech Lead

**O que é.** Módulos com permissão de desenvolvimento, que alteram o código do MR para aplicar as correções.

**Como funciona:**
- O agente faz commits direto na branch do MR, com identidade de bot. O cliente liga essa permissão explicitamente no menu.
- Um MR ou uma issue só com a descrição funciona como pedido: a Esteira Dev implementa dentro dele.
- O módulo corrige e revalida dentro da própria execução, e só faz push quando tudo passou.

**Barreiras de qualidade:**
1. **Definição de pronto.** Antes do push: build e testes passam, as validações de QA passam, e o módulo Tech Lead aprova a legibilidade e a manutenção.
2. **Barreira de publicação.** O módulo só é publicado depois de uma bateria de tarefas reais no estúdio, com pelo menos 90% de acerto de primeira.
3. **Freio.** Três rodadas de correção no máximo. Na quarta, o QA escreve a correção exata, o dev aplica e o QA testa de novo de verdade.
4. **Último recurso.** Se ainda falhar, o MR fica bloqueado e o dono da conta recebe um aviso em linguagem simples, com os botões "Tentar de outro jeito", "Simplificar o pedido" e "Pedir ajuda".

Cada caso que chega ao freio conta como defeito do módulo e pesa na "taxa de acerto de primeira", visível no estúdio. Na esteira de um dev humano não há limite: o QA pode barrar quantas vezes for preciso.

**Depende de:** primeira versão rodando, e o módulo QA confiável o bastante para servir de juiz.

### 8.2 Módulos avulsos (Ads)

**O que é.** Módulos ligados ao projeto, mas fora da esteira de desenvolvimento, disparados sob demanda pelo painel.

**Depende de:** definir o que o módulo de Ads entrega e para onde.

### 8.3 Criador de Apps

**O que é.** Um módulo para quem não tem vivência com tecnologia: a pessoa descreve o app, o Pré-app prepara o repositório e os menus, e o Criador de Apps desenvolve o app em cima disso.

**Depende de:** o Pré-app da primeira versão, módulos de desenvolvimento estáveis e uma forma de a pessoa ver o app rodando sem configurar nada. Precisa ser simples e intuitivo.

### 8.4 Outros itens adiados

- GitHub Enterprise Server.
- Módulos privados de uma organização e marketplace de terceiros.
- Avisos fora do painel, como Slack.

## 9. Condições para abrir a outras contas

1. Confirmação por escrito da Anthropic de que o desenho da seção 3.4 é permitido.
2. Assinatura digital do Orquestrador: conta Apple Developer (US$ 99 por ano) e certificado para Windows. Sem isso o macOS bloqueia a abertura e o Windows mostra "fornecedor desconhecido".
3. Decisão sobre aceitar chave de API, que é o caminho documentado para produtos de terceiros e o indicado para times.

## 10. Riscos e pontos a confirmar

| Risco | O que se sabe | Como tratar |
|---|---|---|
| **Termos da Anthropic** | Os termos proíbem produtos de terceiros de oferecer login do claude.ai ou rotear requisições por credenciais de assinatura. Nenhum trecho isenta produto gratuito. A exceção cobre o usuário final entrando com a própria assinatura no Claude Code sem modificação. | Uso só do dono na primeira versão; confirmação por escrito antes de abrir. |
| **Token de assinatura no GitLab** | A integração oficial do GitLab (em beta) só documenta chave de API, Bedrock e Vertex. | Testar na etapa 1. Se não funcionar, o GitLab fica só pelo Orquestrador ou espera a chave de API. |
| **Limite compartilhado** | O token fica preso à assinatura de quem o gerou. Um time inteiro disparando execuções consome o limite de uma pessoa e volta à zona cinzenta dos termos. | Primeira versão restrita aos projetos e MRs do dono. |
| **Minutos de CI** | GitHub Free: 2.000 minutos por mês em repositório privado. GitLab.com Free: 400 por mês. Os números não vieram das páginas de preço atuais. Uma execução com navegador deve levar de 10 a 30 minutos (estimativa). | O Orquestrador é o caminho sem custo. |
| **Isolamento nos três sistemas** | Instalar e gerenciar um runtime de contêiner em Mac, Windows e Linux é a parte mais difícil do Orquestrador. | Tratar como o maior item da etapa 9. |
| **Escrita no Figma** | Só pelo servidor MCP remoto do Figma, com login interativo, assento pago e recurso em beta que passará a ser cobrado por uso. Parte disso veio de trechos de busca, não de leitura direta. | Protótipo navegável como padrão; Figma opcional. |
| **App sem assinatura digital** | Bloqueio no macOS, aviso no Windows e possível falso positivo de antivírus. | Aceitável para uso do dono; resolver antes de abrir. |
| **Skills de terceiros** | Rodam dentro da pipeline do cliente. As escolhidas são MIT ou Apache-2.0; as do Figma não têm licença aberta. | Versão fixada e revisão antes de publicar. |
| **Evidências** | Prints e eventos passam pelos servidores da plataforma, mesmo com o código ficando no cliente. | Retenção de 30 dias e aviso claro na tela Conexões. |
| **Permissão para criar repositórios** | O Pré-app precisa que a conexão do usuário permita criar repositórios, o que amplia o acesso pedido no GitHub e no GitLab. | Confirmar na etapa 1 e pedir essa permissão só a quem usar o Pré-app. |
| **Acerto de 90% do dev** | É uma meta. Nenhum agente acerta todas as vezes. | Barreiras da seção 8.1. |

## 11. Pendências com o dono

1. Criar à mão o repositório do próprio produto e liberar o acesso a ele, antes da etapa 2. O Pré-app ainda não existe para fazer isso.
2. Escolher o pacote de pixel art.
3. Escolher a hospedagem do painel e do armazenamento de evidências.
4. Escolher o nome definitivo do produto. "Esteira" é provisório.
5. Pedir a confirmação à Anthropic antes de abrir para outras contas.

## 12. Fontes

**Termos e documentação da Anthropic**
- [Claude Code: legal and compliance](https://code.claude.com/docs/en/legal-and-compliance.md)
- [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview.md)
- [Claude Code: authentication](https://code.claude.com/docs/en/authentication.md)
- [Claude Code: GitHub Actions](https://code.claude.com/docs/en/github-actions.md)
- [Claude Code: GitLab CI/CD](https://code.claude.com/docs/en/gitlab-ci-cd.md)
- [Claude Code: headless](https://code.claude.com/docs/en/headless.md)
- [Claude Code: hooks](https://code.claude.com/docs/en/hooks.md)
- [Claude Code: MCP](https://code.claude.com/docs/en/mcp)
- [Anthropic Consumer Terms](https://www.anthropic.com/legal/consumer-terms)
- [Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms)
- [Anthropic Usage Policy](https://www.anthropic.com/legal/aup)

**Skills**
- [microsoft/playwright-cli](https://github.com/microsoft/playwright-cli)
- [garrytan/gstack](https://github.com/garrytan/gstack)
- [addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills)
- [currents-dev/playwright-best-practices-skill](https://github.com/currents-dev/playwright-best-practices-skill)
- [mattpocock/skills](https://github.com/mattpocock/skills)
- [wondelai/skills](https://github.com/wondelai/skills)
- [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins)
- [anthropics/skills](https://github.com/anthropics/skills)
- [pbakaus/impeccable](https://github.com/pbakaus/impeccable)
- [figma/mcp-server-guide](https://github.com/figma/mcp-server-guide)

**Outras**
- [About GitHub's plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans)
- [GitLab: CI minutes update for free users](https://about.gitlab.com/blog/ci-minutes-update-free-users/)
- [pablodelucca/pixel-agents](https://github.com/pablodelucca/pixel-agents)
