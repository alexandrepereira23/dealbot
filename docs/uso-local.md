# Execução local do Dealbot

[Visão geral](../README.md) · [Testes](testes.md) · [Implantação em VPS](deploy-vps.md)

Use Docker Engine com Compose v2.30+ no Linux ou Docker Desktop em modo Linux
com WSL 2 no Windows. Execute os comandos na **raiz do checkout**. Os blocos com
`dc()`, `umask` ou `read` usam Bash: no Windows, abra sua distribuição WSL com a
integração Docker Desktop habilitada. As linhas individuais `docker compose`
também funcionam no PowerShell. Use o mesmo contexto Docker do início ao fim.
Prefira Docker Engine 28 ou mais recente: versões anteriores têm uma limitação
conhecida no isolamento de portas publicadas em loopback na mesma rede local.

## Modo A — demonstração sem credenciais

O laboratório sobe o painel, a API, um coletor com entrada sintética e um mock
do Supabase. Não exige arquivos `.env`, uma conta Supabase ou uma sessão Telegram.
O mock HTTP escuta em `127.0.0.1:54329` para o login sintético do navegador.

Na raiz do repositório:

```sh
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml config --quiet
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml up -d --build
```

Instale a [CA do laboratório](#certificado-https-local) e abra
<https://localhost:18443>. Use o login **`lab@example.invalid`** e a senha
**`laboratorio123`**, que só funcionam na demonstração.

Gere uma oferta de teste. Com a aba visível, aguarde a atualização do painel:
o card deve aparecer antes da foto. O botão **Copiar cupom** deve copiar `LAB10`.

```sh
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml exec -T supabase node /lab/controle.mjs oferta
```

Em seguida, libere a foto. Ela deve aparecer no mesmo card sem recarregar a página.

```sh
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml exec -T supabase node /lab/controle.mjs foto
```

Para inspecionar os serviços ou encerrar a demonstração:

```sh
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml ps
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml logs --tail 50 bot api
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml stop
```

`stop` preserva a fila, as imagens e os dados sintéticos do mock. Não reutilize
esses volumes no projeto `dealbot-local`.

## Modo B — uso real no computador

Painel, API e bot usam as imagens de aplicação da VPS. O Caddy **deste** projeto
publica em loopback, sem DNS público nem rede externa pré-existente. Painel,
`/api` e `/media` têm uma única origem: <https://localhost:28443> por padrão.
Supabase gerenciado e Telegram exigem internet. Para coleta contínua, mantenha o
computador ligado, sem suspender, com o daemon e os containers em execução.

### Supabase e usuário do painel

1. Prefira um **projeto de teste separado**, sem dados existentes. Confirme a URL,
   a chave pública `anon` e a chave privada `service_role` do mesmo projeto.
   Em **Settings → API Keys → Legacy API Keys**, use `service_role` para o
   coletor: a versão instalada do SDK Python exige uma chave no formato JWT e
   não aceita `sb_secret_…`.
2. Em **projeto novo**, revise e aplique manualmente [`supabase/schema.sql`](../supabase/schema.sql)
   no SQL Editor desse projeto. Em **projeto existente**, faça antes o
   [inventário e backup](deploy-vps.md#4-backup-consistente-e-restauração-ensaiada)
   e siga a [ordem controlada de atualização de schema](deploy-vps.md#5-schema-ordem-e-diagnóstico),
   com escritores/limpadores antigos pausados e revisão das RPCs, índices e
   permissões. Não rode o schema completo às cegas sobre dados existentes.
   Nenhum container aplica SQL automaticamente.
3. Confirme que a **Data API** está habilitada. Se a concessão automática de
   privilégios estiver desativada, revise as permissões no SQL Editor. Caso
   faltem os privilégios abaixo, conceda-os apenas ao papel `service_role`:

   ```sql
   grant select on table public.canais to service_role;
   grant select, insert, update, delete on table public.filtros to service_role;
   ```

   Não desative RLS nem conceda acesso a `anon` para resolver uma falha do bot ou
   da API. Valide os acessos do projeto na pré-checagem.
4. Em **Authentication → Users**, crie o usuário do painel; para um ambiente
   restrito, desative novos cadastros públicos e revise a URL e os redirects de
   Auth se o método de login os usa. Use uma senha própria, não a do laboratório.
   A sessão de login do painel é um JWT Supabase, não a sessão do Telegram.

Usar o painel real pode escrever no projeto escolhido (por exemplo, ao editar
regras ou excluir ofertas). Mantenha a limpeza automática suspensa durante a
preparação e o primeiro smoke.

### Arquivos de configuração

Crie os arquivos abaixo uma vez. `cp -n` evita sobrescrever arquivos existentes.
Edite-os localmente e não os versione, publique ou cole em chat. No Windows,
proteja o diretório com permissões/ACLs do seu usuário; `chmod` em NTFS não
substitui essa proteção. O Compose proporciona isolamento, não um cofre de segredos:
quem administra o daemon pode ler o ambiente dos containers.

```bash
umask 077
cp -n deploy/env/local.env.example deploy/env/local.env
cp -n deploy/env/api.env.example deploy/env/api-local.env
cp -n deploy/env/bot.env.example deploy/env/bot-local.env
chmod 600 deploy/env/local.env deploy/env/api-local.env deploy/env/bot-local.env
```

| Arquivo | Variáveis |
| --- | --- |
| `deploy/env/local.env` | `NEXT_PUBLIC_SUPABASE_URL` e `NEXT_PUBLIC_SUPABASE_ANON_KEY` são valores **públicos** do build. `NEXT_PUBLIC_POLLING_LISTA_MS` (5000) e `NEXT_PUBLIC_POLLING_STATS_MS` (30000) definem os intervalos. `LOCAL_HTTPS_PORT` (28443) é a porta HTTPS em loopback. `API_ENV_FILE` (`./env/api-local.env`) e `BOT_ENV_FILE` (`./env/bot-local.env`) são caminhos relativos ao YAML em `deploy/`, não à raiz do checkout. |
| `deploy/env/local.env` (operação) | `DEALBOT_SHA=local` é a tag das imagens; mantenha-a separada das tags da VPS e de `lab`. IDs Linux: `BOT_UID=10001`, `API_UID=10002`, `FRONTEND_UID=10003`, `MEDIA_GID=10000`. `MIDIA_SAIDA_MAX_BYTES=358400` limita o tamanho de cada WebP final. Mantenha `LIMPEZA_ATIVA=false` antes da pré-checagem e da validação. |
| `deploy/env/api-local.env` | `SUPABASE_URL`, `SUPABASE_ANON_KEY` e `SUPABASE_SERVICE_KEY` do mesmo projeto. Defina **`CORS_ORIGIN=https://localhost:28443`**, sem barra final. `RETENCAO_HORAS` (48), `RETENCAO_DIAS` (7), `LIMPEZA_INTERVALO_MIN` (60), `LIMPEZA_LOTE` (100) e `LIMPEZA_MAX_LOTES` (10) controlam a limpeza quando habilitada. |
| `deploy/env/bot-local.env` | Apenas para coletar: `TG_API_ID`, `TG_API_HASH`, `TG_SESSION_STRING`, `SUPABASE_URL` e `SUPABASE_SERVICE_KEY`. `BOT_RETENCAO_DIAS` (7), `BOT_OFERTA_WORKERS` (4), `BOT_MIDIA_WORKERS` (1), `BOT_IO_WORKERS` (1) e `BOT_MIDIA_TRANSFORM_WORKERS` (1) podem ficar como no exemplo. Outros ajustes de runtime estão em [`bot/.env.example`](../bot/.env.example). |

O exemplo local registra os valores de interpolação Docker; não coloque nele
`SUPABASE_SERVICE_KEY` nem variáveis `TG_*`. Variáveis `NEXT_PUBLIC_*` são
gravadas no build do painel; recompile se mudar a URL, chave pública ou polling.
`NEXT_PUBLIC_API_URL=/api`, os paths internos dos volumes e o modo de mídia local
são controlados pelo Compose. A API, e não o painel, usa a `service_role` para
consultar o banco após validar o JWT do usuário. Os arquivos privados são lidos
em formato `raw`: mantenha os valores literais, sem aspas de shell.
`/media/<chave>.webp` é leitura pública sem listagem, sob a origem local; não
trate o nome aleatório do arquivo como controle de acesso.

### Subir o painel sem coletar

No Bash, use este atalho na raiz do checkout. `-p dealbot-local` fixa o projeto
mesmo que o shell possua `COMPOSE_PROJECT_NAME`:

```bash
dc() { docker compose -p dealbot-local --env-file deploy/env/local.env -f deploy/compose.local.yaml "$@"; }

dc config --quiet
dc build api painel
dc up -d api painel caddy
dc ps
dc logs -f api painel caddy
```

Saia do acompanhamento dos logs com `Ctrl+C` (isso não para os containers).
[Confie na CA deste projeto](#certificado-https-local) e abra <https://localhost:28443>.
Confira também <https://localhost:28443/api/health>. Saúde comprova o processo,
não o schema nem o Auth. Para a CLI de pré-checagem, mantenha a limpeza suspensa
e use o [bloco Bash do guia de VPS](deploy-vps.md#token-da-pré-checagem), com o
`dc` **local** definido acima. Valide o login com seu usuário do Supabase.

Se alterar `LOCAL_HTTPS_PORT`, atualize **também** `CORS_ORIGIN` em
`api-local.env`, a URL que abre no navegador e os redirects de Auth relevantes.
Use `https://localhost:<porta>` nos três pontos. Mudar envs pede `up`, não apenas
`restart`. Para reconstruir painel/API sem iniciar a coleta:

```bash
dc config --quiet
dc up -d --build --force-recreate api painel caddy
```

### Habilitar a coleta Telegram (opcional)

Descubra o API ID/hash da sua aplicação em <https://my.telegram.org/>. Gere uma
sessão Telethon localmente usando [`bot/gerar_sessao.py`](../bot/gerar_sessao.py)
uma vez em terminal **privado**. O script solicita autenticação Telegram e mostra
a string da sessão no próprio terminal: não grave a saída, não tire capturas e
copie o valor somente para `TG_SESSION_STRING` em `bot-local.env`. Se usar Python
no host, use Python 3.12 com o ambiente virtual do bot e `requirements.txt`.

Para gerar a sessão pelo Docker, sem iniciar o coletor:

```bash
dc --profile coleta build bot
dc run --rm --no-deps --entrypoint python \
  --volume "$PWD/bot/gerar_sessao.py:/gerar_sessao.py:ro" bot /gerar_sessao.py
```

Cadastre em `canais` apenas os canais autorizados que sua conta consegue ler,
ative os desejados e revise os filtros. Antes de iniciar, confirme que não há
outro coletor real em Railway, VPS, systemd, Docker ou outro computador. O lock
do SQLite só impede dois processos no **mesmo** estado local; não coordena hosts.

O serviço `bot` pertence ao perfil `coleta`. Só execute `up -d bot` depois de
preencher as credenciais e autorizar a coleta:

```bash
dc --profile coleta config --quiet
dc --profile coleta build bot
dc up -d bot
dc --profile coleta logs -f bot
```

O primeiro uso sem marcador pode recuperar histórico conforme `BOT_BOOTSTRAP_HORAS`
(24 por padrão). Nos demais, a fila e os checkpoints permitem retomar. Para parar
somente a coleta, `dc --profile coleta stop bot`; para parar tudo,
`dc --profile coleta stop`. Após parar o projeto, use `dc up -d api painel caddy`
e, só quando quiser a coleta novamente, `dc up -d bot`. Não habilite `coleta` em
`COMPOSE_PROFILES` por padrão.

## Certificado HTTPS local

Cada projeto tem seu próprio Caddy e sua própria CA de desenvolvimento. HTTPS
confiável fornece o contexto seguro usado pelo botão **Copiar cupom**. O Compose
**não** instala certificados no host. Após a primeira subida, espere o Caddy
inicializar e exporte **somente o certificado público da CA** correspondente ao
projeto. Na raiz do checkout:

```sh
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt ./dealbot-lab-ca.crt
docker compose -p dealbot-local --env-file deploy/env/local.env -f deploy/compose.local.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt ./dealbot-local-ca.crt
```

Execute apenas a linha do modo em uso. Confirme que o arquivo veio do seu Caddy;
instale manualmente no perfil de navegador de testes (por exemplo, Firefox →
**Privacidade e Segurança → Certificados → Ver certificados → Autoridades →
Importar**), ou no repositório **do seu usuário** quando o navegador usa o sistema
(por exemplo, **Usuário Atual → Autoridades de Certificação Raiz Confiáveis** no
Windows). Prefira o menor escopo disponível. Se o navegador roda no Windows, é
nele que a raiz precisa ser confiável, ainda que o Docker rode via WSL. Reabra o
navegador e confira que `https://localhost:<porta>` não exibe alerta. Não use
ignorar erros TLS como instrução de uso. Não exporte a chave privada da CA nem
adicione o `.crt` ao Git; remova a confiança quando parar de usar o projeto.

## Persistência e backup

No modo B, os volumes nomeados `estado`, `midia`, `caddy_data` e `backups` pertencem
a `dealbot-local`. O SQLite e seu WAL/lock ficam em `estado`, armazenamento Linux
administrado pelo Docker, **não** em bind mount NTFS, SMB/NFS ou pasta sincronizada.
`midia` guarda as fotos WebP locais. `caddy_data` preserva a CA; se o volume for
trocado, exporte a nova CA e retire a antiga da confiança. `backups` é apenas uma
área de trabalho; copie o backup para fora do Docker para resistir à perda dele.

O inicializador prepara apenas as raízes dedicadas; estado privado `0700` do bot,
mídia setgid `2770` com dono bot e grupo compartilhado, finais `0640`. A API não
monta o SQLite. `stop`, `down` **sem** `-v` e recriação mantêm os volumes. Apagar
os volumes (incluindo `down -v` ou prune de volumes) perde os dados locais: fila,
checkpoints, mídia e CA. Isso não apaga tabelas Supabase e pode deixar referências
remotas a fotos ausentes. O modo A tem volumes separados; não restaure dados reais
no laboratório.

Se o inicializador recusar um volume antigo **não vazio**, pare os serviços,
faça backup e confira dono/grupo dos arquivos antes de qualquer ajuste. Se só as
raízes dedicadas estiverem divergentes (por exemplo, mídia criada com dono
`root`), execute `dc run --rm preparar --ajustar-raizes`. No laboratório, use
`docker compose -f deploy/lab/compose.yaml run --rm preparar --ajustar-raizes`
com o mesmo projeto da subida. Isso não muda o conteúdo dos volumes; trocar
UID/GID de arquivos existentes exige migração controlada, não `chown -R`.

Se customizar IDs, defina-os antes do primeiro uso e mantenha-os no build e
runtime. O inicializador recusa volumes **não vazios** com IDs/modos divergentes;
não force mudança de IDs sobre uma instalação com dados sem backup e revisão.

### Backup e exportação no modo B

Para um conjunto consistente de estado e fotos, pare o bot e suspenda a limpeza
da API (ou pare a API), sem outro escritor/limpador conectado ao mesmo projeto.
A API de backup do SQLite lê um banco em WAL; não copie só `inbox.sqlite3` em
uso. O exemplo pressupõe estado já inicializado pelo bot, volumes preparados e
imagem do bot construída. Escolha nomes inéditos no volume de backup. Com `dc`
definido como acima, os comandos `run` trocam o entrypoint por uma ferramenta
local: **não iniciam a coleta** e `--no-deps` não sobe serviços associados.

```bash
dc --profile coleta stop bot api
dc run --rm --no-deps --entrypoint python bot /scripts/backup-sqlite.py \
  backup /data/state/inbox.sqlite3 /backup/inbox-local.sqlite3
dc run --rm --no-deps --entrypoint python bot /scripts/backup-sqlite.py \
  verify /backup/inbox-local.sqlite3
dc run --rm --no-deps -T --entrypoint python bot - <<'PY'
import os
import tarfile

os.umask(0o077)
with tarfile.open('/backup/media-local.tar.gz', 'x:gz') as arquivo:
    arquivo.add('/data/media', arcname='media')
PY
```

Exporte os três arquivos para um diretório **novo e privado fora do checkout**.
Use Bash Linux/WSL para preservar os bytes da saída. Não compartilhe os dados:
as cópias podem conter mensagens, referências privadas e fotos.

```bash
(
  set -eC
  umask 077
  destino=$(mktemp -d "$HOME/dealbot-backup.XXXXXX")
  for arquivo in inbox-local.sqlite3 inbox-local.sqlite3.manifest.json media-local.tar.gz; do
    dc run --rm --no-deps -T --entrypoint cat bot "/backup/$arquivo" > "$destino/$arquivo"
  done
  cd "$destino"
  sha256sum inbox-local.sqlite3 inbox-local.sqlite3.manifest.json media-local.tar.gz > arquivos.sha256
  printf 'Backup exportado para %s\n' "$destino"
)
```

Conserve a cópia privada fora do host e verifique `sha256sum -c arquivos.sha256`
após transferir. O `restore` da helper exige diretório novo; não sobrescreva o
volume ativo. Para ensaiar com o backup ainda no volume:

```bash
dc run --rm --no-deps --entrypoint python bot /scripts/backup-sqlite.py \
  restore /backup/inbox-local.sqlite3 /backup/ensaio-estado-novo
```

Para restaurar em operação, planeje a troca com o bot parado e ensaie a leitura
das fotos em destino descartável. O backup local **não** inclui as tabelas ou
fotos legadas do Supabase: exporte-as separadamente pelo
[roteiro de backup de dados e objetos](deploy-vps.md#dados-supabase-e-objetos-legados).

## Solução de problemas

| Sintoma | Confira |
| --- | --- |
| Docker não conecta | `docker info`, engine Linux, integração WSL e contexto Docker. |
| Porta ocupada | Identifique o dono da porta. A usa 18443 e 54329 fixas; em B, mude `LOCAL_HTTPS_PORT` **e** a origem da API. Não abra portas na LAN. |
| Erro de certificado ou falha de cópia | Use `localhost` e a CA do projeto correto, em um navegador que confie nela. Clique no botão com a aba ativa; não contorne erro TLS. |
| Login/API falha | Verifique a origem, a URL e as chaves do mesmo Supabase; confirme acesso de rede e schema. `401` indica credencial ausente/rejeitada; `503` transitório do Auth não deve forçar novo login. |
| Erro `42501` ao ler ou gravar | Confira se `SUPABASE_SERVICE_KEY` não contém a chave `anon`. Se a chave privada estiver correta, confira os privilégios da tabela no [Supabase](#supabase-e-usuário-do-painel). |
| `Origem não permitida` ao salvar um filtro | Defina `CORS_ORIGIN` com o endereço exato do painel (por padrão, `https://localhost:28443`, sem barra final) e recrie a API com `dc up -d --no-deps --force-recreate api`. |
| Ofertas reais aparecem sem foto | Se a mensagem tiver foto, ela é processada em segundo plano. Na primeira coleta, o histórico pode aumentar a fila; acompanhe `midia_concluida` nos logs do bot. |
| Card sintético sem foto | Depois de observar a oferta, rode `foto`. Mantenha a aba visível por um ciclo de polling e veja logs de `bot`, `api` e `supabase`. |
| Falha de permissão ou lock | Consulte logs do inicializador e do bot. Confirme dono da raiz de mídia e ausência de segundo coletor. Não apague o lock/SQLite nem use `0777`, permissões extras ou `chown -R`. |

Compartilhe apenas diagnósticos revisados: não imprima ambiente resolvido,
headers de autenticação, textos de canais, URLs privadas ou a sessão Telegram.
