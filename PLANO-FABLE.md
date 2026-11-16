# Esteira: trabalho para o Fable

Complemento do `PLANO.md`. Lista as partes da primeira versão em que um erro custa caro ou é difícil de perceber, e por isso vale usar o modelo mais capaz. A divisão é um julgamento, não uma medição.

## Critério

Vai para o Fable o que tem pelo menos uma destas características:
- Decisão de arquitetura que o resto do código herda.
- Depuração em ambiente que não dá para ver direto (CI de terceiros, três sistemas operacionais).
- Segurança de credenciais.
- Texto de instrução cuja qualidade define o acerto dos módulos.

## Esforço recomendado

- **Padrão: alto (high).** É o ponto de partida indicado para o Fable; acima disso o ganho é irregular.
- **Extra (xhigh)** só em dois lugares, onde um erro passa despercebido por mais tempo: a etapa 1 (prova técnica) e o isolamento do Orquestrador na etapa 10.
- **Médio não é recomendado aqui.** Estas são justamente as partes em que economizar raciocínio sai caro.

## Partes

### Etapa 1: prova técnica (inteira)

Testa o token de assinatura no GitHub Actions e no GitLab CI, o carregamento de skills, os eventos em `stream-json`, o navegador headless e a criação de repositório por API. O caminho do GitLab não está documentado, então é investigação, não execução de receita. O resultado pode mudar o desenho do produto.

### Etapa 2: fundação (só o desenho)

- Modelo de dados multi-conta: organizações, papéis, conexões, módulos e versões, menus, esteiras, execuções, eventos, evidências e aprovações.
- Estrutura do repositório e contratos entre painel, Executor e Orquestrador.

A implementação a partir desse desenho fica com o Opus.

### Etapa 3: conexões (só a parte de segurança)

- Fluxo em que o token do Claude nunca passa pela plataforma.
- Token do projeto que identifica o Executor na API.
- Permissões pedidas ao GitHub e ao GitLab, incluindo a de criar repositórios para o Pré-app.
- Conector de saída para o GitLab self-managed.

### Etapa 4: Executor (inteira)

O programa que roda o Claude Code oficial dentro do job, traduz eventos em passos em linguagem simples, sobe evidências e reporta o resultado. É o coração do produto, e todo o painel ao vivo depende do formato de evento definido aqui.

### Etapa 6: menus e esteiras (só a orquestração)

- Geração e sincronização da configuração de CI nos três provedores.
- Pausa para aprovação e disparo da etapa seguinte.
- Ordem dos menus e comportamento quando um barra.

### Etapa 7: módulos padrão (as skills próprias)

- Plano de teste a partir do MR.
- Relatório de bug com evidências.
- Comparar o comportamento com o esperado.

Essas três definem a assertividade do QA e do UX. A bateria de testes que mede o acerto também fica aqui.

### Etapa 8: Dev e Tech Lead (inteira)

Os módulos que escrevem e revisam código no repositório do cliente, com meta de 90% de acerto de primeira. Inclui as instruções, o freio de rodadas e a bateria de testes do estúdio.

### Etapa 10: Orquestrador (isolamento e runner)

- Instalação e gerência do runtime de contêiner em Mac, Windows e Linux.
- Registro e ciclo de vida do runner oficial.
- Bloqueio de repositório público e comportamento com o computador desligado.

É o item mais difícil da primeira versão.

## Depois da primeira versão

A parte do Criador de Apps que escreve o app inteiro fica com o Fable.
