# credits-agent

Agente que, todo dia:

1. **Descobre** programas oficiais de créditos gratuitos e benefícios para startups (APIs de IA, cloud, GPUs, bancos de dados, devtools, SaaS).
2. **Verifica** cada programa na página oficial do próprio provedor e extrai valor, requisitos, prazos, restrições geográficas, elegibilidade e termos, com citações literais da página.
3. **Avalia a elegibilidade** com regras fixas (o modelo não decide) usando só os dados **verificados** da sua empresa.
4. **Prepara a inscrição** dos programas elegíveis e **pede sua aprovação** antes de enviar cada uma.
5. **Monitora seus e-mails** (somente leitura) para registrar confirmações, aprovações, recusas e créditos concedidos.
6. Mantém um **banco de créditos** (disponíveis, usados, saldos e datas de expiração) e um relatório diário.

## Garantias de segurança

| Regra | Como é garantida |
|---|---|
| Sem inscrição duplicada | Índice único no banco: uma inscrição ativa por programa. Também bloqueia programas já recebidos (créditos no banco ou `previous_programs` do perfil), programas não acumuláveis (`exclusive_with`) e reinscrição antes da carência. O envio muda o status `approved → submitting` de forma atômica, então nada sai duas vezes. |
| Nada é enviado sem você | Só `credits-agent approve` libera o envio. A aprovação fica presa ao *hash* do pacote: se uma resposta, o seu perfil ou as regras do programa mudarem depois, a aprovação deixa de valer. |
| Só dados verificados | O agente usa apenas campos com `verified = true` no perfil. Toda resposta indica os campos de origem; números, e-mails e domínios que não aparecem nesses campos fazem a resposta voltar para você. Dados não verificados não são enviados à API. |
| Fontes oficiais | Um programa só entra se a URL estiver no domínio do próprio provedor. Blogs e agregadores servem só como pista. Redirecionamento para domínio estranho marca o programa como quebrado. |
| Respeito aos termos | O agente respeita o `robots.txt`, espaça as requisições, não faz login, não preenche formulários de terceiros com robô e não aceita termos por você. Formulários web viram um pacote pronto para você colar e enviar. Envio automático só acontece quando a página oficial pede inscrição por e-mail num endereço do domínio do provedor e os termos não proíbem automação. |
| E-mail seguro | A caixa é aberta em modo somente leitura (`EXAMINE` + `BODY.PEEK`): nada é marcado como lido, movido, apagado ou respondido, e nenhum link é clicado. Um e-mail só altera o banco se o seu servidor de e-mail atestar DKIM/DMARC do domínio oficial e se o valor aparecer no texto. Os outros casos vão para revisão manual. |

## Instalação

```bash
cd credits-agent
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
credits-agent init          # cria config.toml, company_profile.toml e data/credits.db
```

Defina a credencial da API do Claude (`export ANTHROPIC_API_KEY=...` ou `ant auth login`).
Modelo padrão: `claude-opus-5-5`, com fallback do servidor em caso de recusa (`fallbacks = "default"`). Os dois podem ser trocados no `config.toml`.

### 1. Perfil da empresa (`company_profile.toml`)

Preencha os campos e marque `verified = true` **apenas** no que você conferiu num documento (diga qual em `source`). Confira com:

```bash
credits-agent profile
```

O arquivo está no `.gitignore` e não deve ir para o repositório.

### 2. E-mail (opcional, recomendado)

No `config.toml`, ative `[email] enabled = true` (IMAP) e, se quiser receber o relatório por e-mail, `[smtp] enabled = true`. As senhas ficam em variáveis de ambiente (veja `deploy/env.example`). No Gmail, use uma *senha de app*.

### 3. Agendamento diário

- cron: `deploy/crontab.example`
- systemd: `deploy/credits-agent.service` + `deploy/credits-agent.timer`

A execução usa um *lock*, então duas execuções nunca rodam ao mesmo tempo.

## Uso no dia a dia

```bash
credits-agent run-daily                 # tudo: descobrir, verificar, avaliar, preparar, enviar aprovados, ler e-mails
credits-agent report                    # relatório atual (também salvo em data/reports/AAAA-MM-DD.md)

credits-agent programs [--eligible]     # programas e elegibilidade
credits-agent show aws:aws-activate     # detalhes, regras e o motivo de cada check
credits-agent verify aws:aws-activate   # reler a página oficial agora

credits-agent applications --pending    # inscrições aguardando você
credits-agent review 3                  # pacote completo: respostas, fontes, termos, checks
credits-agent set-answer 3 5 "texto"    # preencher/corrigir a resposta nº 5 (anula aprovação anterior)
credits-agent approve 3 [--submit]      # pede que você digite APROVAR
credits-agent reject 3 --reason "..."
credits-agent mark-submitted 3          # depois de enviar no site oficial (ou o agente detecta o e-mail de confirmação)
credits-agent prepare chave --force     # preparar programa 'needs_review' depois de você confirmar o requisito

credits-agent credits list
credits-agent credits expiring --days 30
credits-agent credits add --program aws:aws-activate --amount 5000 --expires 2027-11-30
credits-agent credits use 1 120.50 --note "fatura de novembro"
credits-agent export backup.json
```

### Ciclo de vida de uma inscrição

```
draft ─(dados completos)─► awaiting_approval ─approve─► approved ─► submitting ─┬─► submitted ─► accepted / rejected
  ▲                              │                                               └─► awaiting_manual_submission ─(você envia)─► submitted
  └──── set-answer ◄─────────────┘ reject ─► rejected_by_user
```

## Como funciona

| Módulo | Função |
|---|---|
| `discovery.py` | Sementes (`sources/seed_programs.toml`), busca diária com *web search* (as consultas mudam a cada dia), validação de domínio oficial, deduplicação, verificação de páginas, checagem de citações, leitura dos termos e detecção de mudanças |
| `fetcher.py` | Coleta educada: `robots.txt`, intervalo por site, só https, HTML → texto + links |
| `eligibility.py` | Regras de país, estágio, idade, captação, receita, constituição, investidor/aceleradora, prazo, exclusividade, carência e duplicidade |
| `applications.py` | Rascunho com base nos fatos verificados, checagem das respostas contra os fatos de origem, aprovação vinculada ao hash, envio atômico |
| `submitter.py` | E-mail oficial (SMTP da sua conta) ou pacote Markdown/JSON para envio manual |
| `inbox.py` | IMAP somente leitura, filtro por domínio oficial e palavras-chave, DKIM/DMARC, classificação, registro de créditos com validade |
| `db.py` | SQLite: `programs`, `program_snapshots`, `applications`, `credits`, `credit_usage`, `emails_processed`, `events` (auditoria) |
| `llm.py` | API do Claude: saída estruturada (JSON Schema) para extração, rascunhos e e-mails; *web search*/*web fetch* para descoberta |

O modelo só é chamado quando uma página muda, então em dias sem mudanças o custo fica perto de uma busca de descoberta.

## Limitações

- **A extração pode errar.** Cada programa guarda citações da página e o nível de conferência (`ok`/`partial`/`weak`). Leia o `review` antes de aprovar, principalmente valores e termos.
- **O envio por formulário web é feito por você.** É proposital: a maioria dos programas exige login, CAPTCHA ou proíbe envios automatizados.
- **As URLs semente não foram testadas daqui** (a rede deste ambiente bloqueia esses sites). Na primeira execução, o agente marca as URLs quebradas no relatório, e a descoberta encontra páginas novas.
- **Privacidade:** os campos verificados do perfil e o texto dos e-mails relevantes são enviados à API do Claude para redigir e classificar. Campos não verificados ficam na sua máquina.
- Saldo usado: registre com `credits use` (ou exporte da fatura do provedor). O agente não acessa consoles de faturamento.

## Testes

```bash
pytest
```

Os testes rodam offline, com o modelo e a rede simulados, e cobrem deduplicação, trava de aprovação, verificação de respostas, regras de elegibilidade, `robots.txt`, autenticação de e-mail, registro de créditos e uma execução diária completa.
