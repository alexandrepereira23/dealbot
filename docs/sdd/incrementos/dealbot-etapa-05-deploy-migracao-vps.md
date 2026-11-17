---
id: dealbot-etapa-05-deploy-migracao-vps
titulo: "Dealbot — Etapa 5: deploy e migração para VPS"
status: em_validacao
modo: rigoroso
risco: alto
base_commit: 9559cbe2e95401bce0cb343ff8cceafb3493f1b6
aprovacao: usuario
criado_em: 2026-11-16
---

# Entrega da etapa 5

## Escopo e estado

Implementação local autorizada após aprovação do plano baseado em
`PROMPT_DEALBOT_ETAPA_05.md`. O checkout começou exatamente no commit de referência,
com os arquivos não rastreados `Dealbot context .md` e `PROMPT_DEALBOT_ETAPA_05.md`,
preservados. Não houve commit, push, deploy, alteração de DNS/Caddy da VPS,
pausa de serviço produtivo ou aplicação de SQL remoto.

**Preparação implementada; validação Docker/Linux pendente.** O guia operacional
é [docs/deploy-vps.md](../../deploy-vps.md). Dados reais de domínio/rede/VPS/caminhos
continuam parametrizados. Nenhuma credencial foi solicitada.

## Contrato entregue

- Dockerfiles por serviço, usuários não root, bases por versão/digest, locks npm/Python
  e allowlists de contexto. Python 3.12, Node 24 LTS, Next 16 estável/standalone.
- `deploy/compose.yaml`: somente bot/API/painel, estado privado, mídia dedicada,
  limites comuns, SIGTERM, prazos, rootfs somente leitura, capacidades removidas,
  reinício e rotação de logs. Sem migração automática, Postgres ou proxy produtivo novo.
- Caddy existente por rede Docker externa ou override de portas exclusivamente loopback.
  Trecho preserva `/api` e `/media`; painel compilado com API relativa `/api`.
- `LIMPEZA_ATIVA` validada estritamente; Compose começa em `false`. Encerramento
  cancela agendamentos e drena ciclo em andamento com prazo. Default fora do Compose
  conserva o comportamento anterior (`true`).
- CLI de prontidão com prazo, consultas somente leitura e token opcional por env privado.
  Retorno 2 sem prova de Auth; inventário SQL separado para definições/RPCs/grants.
  Nunca chama RPC que libere o gate legado durante diagnóstico.
- Backup SQLite pela API oficial, manifesto privado de integridade/checkpoints,
  restauração exclusiva em diretório novo, verificação e recusa de sobrescrita.
- Laboratório com fronteiras Telegram/Supabase falsas, API/SDK/pipeline/SQLite/Pillow/UI
  reais, Caddy HTTPS local e navegador. Executor Docker adicional testa POSIX,
  permissões, publicação/remoção reservada e recriação quando houver daemon.
- Guia parametrizado de inventário, pausa/backups, schema, API→bot→painel/proxy,
  limpeza no momento seguro, smoke, observação e rollback compatível sem apagar volumes.

## Versões e segurança

Consultadas as políticas oficiais:

- https://nodejs.org/en/about/previous-releases
- https://nextjs.org/support-policy
- https://nextjs.org/docs/app/guides/upgrading/version-16

| Componente | Versão selecionada/usada |
|---|---|
| Node de verificação e imagens | 24.22.3 LTS |
| Next / React | 16.4.6 / 19.3.1 |
| Python de deployment/testes bot | 3.12.16 |
| Pillow / python-dotenv | 13.0.0 / 1.2.2 |
| Telethon / Supabase Python | 1.36.0 / 2.9.1, contratos preservados |
| Supabase JS | 2.119.0 (lockfiles) |
| Zod | 4.6.7, migração coberta pelos testes de validação existentes |
| Caddy local e imagem de laboratório | 2.11.9 |
| PostgreSQL local real | 18.6, binários Windows; sessões TCP independentes com pg 8.21.0 |
| Playwright / Chromium | 1.61.1 / Chrome for Testing 149.0.7827.55 |
| Docker CLI / Compose disponíveis | 29.2.0 / 5.0.2; daemon Linux indisponível |

`npm audit --omit=dev` terminou com **0 vulnerabilidades** em API e painel.
Auditoria completa npm também retornou 0 após atualizar os locks.
`pip-audit --no-deps --disable-pip -r requirements.lock` retornou
**nenhuma vulnerabilidade conhecida**. Não equivale a auditoria das camadas Debian,
cuja análise das imagens construídas permanece pendente.

Na resolução inicial, Zod 3 apresentava GHSA-mrhx-c7xc-m3w5; Pillow 12.x e
python-dotenv 1.0.1 também tinham correções disponíveis. Foram atualizados e
revalidados. ESLint 9.39.5 é ferramenta de desenvolvimento compatível com os peers
do `eslint-config-next`; o registro o marca descontinuado. A tentativa com ESLint
10 gerou conflitos dos plugins transitivos, por isso não foi mantida. Não compõe
o runtime standalone. Os únicos suppressions novos são locais à regra
`set-state-in-effect`, para preservar limpeza imediata de dados ao invalidar sessão
e início da consulta externa de filtros, sem redesenhar o ciclo de Auth/polling.

## Evidências executadas

As contagens abaixo são desta implementação, não herdadas da etapa 4.
Node/Python foram executados por caminhos absolutos em ferramentas temporárias.
Os comandos npm equivalentes abaixo devem usar Node 24 conforme `.nvmrc`.

| Verificação | Comando/resultado |
|---|---|
| Bot completo | Em `bot/`: `python -B -m unittest discover -s tests -v`: **479 executados, 457 aprovados, 22 skips de POSIX/Linux, 0 falhas**, Python 3.12.16/Windows. Contratos Telethon/Supabase e codecs WebP presentes. |
| Dependências Python | Instalação do lock com hashes em venv descartável; `pip check` sem dependências quebradas. |
| API | `npm ci` e `npm test`: **110 executados, 107 aprovados, 3 skips Linux, 0 falhas**. Inclui dois novos testes do agendamento/desligamento da limpeza. |
| Frontend | Instalação limpa, `npm test`: **50/50**, `npm run lint`, `npm run typecheck` e build aprovados. |
| Build isolado | `deploy/lab/validar-local.py`: cópia por allowlist sem `.env`; `next build` 16.4.6/Turbopack e standalone inicializado. |
| SQL etapa 2 | `node tests/sql-etapa2.local.mjs` com PostgreSQL 18.6 local novo: aplicação dupla, preservação, defaults, constraints e preflight aprovados. |
| SQL etapas 3/4 | `node tests/sql-etapa3.local.mjs`: **67 grupos aprovados**, incluindo revisão de cópias/expiração e concorrência por barreiras/locks entre sessões reais. |
| SQL instalação limpa | `deploy/lab/sql.local.mjs`: schema completo aplicado duas vezes em terceiro banco novo, inventário somente leitura e grants verificados. |
| Backup SQLite | `python -B -m unittest discover -s deploy/tests -v`: **2/2**, com WAL ativo, checkpoint congelado, restauração, detecção de alteração e recusa de sobrescrita/origem ausente. |
| Smoke browser | HTTPS local via Caddy, login sintético com SDK real, 401 sem token, CORS permitido/negado, CSP e bytes legados, polling sem F5, compra antes da imagem, WebP na mesma instância, 503→200 de Auth sem logout, 390×844 e 1440×900 sem overflow. |
| Processo/persistência local | Segunda instância recusada, reinício de processos bot/API, fingerprints de campos congelados da fila e bytes de mídia preservados. Não equivale a recriação de container/SIGTERM POSIX. |
| Restauração integrada | No último `validar-local.py`, backup online do estado real da fixture e restauração em diretório novo conservaram fingerprints de fila/checkpoints. Arquivo `.tar.gz` da mídia foi restaurado em outro diretório e todos os hashes WebP comparados com sucesso. |
| Sintaxe/configuração | Compose produção, override host e laboratório com perfil SQL: `config --quiet` aprovado. Caddy `validate --adapter caddyfile` aprovado para trecho e fixture, com versão 2.11.9. `sh -n` dos três scripts shell aprovado via WSL. |
| Simulação limitada | `python -B -m simulacao --seed 42 --live 10 --historico 30 --db-ms 1 --midia-ms 2`: 40 ofertas aprovadas, fila de ofertas zerada, concorrência máxima 4/1. Mede até terminalização das ofertas; mídia ainda tinha pendências na fotografia de métricas. Não é SLA/VPS nem prova de drenagem de todas as fotos. |

### Como repetir SQL sem psql instalado

`deploy/lab/sql.local.mjs` requer `DEALBOT_LAB_BASE`, `DEALBOT_LAB_PG_BIN` e
`DEALBOT_TEST_PG_MODULE` absolutos. Cria cluster e bancos novos no temporário,
ouve só `127.0.0.1`, executa as suítes e para seu próprio cluster no `finally`.
Não usa serviço Postgres já existente. A alternativa `pg` mantém as mesmas guardas
de banco local descartável, sem senha/query, e usa uma conexão real por sessão.
O caminho padrão dos runners continua sendo psql. PGlite não foi usado como prova.

No laboratório desta sessão os artefatos SQL ficam no temporário
`dealbot-pg-EFFCZe`, com o cluster parado. O smoke local final usa outro diretório
`dealbot-local-o1tyoclu`; nomes não representam caminhos produtivos.

## Falhas intermediárias e limitações

- O primeiro build na árvore original detectou `.env.local` pelo carregamento
  automático do Next. Foi substituído como evidência pelo build em cópia allowlist
  sem arquivos de ambiente, usando exclusivamente valores sintéticos. Nenhum valor
  desses arquivos foi transcrito no relatório.
- Um teste de backup inicialmente expôs `fsync` em handle somente leitura no
  Windows e conexões SQLite não fechadas pelo context manager. Corrigidos com
  handle apropriado e fechamento explícito; testes passaram após a correção.
- O primeiro adaptador SQL tentou importar `Client` como named export de CJS.
  Corrigido; a execução completa com PostgreSQL real passou posteriormente.
- Uma interrupção do laboratório deixou uma API temporária remanescente. Ela foi
  identificada como processo criado pelo ensaio e encerrada; o runner agora recusa
  portas ocupadas e verifica a vida do processo esperado, evitando usar uma API antiga.
  Smoke posterior completo passou.
- A simulação com defaults `python -B -m simulacao --seed 42` ultrapassou o orçamento
  de 180 segundos e não é declarada concluída. O cenário limitado acima terminou.
- WSL disponível é versão 1, Python 3.14 e usuário root; não foi aceito como substituto
  das condições Python 3.12/não root/filesystem dos containers.
- `docker info` e tentativa de `docker build --target producao -t dealbot-api:etapa5-verificacao backend`
  falharam pela ausência do pipe `dockerDesktopLinuxEngine`. **Não houve build de
  imagem, execução Docker Linux ou auditoria de camada OS bem-sucedida.**
- `deploy/lab/validar-compose.py`, o Dockerfile SQL e dump/restore lógico por pg_dump
  estão preparados, mas ainda não executados. Também pendem UID/GID/setgid, rootfs
  read-only, acesso a `/proc/self/fd`, SIGTERM e recriação sob a configuração dos containers.
- Auth/Telegram/Storage gerenciados, TLS público, DNS e filesystem da VPS não foram
  acessados ou certificados. Backup de bucket real e restauração remota não executados.

## Condições para concluir a etapa

1. Disponibilizar daemon Docker Linux local descartável e executar
   `deploy/lab/validar-compose.py` conforme o guia.
2. Corrigir qualquer falha e registrar contagens POSIX, build/digests, usuários,
   permissões, reinício/recriação, restauração SQLite/mídia/SQL e análise das imagens.
3. Inventariar domínio/rede/caminhos e preparar SHA candidato e imagens de rollback
   compatíveis. Preencher dados privados fora do repositório.
4. Executar a virada real somente em autorização/janela próprias: backup/pausa →
   schema → API sem limpeza → um bot → painel/proxy → smoke → habilitar limpeza.

Rollback sempre conserva schema e volumes, exige código compatível com SQLite v7,
RPCs/pins e mídia local e não reativa coletor/limpador antigo. O guia contém os
comandos parametrizados; nenhum deles foi aplicado à produção.
