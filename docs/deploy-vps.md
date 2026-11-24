# Dealbot na VPS — preparação, virada e rollback

[Visão geral](../README.md) · [Execução local](uso-local.md) · [Testes](testes.md)

Este guia descreve a implantação em uma VPS com Caddy, incluindo a virada de
uma instalação existente e o rollback. Antes da virada, execute o
[ensaio Docker/Linux](testes.md#ensaio-automatizado-dockerlinux). Testes no host
e `compose config` não substituem esse ensaio.

## 1. Topologia e inventário obrigatório

O Compose de produção contém somente **API Express, bot Python e painel Next**.
Postgres/Auth/Storage legado continuam no Supabase gerenciado. O Caddy já existente
recebe `/api/*` e `/media/*` na API, preservando prefixos; o restante segue ao painel.
Novas fotos são WebP locais; jobs antigos mantêm seu destino Supabase congelado.

Preencher uma ficha privada antes da janela:

| Parâmetro | Confirmar |
|---|---|
| VPS/acesso | Host, operador, distribuição, arquitetura, RAM, espaço livre e inodes. |
| `<DOMINIO_DEALBOT>` | DNS A/AAAA e HTTPS; `dealbot.usenexora.online` é somente exemplo. |
| Caddy | Versão, host ou container, arquivo/imports, rede, comando de validação/recarga e sites existentes. |
| Rede | Docker Engine/Compose, redes e portas em uso; saída Telegram/Supabase. |
| Coletores/limpadores | Localização, SHA e supervisor de TODOS: Railway, systemd, Compose, outros hosts e cron. |
| Estado | Caminho real do `inbox.sqlite3`, WAL/SHM, dono, versão e fila/checkpoints. |
| Mídia | Diretório dedicado atual ou novo, dono/grupo, filesystem e crescimento diário. |
| Supabase | Projeto correto, versão Postgres, schema/RPCs/grants, origem exata de fotos antigas, métodos de Auth e URLs de retorno. |
| Versões | SHA candidato, imagens/digests, SHA compatível de rollback e suas configurações públicas de build. |
| Backup | Diretório privado, referência externa protegida, horário, retenção e restauração ensaiada. |

O candidato precisa conter esta implementação em um SHA revisado. A referência
`9559cbe2e95401bce0cb343ff8cceafb3493f1b6` não inclui estes Dockerfiles; não usar seu
SHA para rotular imagens de uma árvore modificada. Commit/publicação são passos
separados do operador. Não há imagem de rollback presumida ou publicada por esta entrega.

Inspeção remota somente quando autorizada. Inventário local somente leitura:

```bash
export STATE_HOST_DIR=/srv/dealbot/state
export MEDIA_HOST_DIR=/srv/dealbot/media
export BACKUP_DIR=/srv/dealbot/backups
sh deploy/scripts/preflight.sh
```

O script não certifica DNS, Supabase ou ausência de escritor em outro host.
Confirmar filesystem local compatível (por exemplo ext4/xfs); não colocar SQLite
em NFS/SMB, pasta sincronizada ou volume descartável de release.

## 2. Arquivos de configuração e imagens

Requer Docker Compose com `env_file.format: raw` (2.30+). Exemplos em `deploy/env/`:

- `compose.env.example`: interpolação, caminhos e configurações públicas de build;
- `bot.env.example`: Telegram e service role somente no runtime do bot;
- `api.env.example`: service role e chave pública de Auth somente no runtime da API.

Instalar os arquivos reais fora da árvore de release, por exemplo em `/etc/dealbot/`,
com diretório `0700` e arquivos `0600`. Preencher localmente, sem colar credenciais no chat.
Não executar `docker compose config` sem `--quiet` em logs compartilhados: a resolução inclui segredos.
Não copiar ambientes reais para os exemplos. Valores com `$` são literais nos envs de runtime.

No arquivo de interpolação, definir SHA completo, caminhos absolutos e os mesmos IDs
usados no build/runtime. Defaults: bot `10001:10000`, API `10002:10000`, painel `10003:10003`.
Confirmar que os IDs não conflitam com a administração local.

Crie diretórios **novos e dedicados**, somente na preparação autorizada da VPS.
Informe os mesmos `BOT_UID`, `MEDIA_GID`, `STATE_HOST_DIR` e `MEDIA_HOST_DIR` do
arquivo de interpolação; os valores abaixo são exemplos, não um `source` do env.

```bash
BOT_UID=10001
MEDIA_GID=10000
# Use os caminhos absolutos já definidos na seção 1, ajustados ao inventário.
sudo install -d -m 0700 -o "$BOT_UID" -g "$MEDIA_GID" -- "$STATE_HOST_DIR"
sudo install -d -m 2770 -o "$BOT_UID" -g "$MEDIA_GID" -- "$MEDIA_HOST_DIR"
sudo install -d -m 0700 -o "$(id -u)" -g "$(id -g)" -- "$BACKUP_DIR"
```

Se os diretórios **já existem**, pare o coletor e suspenda qualquer limpeza antes
de ajustar permissões. Depois do backup, confira com `sudo stat -c '%F %a %u:%g %n'`
e `sudo realpath -e` que os dois caminhos são as raízes dedicadas esperadas (não
links, ancestrais, outros mounts ou caminhos compartilhados). Só então corrija
as raízes, se necessário, com os valores do mesmo env:

```bash
sudo chown -h -- "$BOT_UID:$MEDIA_GID" "$STATE_HOST_DIR" "$MEDIA_HOST_DIR"
sudo chmod 00700 -- "$STATE_HOST_DIR"
sudo chmod 02770 -- "$MEDIA_HOST_DIR"
```

Não use `chown -R`. Em estado migrado, inspecione individualmente os arquivos
conhecidos do SQLite e do lock; se necessário, ajuste **somente** os regulares
confirmados nesse volume dedicado, nunca links, com o serviço parado. O estado
usa `0700` na raiz e `0600` em arquivos privados. A API **não monta** esse
diretório. No volume de mídia, o **bot é dono** porque precisa executar `fchmod`
na raiz ao inicializar o armazenamento; escrita pelo grupo não permite isso.
Setgid `2770` garante o grupo compartilhado (`MEDIA_GID`); o bot publica finais
`0640`. A API precisa de leitura dos finais e escrita/execução na raiz para
remover chaves conhecidas após reserva, mas a rota HTTP é só GET/HEAD. Não monte
mídia como somente leitura na API. O limite de saída padrão é `358400` bytes;
o Compose propaga a mesma configuração aos dois serviços.

Usar um diretório imutável por SHA, por exemplo `<RELEASE>=/opt/dealbot/releases/<SHA>`.
Os comandos seguintes pressupõem Bash e execução nessa release:

```bash
export RELEASE=/opt/dealbot/releases/PREENCHER_SHA
export COMPOSE_ENV=/etc/dealbot/compose.env
COMPOSE_ARGS=(--env-file "$COMPOSE_ENV" -f "$RELEASE/deploy/compose.yaml")
# Somente se o Caddy estiver no HOST:
# COMPOSE_ARGS+=(-f "$RELEASE/deploy/compose.caddy-host.yaml")
dc() { docker compose "${COMPOSE_ARGS[@]}" "$@"; }
dc config --quiet
dc build --pull
```

Node `24.22.3`, Python `3.12.16` e suas bases multi-arquitetura estão fixados por
digest. Next `16.4.6`, React `19.3.1`, lockfiles npm e `bot/requirements.lock`
controlam dependências. `npm ci` e hashes Python evitam resolução de runtime variável.
Contextos são allowlists: `.env`, SQLite, sessões, fotos e backups não entram nas imagens.
Frontend recebe somente valores públicos no build; trocar URL/chave pública/polling exige rebuild.
`NEXT_PUBLIC_API_URL=/api` é fixado no Compose. Nenhum service role/TG é build arg.

Registrar os IDs reais antes da janela:

```bash
dc images
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "dealbot-api:<SHA>" "dealbot-bot:<SHA>" "dealbot-painel:<SHA>"
```

Conservar as imagens do SHA compatível anterior. Atualizações de patches/digests
exigem regenerar locks quando aplicável e repetir as verificações afetadas.

## 3. Integração ao Caddy existente

O trecho em `deploy/caddy/dealbot.caddy.example` não substitui nenhum Caddyfile.
`handle`, ao contrário de `handle_path`, conserva os prefixos. Não adicionar outro
proxy de produção nem publicar novas portas 80/443.

### Caddy em Docker

- Preencher `CADDY_NETWORK` com uma rede existente, alcançável pelo Caddy.
- A API e o painel entram nessa rede com aliases `dealbot-api` e `dealbot-painel`.
- Bot fica somente na rede dos serviços; nenhuma porta do projeto é publicada.
- Preferir uma rede dedicada de backend do Caddy para o Dealbot. Se for necessário
  conectar o proxy à rede, fazê-lo explicitamente na janela; registrar a mudança
  na configuração persistente do supervisor do Caddy.

Ambiente do processo **Caddy**, não do Compose Dealbot:

```text
DEALBOT_DOMAIN=<DOMINIO_DEALBOT>
DEALBOT_API_UPSTREAM=dealbot-api:3333
DEALBOT_PAINEL_UPSTREAM=dealbot-painel:3000
```

### Caddy no host

Acrescentar `deploy/compose.caddy-host.yaml`. Ele publica somente
`127.0.0.1:13333` e `127.0.0.1:13000` e usa uma rede privada do projeto.
Preencher `CADDY_NETWORK=dealbot-proxy-host` para satisfazer a interpolação do arquivo base;
o override não procura uma rede externa.

```text
DEALBOT_DOMAIN=<DOMINIO_DEALBOT>
DEALBOT_API_UPSTREAM=127.0.0.1:13333
DEALBOT_PAINEL_UPSTREAM=127.0.0.1:13000
```

Caso o Caddy não receba envs, substituir os três placeholders por valores exatos
no trecho a integrar. Validar a configuração **completa** com a versão instalada
e os imports/certificados existentes antes da recarga. Não há comando universal
de reload seguro sem inventariar se o supervisor é systemd ou Docker.
O Caddy continua sendo o único salto confiável da API (`trust proxy=1`).

`CORS_ORIGIN=https://<DOMINIO_DEALBOT>` não tem barra final nem caminho.
O CSP do painel conserva `'self'` e a origem de `NEXT_PUBLIC_SUPABASE_URL` em
`img-src`; confirmar URLs legadas se o projeto usa domínio de Storage personalizado.
Não abrir wildcard para resolver divergência de origem. Confirmar também Site URL
e allowlist de redirects no Supabase Auth na janela autorizada, conforme os métodos usados.

## 4. Backup consistente e restauração ensaiada

### SQLite e mídia

Na janela final: suspender o limpador e parar o coletor anterior antes de capturar
o conjunto de backups. O backup online abaixo funciona com WAL ativo; copiar só
`inbox.sqlite3` não é backup consistente. A helper não abre `.env`, não muda a fila
e não sobrescreve arquivos/diretórios existentes.

```bash
umask 077
python3 deploy/scripts/backup-sqlite.py backup \
  "$STATE_HOST_DIR/inbox.sqlite3" "$BACKUP_DIR/inbox-final.sqlite3"
python3 deploy/scripts/backup-sqlite.py verify "$BACKUP_DIR/inbox-final.sqlite3"
tar --one-file-system --numeric-owner --acls --xattrs \
  -C "$MEDIA_HOST_DIR" -czf "$BACKUP_DIR/media-final.tar.gz" .
sha256sum "$BACKUP_DIR/inbox-final.sqlite3" "$BACKUP_DIR/media-final.tar.gz" > "$BACKUP_DIR/arquivos.sha256"
```

O operador precisa de permissão de leitura do estado, por exemplo executar a helper
como o UID do bot, ou por um operador privilegiado, sempre com destino privado.
Após cópia para outra máquina, conferir hashes e ACLs (no Windows, configurar ACL privada).
Manter cópia protegida fora da VPS; dumps e SQLite contêm texto/URLs privados.

Restaurar somente em caminho NOVO descartável:

```bash
python3 deploy/scripts/backup-sqlite.py restore \
  "$BACKUP_DIR/inbox-final.sqlite3" "$BACKUP_DIR/ensaio-estado-novo"
install -d -m 0700 "$BACKUP_DIR/ensaio-media-nova"
tar --no-same-owner -xzf "$BACKUP_DIR/media-final.tar.gz" -C "$BACKUP_DIR/ensaio-media-nova"
```

Comparar hashes dos finais conhecidos, contagens e fingerprints privados do manifesto.
A helper verifica integridade, versão e todas as tabelas de fila/checkpoints presentes.
Não iniciar bot de teste com credenciais reais sobre essa cópia. Para a migração real
de host/caminho, parar o escritor de origem e restaurar a cópia FINAL no diretório novo,
ajustando dono/grupo; se o estado já está no caminho correto, preservá-lo diretamente.
O lock não é removido para tentar liberar outra instância: o lock vivo pertence ao processo.

### Dados Supabase e objetos legados

Usar cliente `pg_dump` de major igual ou superior à do servidor, conexão TLS por
serviço libpq configurado em arquivo privado (`PGSERVICE`, `PGSERVICEFILE`,
`PGPASSFILE`), sem senha na linha de comando. Na janela autorizada:

Para uma base anterior à etapa 3, selecionar na lista abaixo apenas as tabelas
existentes confirmadas pelo inventário. Registrar explicitamente os objetos
ausentes; não criá-los para satisfazer o backup.

```bash
umask 077
pg_dump --format=custom --no-owner --no-privileges \
  --table=public.produtos --table=public.produto_aparicoes \
  --table=public.filtros --table=public.canais --table=public.bot_state \
  --table=public.oferta_eventos --table=public.oferta_midias --table=public.oferta_controle \
  --file="$BACKUP_DIR/dealbot-final.dump"
cp supabase/schema.sql "$BACKUP_DIR/schema-candidato.sql"
psql -X -v ON_ERROR_STOP=1 -f deploy/schema-inventario.sql > "$BACKUP_DIR/schema-inventario.txt"
pg_restore --list "$BACKUP_DIR/dealbot-final.dump" > "$BACKUP_DIR/dump-lista.txt"
```

O dump selecionado protege tabelas, relações, dados e sequências associadas; não é
backup integral de Auth, extensões, grants ou funções do projeto. Arquivar também
o schema/definições reais verificadas, grants inventariados e SHA, sobretudo se há
customizações além do candidato. Supabase continua responsável pelo datastore/Auth
gerenciado; confirmar cobertura/retenção da política de backup do provedor.

Ensaio de recuperação: em banco NOVO descartável, preparar os papéis/Auth mínimos
(fixture sintética em `backend/tests/sql-etapa3.local.sql` somente no laboratório),
restaurar o arquivo com `pg_restore --exit-on-error --no-owner --no-privileges`,
depois instalar/conferir os blocos compatíveis de funções/policies/grants.
Não usar `--clean`, reset ou restauração sobre o banco ativo. Comparar contagens,
IDs, hashes de dados, sequências, pins, gate e reservas antes de considerar recuperável.
`deploy/lab/sql-compose.sh` ensaia dump/restauração completos de uma base sintética.

**Objetos do bucket são uma cópia separada.** Dump SQL/backup de metadados não inclui
os bytes das fotos. Com CLI Supabase previamente configurada para o projeto correto,
exemplo de download somente leitura (confirmar flags na versão instalada):

```bash
supabase storage cp --experimental --remote="$SUPABASE_PROJECT_REF" \
  -r ss:///produtos/ "$BACKUP_DIR/bucket-produtos/" \
  > "$BACKUP_DIR/storage-copia.log" 2>&1
```

O log fica privado pois nomes de objetos podem ser sensíveis. Pode-se proteger uma
seleção conhecida em vez do bucket todo, mantendo mapa exato de bucket/chave e hash.
Não copiar apenas metadados ou URLs públicas esperando recuperar objetos apagados.
Testar leitura dos bytes exportados e recuperação em destino descartável, sem upload
no bucket produtivo. Exportação/restauração do Storage real não foi executada nesta entrega.

## 5. Schema: ordem e diagnóstico

Nenhum container aplica SQL. `deploy/schema-inventario.sql` usa transação read-only,
consulta colunas/constraints/índices/definições de funções/grants e agrega estado de
pins/reservas sem listar URLs ou textos. Não chama `oferta_legado_pronto`.

- **Base existente:** comparar com a base limpa da mesma release, inclusive definições
  de RPCs (não só nomes) e as correções de cópia/expiração. Selecionar os blocos
  necessários entre os marcadores `ETAPA 2 FILTROS` e `ETAPA 3 OFERTAS` do schema.
  Aplicar etapa 2 antes da 3, com coletores/limpadores antigos pausados.
- **Instalação limpa Supabase:** usar `supabase/schema.sql` completo em projeto novo
  após confirmar papéis/schemas gerenciados. Preencher canais/filtros conscientemente.
- Preservar índices textuais parciais de legado e numéricos separados, decisões,
  grafias, preços e tempos. Preflight incompatível significa parar e diagnosticar.
- Preservar `oferta_controle.legado_pronto`, pins e tombstones; não editar o gate
  para burlar o preflight. O bot registra referências legadas antes de liberar esse gate.
- Não executar upsert textual antigo nem restaurar definições antigas das RPCs.

As suítes ensaiam tipos/índices incompatíveis, dados legados, reaplicação, cópias,
expiração e concorrência. Isso não comprova configurações/extensões do Supabase real.

## 6. Virada — executar somente na janela aprovada

1. **Inventário/preflight:** concluir itens da seção 1; preparar imagens e rollback
   por SHA, ensaio Linux e referências dos backups. `dc config --quiet`.
2. **Pausa:** suspender limpeza antiga, parar coletor antigo e confirmar ausência
   de escritores no Railway/systemd/Compose/outro host. Usar OU Compose OU
   `bot/dealbot.service`, nunca ambos. Não mudar schema antes dessa confirmação.
3. **Backups finais:** SQLite, mídia, dados e objetos legados conforme seção 4.
   Registrar checkpoints recuperáveis e verificar restauração.
4. **Schema:** aplicar somente o necessário conforme seção 5; conferir definições/grants.
5. **API primeiro**, com `LIMPEZA_ATIVA=false` no arquivo de interpolação:

   ```bash
   dc up -d --no-deps api
   ```

   Rode a [pré-checagem com token](#token-da-pré-checagem) antes de seguir.
   Leituras do schema não substituem inventário de RPCs/grants. A CLI não grava
   nem dispara limpeza e tem prazo de 30 segundos. `/api/health` comprova apenas processo.
6. **Um bot:** `dc up -d --no-deps bot`. Conferir prontidão legada, snapshot válido
   de filtros/canais, ausência de conflito de lock e redução/progresso da fila.
   Filtros indisponíveis não equivalem a configuração vazia. Novas mídias locais,
   retries legados ainda no Supabase.
7. **Painel/proxy:** `dc up -d --no-deps painel`. Integrar o trecho ao Caddy existente,
   validar configuração completa e recarregar somente o supervisor inventariado.
   Confirmar DNS/TLS, login, sessão e smoke abaixo.
8. **Limpeza:** depois da prontidão e smoke, alterar `LIMPEZA_ATIVA=true` no arquivo
   de interpolação e executar `dc up -d --no-deps api`. Isso recria a API com a
   configuração nova; `restart` sozinho não atualiza envs.

O Compose não usa dependência que inicie o bot ao subir a API. Containers do bot
recebem SIGTERM e 90 s; o orçamento interno é 25 s e I/O/checkpoints são drenados.
API recebe 40 s e aguarda HTTP/ciclo de limpeza até prazo interno de 25 s.
Saúde degradada por si só não reinicia containers: observar causas antes de intervir.

### Token da pré-checagem

Use um **JWT de acesso válido do usuário do painel** do projeto testado, não a
chave `anon` ou `service_role`. Execute em terminal Bash privado e interativo
(Linux ou WSL no Windows), com `dc` já definido e a API em execução. O Compose
não copia automaticamente as variáveis do host para `exec`: `-e` com o **nome**
repassa explicitamente o valor exportado. Cole o JWT somente quando solicitado:

```bash
(
  set +x
  unset DEALBOT_PREFLIGHT_TOKEN
  IFS= read -rs -p 'JWT de acesso do painel: ' DEALBOT_PREFLIGHT_TOKEN || exit 1
  printf '\n' >&2
  [[ -n "$DEALBOT_PREFLIGHT_TOKEN" ]] || exit 1
  export DEALBOT_PREFLIGHT_TOKEN
  dc exec -T -e DEALBOT_PREFLIGHT_TOKEN api node src/preflight.js
)
```

`read -rs` não ecoa o valor; o subshell descarta a variável ao terminar. Não
grave essa credencial em arquivos, imagens, chat, histórico ou logs de depuração.
Não a exporte no shell pai nem a configure no ambiente permanente do serviço.

Para **diagnóstico parcial**, use `dc exec -T api node src/preflight.js` sem
`-e`. Resultado da CLI: **0** com token válido e checagens completas; **2** sem
token quando as demais checagens passaram (Auth **não** verificado); outro código
não zero quando falha, inclusive se o token for rejeitado. Só avance a virada com
resultado 0 e os demais requisitos da janela satisfeitos.

### Smoke HTTPS

- `/api/health` responde, rota de dados sem token retorna 401 e não expõe dados.
- Login real via Supabase e polling autenticado sem F5; sessão persiste ao recuperar
  indisponibilidade temporária de Auth. Não invalidar sessão por 503.
- Compra disponível antes da foto; depois WebP aparece no mesmo card em `/media/...`.
- Foto antiga Supabase aparece sem violação CSP; CORS corresponde à origem exata.
- Oferta repetida/retomada não duplica card/aparição; conferir reinício com fila pendente.
- Celular/desktop, filtros, cupom e links utilizáveis. Não imprimir JWT nas evidências.

## 7. Observação e manutenção

```bash
dc ps
dc logs --since 15m --tail 200 bot api
sh deploy/scripts/verificar-volumes.sh
```

Logs normais do bot/API usam eventos/IDs/contagens e erros saneados; antes de
compartilhar, revisar redaction. Não usar `docker inspect`/`printenv`, HTTP debug,
query de `raw_text`, dump de sessão ou logs de acesso com URLs privadas.
Acompanhar `estado_local`, fila/retries/compensações, idade do trabalho, falhas de
prontidão e ciclos de limpeza. Medir `df`, inodes e `du` diariamente no início;
definir alertas antes de 80% de disco e estimativa de dias restantes pelo crescimento.
Rotação de logs está no Compose. Não há eviction arbitrária de fotos em uso.

Atualização normal: repetir backup/prontidão, preparar novo SHA, subir em ordem e
recriar somente serviços afetados. Paths ficam fora das releases. Não incluir
remoção de volumes, `docker system prune --volumes` ou `down -v` nessas rotinas.

## 8. Rollback compatível

Gatilhos: falha de preflight/schema, loop de inicialização, fila sem progresso,
auth/polling/mídia persistentemente quebrados, erro de dedup/retomada ou falta de espaço.

1. Fixar `LIMPEZA_ATIVA=false`; recriar API sem limpeza e parar o bot se necessário.
   Se a API também está quebrada, pará-la para interromper novos ciclos.
2. Preservar estado, mídia, schema, pins e reservas. Registrar falha e backup atual.
3. Selecionar a release/imagens **já ensaiadas** de rollback, compatíveis com SQLite v7,
   identidade/RPCs atuais e mídia local. Apontar `COMPOSE_ARGS` e `DEALBOT_SHA` para ela.
4. `dc up -d --no-deps api`, conferir prontidão; depois `bot`, painel e smoke.
5. Reabilitar limpeza somente quando os contratos e a retomada estiverem confirmados.

Não reativar coletor monolítico, limpador antigo ou binário que não entenda v7/local.
Mudar o modo de escrita para Supabase não elimina a necessidade de servir/limpar
fotos locais existentes. Não reverter schema ou restaurar snapshot antigo por reflexo:
restauração é recuperação separada e pode perder eventos posteriores. Se nenhum
binário compatível estiver disponível, manter coletor/limpeza pausados e diagnosticar.

## 9. Reproduzir laboratório

Para uma demonstração manual sem ferramentas de teste no host, siga o
[guia local](uso-local.md#modo-a--demonstração-sem-credenciais). Os ensaios
automatizados abaixo usam apenas ambientes de teste separados.

Sem Docker, `deploy/lab/validar-local.py` copia fontes por allowlist para temporário
sem `.env`, compila standalone, inicia Caddy HTTPS local, API e pipeline com fronteiras
Telegram/Supabase falsas. Requer Python 3.12 com lock instalado, Node 24, Caddy e
Playwright/Chromium em caminhos absolutos. Ocupa somente portas locais 3000, 3333,
54329 e 18443 e recusa portas ocupadas. Não instala confiança da CA no sistema.

```bash
python -B deploy/lab/validar-local.py --base <TEMP_ABSOLUTO_EXISTENTE> \
  --node <NODE24_ABSOLUTO> --caddy <CADDY_ABSOLUTO> --playwright <PLAYWRIGHT_INDEX_MJS>
python -B -m unittest discover -s deploy/tests -v
```

Com Docker Linux disponível:

```bash
python -B deploy/lab/validar-compose.py --node <NODE24_ABSOLUTO> --playwright <PLAYWRIGHT_INDEX_MJS>
```

O runner cria projeto único, usa envs sintéticos, valida configuração/builds, testa
UID/GID, setgid, lock, `/proc/self/fd`, reserva/remoção, SIGTERM e recriação; executa
testes POSIX e SQL real. O único inicializador root prepara volumes de laboratório;
os processos de aplicação são não root. Ele para somente seu projeto e preserva
volumes/artefatos. Fotos/estado são sintéticos. O PostgreSQL e o Caddy desse arquivo
são exclusivos do laboratório e não devem ser usados como Compose de produção.

O mock HTTP não prova assinatura de JWT, Telegram, Supabase Auth/Storage reais ou
RPCs transacionais. Estas últimas têm suíte separada com Postgres real. O operador
deve concluir o smoke real autorizado durante a virada.
