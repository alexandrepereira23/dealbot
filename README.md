# Dealbot

Aplicação web de promoções. Um bot Python captura ofertas de canais do
Telegram, estrutura os dados por regex/heurística e salva no Supabase. Uma API
MVC em Node serve os dados, e um frontend Next.js exibe tudo com login, filtros
por categoria e edição das regras de captura.

```
Telegram → Inbox SQLite (VPS) → Bot Python → Supabase → API MVC (Node) → Next.js (Vercel)
                                              └→ Mídia separada → Supabase Storage
```

## Estrutura

```
dealbot/
├── supabase/schema.sql          # rode no SQL Editor do Supabase
│
├── backend/                     # API REST em camadas (MVC)
│   └── src/
│       ├── config/              # env + clientes Supabase
│       ├── models/              # acesso a dados (produto, filtro, canal)
│       ├── services/            # regras de negócio + validação (Zod)
│       ├── controllers/         # recebem req/res
│       ├── routes/              # rotas + auth aplicada
│       ├── middlewares/         # auth (JWT) e tratamento de erros
│       ├── utils/               # erros HTTP
│       ├── app.js               # monta express
│       └── server.js            # entrypoint
│
├── bot/                         # bot de captura (modo live/persistente)
│   ├── src/
│   │   ├── config.py            # variáveis de ambiente
│   │   ├── db.py                # cliente Supabase
│   │   ├── extractor.py         # estrutura texto via regex/heurística
│   │   ├── filters.py           # aplica as regras cadastradas
│   │   ├── repository.py        # gravação async + reconciliação/dedup
│   │   ├── estado.py            # inbox, fronteiras e mídia duráveis em SQLite
│   │   ├── pipeline.py          # workers limitados: oferta primeiro, foto depois
│   │   ├── recuperacao.py       # paginação de histórico + refresh de canais
│   │   ├── midia.py             # adaptador único de Supabase Storage
│   │   └── main.py              # loop de eventos do Telethon
│   ├── gerar_sessao.py          # gera a session string (rode 1x)
│   └── dealbot.service          # unit do systemd para o VPS
│
└── frontend/                    # Next.js (App Router)
    └── src/
        ├── app/
        │   ├── page.tsx         # dashboard (listagem + stats)
        │   ├── login/page.tsx   # login
        │   └── filtros/page.tsx # CRUD de filtros
        ├── components/          # Header, ProdutoCard, FiltroCategorias
        ├── hooks/useAuth.ts     # proteção de rota
        └── lib/                 # cliente Supabase, cliente da API, tipos
```

## Como a autenticação funciona

1. O usuário loga no frontend via Supabase Auth → recebe um JWT.
2. O frontend manda o JWT no header `Authorization: Bearer` em cada chamada.
3. O middleware `autenticar` do backend valida esse JWT no Supabase.
4. O backend acessa o banco com a `service_role key` (ignora o RLS).

A `service_role key` fica **só no backend e no bot**. A `anon key` fica no
frontend. Nunca troque as duas de lugar.

## Setup

### 1. Supabase
1. Crie um projeto em supabase.com
2. SQL Editor → cole e rode `supabase/schema.sql`
3. Settings → API: copie `URL`, `anon key` e `service_role key`

### 2. Seu usuário (acesso restrito a você)
1. Authentication → Providers → desative "Enable email signups"
2. Authentication → Users → "Add user" → crie seu e-mail e senha

### 3. Bot (no VPS Oracle)
```bash
cd bot
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python gerar_sessao.py          # informe API ID/HASH de my.telegram.org
cp .env.example .env            # preencha as variáveis
python -m src.main              # teste manual

# para rodar como serviço:
sudo install -m 644 dealbot.service /etc/systemd/system/dealbot.service
sudo systemctl enable --now dealbot
```
Cadastre os canais a monitorar na tabela `canais` do Supabase.

Use o Python **3.12** para reproduzir a verificação desta etapa. As dependências
diretas continuam fixadas em `bot/requirements.txt`; não rode `bot/bot.py`
(legado com Gemini). O serviço usa uma sessão já autorizada; não pede telefone
interativamente. Nada nesta entrega executa migração ou deploy em produção.

### Coleta durável e operação do bot

Antes de instalar/iniciar o serviço no ambiente escolhido, crie um diretório
privado **fora da pasta de deploy**, pertencente ao usuário do serviço:

```bash
install -d -m 700 /home/ubuntu/dealbot-state
```

Execute isso como o usuário `ubuntu` do exemplo, ou ajuste proprietário/caminhos
conforme seu ambiente. Defina `BOT_STATE_DIR` em `bot/.env`. Sem a variável, o
default é `~/.local/state/dealbot`. A unit de exemplo fixa
`/home/ubuntu/dealbot-state`; use o mesmo caminho em todas as inicializações.
Em container, monte esse diretório como **volume persistente** e conceda escrita
ao usuário do bot. Não use `/tmp`, diretório de build ou compartilhamento de
rede para SQLite. Preserve `inbox.sqlite3` e seus arquivos WAL/SHM: para backup,
pare o bot ou use a API de backup do SQLite; não copie só o arquivo principal
de um banco em uso. Estado contém textos e referências privadas de canais,
mas não credenciais/sessão. Não o publique nem versione.

O lock impede duas instâncias no mesmo diretório. **Não execute duas instâncias
do coletor com diretórios diferentes**: o lock não coordena processos distintos
nem oferece deduplicação distribuída. A inbox usa WAL, `synchronous=FULL`, um
executor SQLite serial e submissões limitadas. Falta de disco/erro local para
a coleta com log e saída não zero, preservando o marcador; o supervisor do
serviço pode reiniciar, mas não deve apagar/recriar o banco para ocultar o erro.

Recepção live e histórico compartilham `(ID numérico Telegram do canal, ID da
mensagem)`. O ID da linha em `canais` **não** é esse ID Telegram. Usernames e
referências de acesso são mantidos separadamente. A fronteira de coleta só
avança junto com uma página gravada, nunca pela chegada de uma mensagem live
mais nova. IDs podem ter lacunas. A conclusão de processamento é outro estado.

- **Primeiro uso sem marcador:** coleta somente as últimas
  `BOT_BOOTSTRAP_HORAS=24` horas; início e limite superior são fixados no estado
  para retomar o bootstrap sem janela móvel. Um canal vazio continua monitorado.
- **Depois:** startup, retorno de saúde da conexão (RPC de controle) e conferência
  a cada `BOT_RECUPERACAO_INTERVALO_S=60` percorrem o restante por páginas. Não há
  limite total de 50/100 mensagens. O lote limita uma rodada, não o backlog.
  Cada página faz uma única chamada pública `GetHistory` pelo Telethon, com no
  máximo 100 mensagens; não há continuação oculta do iterador. Respostas curtas
  não autorizam saltar até a mensagem mais nova: o prefixo é confirmado antes
  da próxima chamada/pacing. Fim é confirmado por resposta vazia ou pelo alcance
  comprovado do limite fixado. IDs apagados sem conteúdo não viram ofertas fictícias.
- **Prioridade:** até 4 escolhas live antes de dar oportunidade ao histórico
  elegível, com rodízio entre canais históricos. Pausa de 0,25s entre rodadas de
  recuperação; FloodWait/Retry-After prevalecem sobre o teto normal de backoff.
- **Configuração:** filtros a cada 15s e canais a cada 30s, sem reinício. Falha
  temporária preserva o último snapshot válido. Sem filtro carregado com sucesso,
  ofertas aguardam configuração; resposta válida sem filtros mantém “aceitar
  tudo”. Alterações valem para decisões futuras, não reavaliam descartes antigos.
  Canal desativado não recebe nova coleta, mas pendências aceitas continuam.
  Páginas em trânsito são conferidas contra a ativação atual antes do commit;
  desativar e reativar não autoriza aceitar uma página da ativação anterior.
  O retry de resolução também fica no SQLite por username normalizado, mesmo
  antes de conhecer o ID Telegram: reiniciar não encurta um FloodWait vigente.
  Um FloodWait recebido por chamada de uma ativação anterior também preserva
  seu prazo pelo ID estável, sem alterar a fronteira ou reativar o canal.
- **Oferta primeiro:** mantém extrator/filtros/hash atual e dedup de 48h. Salva
  oferta com foto nula antes de baixar/enviar mídia. Retry reconcilia produto e
  aparições por evento sem limitar a busca a 48h. Depois atualiza a foto pelo
  mesmo ID. Falha de foto não remove nem esconde oferta. Storage continua no
  Supabase, isolado em `midia.py`; não há armazenamento definitivo na VPS ainda.
  Se o upload foi confirmado e falha o vínculo da foto, o checkpoint continua
  recuperável até reconciliar a foto remota ou compensar o objeto conhecido.
  Foto já vinculada é preservada; falha permanente só terminaliza depois dessa
  conferência/compensação. Duplicatas mantêm a classificação também nos retries,
  sem alterar o hash ou a janela de 48h.
- **Retenção:** `BOT_RETENCAO_DIAS=7` vale para eventos inteiramente finalizados;
  uma drenagem começa a cada hora (`BOT_LIMPEZA_INTERVALO_S=3600`, também no startup).
  Cada ciclo executa até `BOT_LIMPEZA_MAX_LOTES=10` transações de no máximo
  `BOT_LIMPEZA_LOTE=100` eventos **e** 100 mídias, cedendo execução entre lotes.
  Se qualquer tabela encher seu último lote, retoma após
  `BOT_LIMPEZA_CONTINUACAO_S=1`, com o mesmo cutoff até esgotar os elegíveis;
  só então aguarda o intervalo normal e renova o cutoff. Um lote exatamente
  cheio pode causar uma consulta extra vazia. O orçamento limita lotes/registros,
  não garante prazo rígido de disco/SQLite. Lote aceita até 1000, ciclos até 100
  lotes e continuação até 60s; todos positivos/finitos, contagens inteiras.
  Não apaga pendências, retries, mídia ou
  compensações recuperáveis. Fronteiras/aliases são preservados. Essa retenção
  não muda a limpeza remota da API, por padrão 48h (`RETENCAO_HORAS`).

Todos os parâmetros e valores de exemplo estão em `bot/.env.example` e no
`.env.example` da raiz. Os principais limites são 4 workers de oferta, 1 de
mídia, 1 executor SQLite (`BOT_IO_WORKERS` aceita somente 1), buffer/página de
100, mídia até 10MiB, timeout remoto de 10s e de mídia de 30s. Intervalos e
valores devem ser positivos/finitos e o lote de recuperação não pode exceder o buffer. Não há
task de processamento por mensagem nem consulta de filtros por mensagem.

O transporte Telethon 1.36.0 usa despacho sequencial e uma fila de updates
limitada, com adaptação interna pequena coberta por teste de contrato. Overflow
é **visível**: desconecta a recepção, elimina apenas updates ainda não aceitos
e reconcilia pelo histórico. O limite conta pacotes de updates, não bytes; um
pacote/resposta Telegram e caches internos ainda têm custo próprio. Não é uma
promessa de memória em bytes constante sob qualquer resposta do Telegram.
Mudanças de versão exigem revalidar essa adaptação.

SIGTERM/SIGINT param recepção e tarefas auxiliares, aguardam workers por
`BOT_SHUTDOWN_TIMEOUT_S=25` e preservam o restante como retry. Esse orçamento limita
a espera antes de cancelar; devolver claims duravelmente e fechar recursos têm
custo adicional. A unit usa 60s de prazo total. O registro usa
`loop.add_signal_handler` onde suportado;
no Windows/fallback agenda via `loop.call_soon_threadsafe`, acordando o loop
mesmo ocioso. Instala na thread principal e restaura handlers ao sair. Se aumentar
timeouts/drenagem, ajuste `TimeoutStopSec`.
Interrupção forçada deixa claims para recuperação no startup. Para reverter a
versão, pare o processo, preserve o diretório e restaure o código desejado sem
apagar fila. O código anterior é live-only e não consumirá esse backlog; nunca
execute ambas as versões simultaneamente.

**Limites da garantia:** não é exactly-once. Mensagens apagadas antes da coleta,
canais sem acesso, perda do diretório persistente ou identidade histórica de
username desconhecida não podem ser recuperados por promessa de código. Sem
registros locais e remotos não há dedup ilimitada no tempo. Renomeações conhecidas
mantêm aliases; reassociação conhecida de username a outro ID é recusada.
Upload/atualização usam chave determinística e compensação de objetos conhecidos;
não há transação única com o limpador remoto. Sua corrida com anexação de foto
pode deixar órfão fora dos checkpoints observáveis; não prometemos zero órfãos
ou varredura geral destrutiva do bucket.

### Diagnóstico, testes e simulação (sem credenciais)

Logs são JSON, sem texto completo, tokens ou session string. No ambiente onde
o serviço estiver instalado, `journalctl -u dealbot -f` permite correlacionar
`canal_id`, `msg_id`, `produto_id`, `origem`, `tentativa`, `estado` e `proxima`:

- `oferta_descartada`: motivo `sem_produto` ou `filtro`;
- `mensagem_ignorada`: canal inativo ou geração encerrada antes da aceitação
  durável; trabalho já gravado permanece processável;
- `oferta_duplicata`/`oferta_disponivel`: efeito confirmado, antes de mídia;
- `trabalho_falhou`: classe oferta/mídia, motivo saneado e prazo de retry;
- `midia_concluida`: resultado da atualização da foto;
- `estado_local`: contagens por estado e idade da pendência mais antiga;
- `historico_registrado`, `historico_falhou`, `canal_indisponivel`,
  `telegram_indisponivel` e `recepcao_sobrecarga`: coleta/conexão/configuração.

`data_origem` é o horário Telegram; `recebido_em` é recepção local;
`disponibilizado_em` é confirmação local do efeito remoto. Não confunda idade
de histórico com latência local, e não inclua tempo de foto/renderização nela.
Para inspeção detalhada, use cópia consistente local do SQLite em modo somente
leitura; `eventos` contém estados/resultado/erros e `midias` o status por produto.
Não exponha os campos de texto ou access hash em relatórios públicos.

```bash
cd bot
# Suíte sem dependências de rede; contratos SDK são pulados se não instalados:
python -S -m unittest discover -s tests -v
# Com ambiente virtual/requirements instalados: inclui contratos SDK com HTTP fake.
python -m unittest discover -s tests -v
python -m pip check

# Referência: banco 100ms POR OPERAÇÃO, mídia 2000ms download+upload:
python -m simulacao --seed 42 --live 100 --historico 1000 --db-ms 100 --midia-ms 2000 --oferta-workers 4 --midia-workers 1
# Comparação com a mesma carga live, sem histórico:
python -m simulacao --seed 42 --live 100 --historico 0 --db-ms 100 --midia-ms 2000 --oferta-workers 4 --midia-workers 1
# Falha de mídia (nenhuma credencial ou recurso real):
python -m simulacao --seed 42 --live 100 --historico 1000 --db-ms 100 --midia-ms 2000 --midia-falha
```

Os testes usam SQLite temporário, Telegram/HTTP/Storage falsos; não leem `.env`
real. Testes de sinais de processo são POSIX e devem rodar em Linux local/WSL
(são pulados no Windows). A simulação usa cinco esperas lógicas de banco por
oferta distinta, seed e dataset verificáveis, e emite JSON com p50/p95/máximo
até confirmação da oferta (antes da aparição/foto), vazão, intervalo medido, fila inicial/pico/
final, workers máximos e atraso de heartbeat. Mede antes do shutdown, sem
esperar drenar fotos; instrumentação adiciona custo e amostras de resultados
crescem com o tamanho do cenário. **Não valida desempenho real da VPS, Telegram,
Supabase nem renderização do frontend.**

### 4. Backend
```bash
cd backend
npm install
cp .env.example .env            # preencha as variáveis
npm start                       # sobe na porta 3333
```

### 5. Frontend
```bash
cd frontend
npm install
cp .env.example .env.local      # preencha as variáveis
npm run dev                     # http://localhost:3000
```
Deploy no Vercel: defina as três variáveis `NEXT_PUBLIC_*` no painel.
A `NEXT_PUBLIC_API_URL` deve apontar para a URL pública do backend no VPS.

## Endpoints da API

Todas exigem `Authorization: Bearer <jwt>`, exceto `/health`.

```
GET    /api/health
GET    /api/produtos?categoria=eletronicos
GET    /api/produtos/estatisticas
GET    /api/produtos/:id
DELETE /api/produtos/:id
GET    /api/filtros
POST   /api/filtros
PUT    /api/filtros/:id
DELETE /api/filtros/:id
GET    /api/canais
POST   /api/canais
PUT    /api/canais/:id
DELETE /api/canais/:id
```

## Extração de produtos
O `bot/src/extractor.py` estrutura cada mensagem por regex/heurística (preço,
cupom, link, categoria por palavras-chave). Não há dependência de IA nem chave
externa. As categorias suportadas estão fixas em `extractor.py` e em
`frontend/lib/types.ts` (`CATEGORIAS`) — mantenha as duas em sincronia.
