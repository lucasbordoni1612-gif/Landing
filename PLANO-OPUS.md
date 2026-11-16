# Esteira: trabalho para o Opus

Complemento do `PLANO.md`. Lista as partes da primeira versão que são trabalho bem definido, com resultado fácil de conferir olhando a tela ou rodando um teste. A divisão é um julgamento, não uma medição.

## Critério

Vai para o Opus o que tem estas características:
- O que construir já está decidido no plano ou num desenho feito antes.
- O erro aparece na hora, na tela ou num teste.
- É volume de telas e formulários, não investigação.

## Esforço recomendado

- **Padrão: alto (high).** O padrão de fábrica do Opus é médio, então é preciso subir manualmente. Para escrever código, o alto reduz erros sem pesar muito no custo.
- **Médio** serve para tarefas mecânicas: textos de tradução, ajustes de estilo, telas repetidas a partir de uma já pronta.
- **Extra (xhigh)** não é necessário. Se uma tarefa do Opus parecer pedir extra, é sinal de que ela pertence ao arquivo do Fable.

## Ordem de uso

O Fable entra antes do Opus em três pontos, porque o Opus constrói em cima do que ele define:
1. Etapa 1 inteira (Fable), antes de qualquer código do produto.
2. Desenho da etapa 2 (Fable), depois a implementação (Opus).
3. Etapa 4 inteira (Fable), antes da etapa 9 (Opus), que consome o formato de evento.

A etapa 0 (protótipo) é do Opus e não depende de nada disso.

## Partes

### Etapa 0: identidade e protótipo (inteira)

- As três direções visuais.
- O protótipo navegável com todas as telas e o escritório simulado.

O resultado é conferido pelo dono a olho, então um erro não passa despercebido.

### Etapa 2: fundação (implementação)

- Montagem do repositório e do banco a partir do desenho feito pelo Fable.
- Login por GitHub, GitLab e e-mail.
- Tradução em português e inglês.
- Sistema visual derivado da direção escolhida.

### Etapa 3: conexões (telas)

- Tela "Conexões" com passo a passo e botão "Testar".
- Aviso de validade do token.
- Onboarding de projeto.

### Etapa 5: estúdio de módulos e catálogo (inteira)

- Criação e edição de módulos.
- Importação de skills por upload, repositório Git e link do skills.sh.
- Versões rascunho e publicada.
- Catálogo com cartões, com e sem imagem.

### Etapa 6: menus e esteiras (telas)

- Criação de menu e escolha do modo.
- Seletor de apps e o botão "Pedir uma mudança".
- Montagem da esteira e ligação com repositórios.

### Etapa 7: módulos padrão (montagem)

- Reunir as skills de terceiros de QA, UX e Design, com versão fixada.
- Módulo Pré-app.
- Botões de aprovação do UX e do Design.

### Etapa 9: escritório ao vivo (inteira)

- Visão Lista.
- Escritório em pixel art: corredor, mesas, personagens e as cinco animações.
- Painel de detalhes com prints, vídeo e diff.

Consome o formato de evento definido pelo Fable na etapa 4.

### Etapa 10: Orquestrador (casca do app)

- Janela, login, ícone na barra do sistema e início automático.
- Geração dos instaladores para os três sistemas.
- Link de download no painel.

### Etapa 11: administração e fechamento (inteira)

- Painel de administração da plataforma.
- Papéis e convites.
- Roteiro do teste de ponta a ponta.

## Depois da primeira versão

O módulo de Ads e as telas do Criador de Apps podem ficar com o Opus. A parte do Criador de Apps que escreve o app fica com o Fable.
