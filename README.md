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

- `oferta_descartada`: diagnóstico local com motivo de extração ou rejeições por
  regra; `oferta_decidida` identifica o aceite antes do primeiro efeito remoto;
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

Se um teste assíncrono exceder seu watchdog, não aumente o prazo nem desabilite
o modo debug para obter verde. Separe fila/execução SQLite de retorno ao loop
e verifique estados/fatalidade dos workers. No WSL, confirme o filesystem de
cada parte: a inbox temporária pode estar em ext4 enquanto fontes/venv em
`/mnt/c` usam 9p. A captura de stacks do debug consulta metadados das fontes;
um perfil local encontrou custo dominante em `linecache.checkcache`/`stat`,
não na execução SQL. Isso não prova a causa de todo timeout: preserve a falha,
registre o ambiente e use controles de agendamento, sem mudar `WAL`/`FULL`,
assertions ou dados para mascará-la. Evidências e limites constam no PRD da etapa 2.
Na etapa 3, controles base/atual também localizaram caudas no COMMIT (até2,546s
na base), além do custo de `stat` com fontes9p. Para verificação POSIX, prefira
fontes e temporários no filesystem Linux do WSL, com Python3.12/requirements;
confira hashes se usar snapshot, copiando apenas código/fixtures, nunca `.env`,
sessões ou estado privado. Execute em `bot/` o mesmo comando completo acima,
sem sondas e mantendo debug, watchdogs e WAL/FULL intactos. Registre falhas anteriores
e o filesystem de fontes/venv/temporários: uma execução rápida não elimina caudas
de sincronização, e um teste lento não autoriza atribuir regressão sem controles.
Não reinicie/reconfigure WSL/Windows nem mude durabilidade para testar essa hipótese.
Os controles de refresh em `python -m unittest tests.test_progresso_configuracao -v`
usam barreiras de eventos, dois workers e SQLite real para exercitar janelas de
notificação/SELECT/commit. Não reproduzem nem explicam o timeout histórico.

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

### Etapa 2: extração contextual e regras previsíveis

O título é a linha descritiva do produto, não a primeira chamada promocional.
Marca/modelo/capacidade e variantes após hífens são preservados. Filtros e
categorias usam o **conteúdo descritivo completo**, sem URLs, códigos de cupom
ou rodapés identificados de divulgação. Caixa, acentos e espaços são
normalizados; palavras/frases usam limites de palavras, sem fuzzy amplo.
Uma frase deve aparecer junta: `memória ram` não equivale a termos espalhados.

Regras ativas têm dois tipos:

- **`interesse`** (default legado): basta passar em uma regra. Dentro dela,
  categoria, teto e palavras são condições combinadas. `modo_palavras` é
  `qualquer` (default legado) ou `todas`. Palavras-chave vazias não restringem.
  Bloqueios da regra continuam por **qualquer termo e somente naquela regra**,
  independentemente do modo de inclusão; outro interesse pode aceitar.
- **`bloqueio_global`**: avaliado antes de interesses, veta sem que outro
  interesse possa autorizar. Lista de bloqueios deve ser não vazia; o modo
  qualquer/todas aplica-se a ela. Inclusões devem estar vazias, categoria/teto
  nulos. API rejeita combinações incompatíveis; a tela explica e limpa os
  campos inaplicáveis ao trocar o tipo.

Sem interesses ativos, ofertas válidas passam se nenhum global vetar. Sem
regras ativas, ofertas válidas passam. Isso **não** transforma falha de
configuração em lista vazia: sem snapshot válido, aguarda; erro posterior
preserva o último válido e sua idade. Mudanças valem só para decisões futuras.
Editar conteúdo de regra pausada não a ativa; PUT parcial preserva omitidos,
enquanto `null`/`[]` explicitamente removem a condição permitida.

API valida as sete categorias (não `todos`), enums, nome 1–100 caracteres,
até 50 entradas por lista, termos/frases de 1–100 caracteres após trim e
duplicatas normalizadas. Teto aceita número finito de 0 a 99.999.999,99,
com até dois decimais. Campo omitido é diferente de zero. Preço desconhecido
rejeita somente a regra com teto, com `preco_desconhecido`; outra sem teto
pode aceitar. Zero explícito/gratuidade identificada é conhecido, não ausente.

#### Dinheiro, links, cupons e limitações

- Atual/final/à vista explícito tem precedência; anterior exige marcador
  como `de`/`antes`. Frete, parcela, valor de desconto e compra mínima não são
  preço atual/anterior. Não se deriva total de parcelas nesta versão.
- `De R$ 399,90 por R$ 299,90` → 299,90/399,90; `Por R$ 299,90 / Frete
  R$ 15,00` → 299,90/anterior ausente; `10x de R$ 99,90 / à vista R$ 899,00`
  → 899,00. Desconto/compra mínima ou `20% OFF` isolados não fornecem preço.
- Condição/modelo após preço inline continuam descritivos: `SSD R$ 299,90 -
  USADO` permanece sujeito ao veto de usado. Frete com `de`/`por` e pontuação
  (`Frete: grátis`, `Frete – grátis`) não fornece preço atual/anterior do produto.
  Na descrição, remove-se o serviço reconhecido, não a condição que o segue:
  `Frete incluso, USADO` também preserva o veto de usado.
- Formatos brasileiros: `R$ 1.234,56`, `R$ 299,90`, `R$ 299` e espaços
  não separáveis; `R$ 1.234` significa 1234,00 por agrupamento brasileiro.
  `R$ 1,234`, `R$ 12.34` ou separadores inválidos ficam desconhecidos e
  explicados. Comparações internas usam centavos; JSON/API continuam number/null.
- Só links públicos HTTP/HTTPS: candidatos do texto, entidades e botões são
  capturados sem nova consulta de enriquecimento. Links comerciais/contextuais
  vencem divulgação de grupo/rede social; encurtados são mantidos sem redirects.
  Caixa do caminho/query e parâmetros legítimos são preservados.
- Cupom exige evidência contextual, como `Use o cupom: AbC123`; preserva a
  grafia. Backticks ou `DESCONTO` isolados não fabricam cupom. Cupom ambíguo
  permanece nulo sem invalidar uma oferta independente.
- Mensagens curtas podem ser ofertas; divulgação genérica não é produto.
  Múltiplos produtos/preços independentes detectados são ambíguos: não escolher
  o menor. Mantém-se **uma oferta por mensagem**, sem cobertura completa de
  listas, álbuns ou edições.
- Mudança de linha/especificação não prova segundo produto: `Capacidade 1 TB`
  e um campo simples `Memória RAM 16 GB` entre valores do notebook continuam
  sua descrição. Identificação própria, como `Memória RAM 16 GB Kingston Fury`
  seguida de preço, ou marca antes de outro objeto (`Logitech Headset`), é
  evidência de oferta independente. Essas heurísticas locais não prometem
  reconhecer toda especificação/formato possível; conflitos não viram menor preço.
- Dois objetos com preços próprios separados por cláusulas na mesma linha
  também são múltiplos: `SSD R$ 350 / Headset por R$ 149` não gera um card
  composto. Relações de/por, parcelas e frete do mesmo produto não criam objetos.
  Campos rotulados do notebook, como `Processador: Intel Core i5`, sem preço
  próprio, continuam especificação. Frete/parcela/anterior dentro do campo não
  é preço próprio; memória com marca/modelo residual e preço seguinte continua
  oferta independente, mesmo escrita com dois-pontos.
- Cadeira gamer é casa, headset gamer é eletrônico e jogo PS5 é games;
  incerteza vira outros. Há ponto de extensão por ID/username de canal, mas
  nenhum formato específico foi inventado: exemplos/testes são **sintéticos**.
- Deduplicação/hash e janela de 48h continuam os mesmos. O hash antigo ainda
  normaliza a caixa da URL e possui outras limitações de identidade; corrigir
  isso, resolver redirects e produto canônico pertencem à etapa 3. Não há
  recálculo histórico, reabertura em massa ou nova avaliação de decisão congelada.

#### Prévia offline e diagnóstico

Em `bot/`, sem `.env`, tokens, Supabase ou Telegram reais:

```bash
python -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json
python -m medir_extracao
python -m medir_extracao --limites  # também 10 regras, 50 termos por lista, 100 caracteres
python -m unittest tests.test_filtros_etapa2 tests.test_decisoes_etapa2 -v
```

Os arquivos de exemplo acima são sintéticos. Prévia usa a mesma extração e
avaliação dos workers, retorna JSON com produto, descrição de avaliação,
aceite e motivos. Código de saída: 0 para avaliação válida (inclusive rejeição),
2 para entrada/configuração inválida e 1 para falha técnica. Ela deliberadamente
mostra os dados locais fornecidos: não publique sua saída com mensagens privadas.
O benchmark de corpus mede CPU/local, não latência real de Telegram/lojas/VPS.

`--contexto arquivo.json` é opcional. Formato normalizado: `versao: 1`,
`links: [{url, origem: "entidade" | "botao", rotulo, offset?, length?}]`,
`codigos: [{offset, length}]`, `exclusoes: [{offset, length}]`; admite
`canal_id` inteiro e `username` para seleção do adaptador. Esses offsets são
índices **Python no texto bruto**; a fronteira Telethon converte UTF-16 usando
o SDK, inclusive com emoji antes da entidade. Não use offsets do `.text`
formatado. Envelopes antigos sem contexto continuam legíveis, sem refetch.

Diagnóstico local registra códigos/IDs de regras e razões por regra:
`aceita_por_regra`, `bloqueio_global`, `bloqueio_da_regra`, `palavra_ausente`,
`categoria_divergente`, `preco_acima_do_limite`, `preco_desconhecido`,
`preco_ambiguo`, `sem_evidencia_de_oferta` e situações específicas de extração.
Logs não contêm texto/código/termos privados nem URLs completas. Descrição,
candidatos e diagnóstico não são colunas remotas: há projeção explícita de
campos de produto. Aprovação e diagnóstico são congelados antes da rede;
descarte legítimo/ambiguidade terminaliza sem retries infinitos.

#### Migrações e atualização futura — não aplicadas remotamente

1. Preservar backup consistente do estado SQLite e conferir dados/schema.
   O script `supabase/schema.sql` contém o bloco aditivo da etapa 2: novos
   campos de filtros, defaults e constraints. Não basta `CREATE TABLE IF NOT
   EXISTS` para atualizar banco antigo. Legado incompatível exige diagnóstico
   e correção autorizada, nunca apagamento/reinterpretação automática.
2. Parar o coletor antigo e, em operação futura explicitamente autorizada,
   aplicar primeiro o bloco SQL da etapa 2. Esta entrega só prepara/testa
   localmente o SQL: **não o executa no Supabase**.
3. Atualizar backend e bot antes de habilitar a nova UI. Startup do bot migra
   SQLite aditivamente para v5; não trocar/apagar `BOT_STATE_DIR`. IDs, pendências,
   decisões/hash, mídia e fronteiras são preservados. Decisões existentes
   continuam sendo reconciliadas sem reextração, mesmo sem configuração nova.
4. Só então atualizar frontend e conferir CRUD/tipos/modos/pausados. Não manter
   bot antigo lendo bloqueio global como se fosse interesse permissivo.
5. Schema incompleto produz erro explícito (API) e refresh inválido (bot), sem
   fingir sucesso ou descartar novos campos. Sem snapshot válido aguarda; com
   snapshot válido conserva o último. Consultas exigem as novas colunas.

Rollback: parar coletor, preservar os dados e usar versão compatível. Colunas
aditivas podem permanecer, mas o stack antigo ignora globais/`todas`; voltar
a ele com essas regras é inseguro. Não desativar vetos nem apagar fila para
reverter. Código antigo pode recusar SQLite v5; restauração consistente exige
decisão própria e perde eventos posteriores ao backup. Nunca iniciar dois
coletores. Sem deploy/migração remota automática.

Verificações locais adicionais:

```bash
# Em backend/ (Node; sem Supabase real)
npm test
# Requer psql e banco LOCAL DESCARTÁVEL vazio, com nome protegido pelo runner:
DEALBOT_TEST_POSTGRES_URL=postgresql://localhost:5432/dealbot_teste npm run test:sql
# Alternativa: PGlite instalado fora do projeto, instância Postgres em memória:
DEALBOT_TEST_PGLITE_MODULE=/caminho/absoluto/node_modules/@electric-sql/pglite/dist/index.js npm run test:sql

# Em frontend/ (API/Auth e hooks falsos, componente real renderizado; não é browser E2E)
npm test
npm run lint
npx --no-install tsc --noEmit --incremental false
npm run build
```

Use somente um dos dois modos SQL. O runner recusa URL remota, parâmetros e
nome de banco não protegido; transações com rollback preservam o ambiente de
teste. A execução desta entrega usou PostgreSQL 18.6/PGlite 0.5.11 temporário;
não valida extensões/RLS/infraestrutura do Supabase real. PGlite não é dependência
de produção. No build, usar variáveis `NEXT_PUBLIC_*` fictícias de teste, não
credenciais. Resultados, comparação com a base e limitações estão no PRD
`docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`.

## Etapa 3 — identidade de ofertas (preparação local, sem deploy)

O caminho ativo passa a usar `pipeline_identidade.py` e `repository_identidade.py`.
`produtos` continua sendo o card/instância de oferta, não um catálogo. O hash
antigo em `dedup.py` permanece **somente para decisões legadas congeladas**;
ausência de schema/RPC novo mantém trabalho pendente, nunca ativa fallback novo
por título. Leia o estado e as evidências atuais no
`docs/sdd/incrementos/dealbot-etapa-03-identidade-deduplicacao.md` antes de aplicar
qualquer atualização futura. Nenhum SQL desta etapa foi aplicado em produção.

### Política e matriz de identidade

| Evidência | Decisão |
|---|---|
| Mesmo canal Telegram numérico + mensagem | Mesmo evento, inclusive live/histórico/retry após 48h. |
| Identidade forte de produto/variante, vendedor/anúncio e condições equivalentes | Um card por instância, outra aparição para cada evento novo. |
| Cópia estrita do post, preço igual e mesmo destino de compra verificável | Um card e duas aparições, sem afirmar equivalência comercial de metadados ausentes. |
| Preço conhecido mais recente menor **ou maior** | Atualizar, sem conservar preço antigo apenas porque era menor. |
| Mesmo título, foto, preço ou URL curta | Não prova equivalência; preservar separado quando incerto. |
| Outro seller/loja/variante/kit/quantidade ou condição conflitante | Oferta separada; não remover conflito da chave. |
| Cupom omitido ou vendedor/variante desconhecidos | Não interpretar como sem cupom/seller padrão/variante única. |
| Dois encurtadores opacos | Duplicatas provisórias permitidas; reconciliar somente após prova suficiente. |

Preço não faz parte da chave estável. Nulo difere de zero. `preco_original` é
o preço anterior **anunciado**; `preco_anterior_atualizacao` é metadado distinto
para uma mudança observada. Uma observação vencedora sem preço torna o atual
desconhecido, não zero nem o último menor preço. O card só indica queda quando
ambos os valores comparados são conhecidos, sem fabricar desconto anunciado.

### Formatos realmente reconhecidos e incerteza

`identidade.py` aceita um subconjunto deliberadamente restrito: Amazon BR
`/dp/ASIN` e Mercado Livre BR `/MLB-número` sem slug. O domínio aceito **não**
significa suporte completo. ASIN/catálogo não prova seller ou seleção da variante;
anúncio ML pode conter várias variações. Queries ML não interpretadas, fragmentos,
assinaturas ou outros formatos permanecem incertos. Só `tag` de Amazon no formato
suportado é descartado por regra específica; `linkCode` é conservado/comparado
com caixa exata, `smid` não é removido e precisa concordar com vendedor comprovado.
Não há lista universal de tracking nem ordenação/reconstrução da query.

Identidade forte exige evidência explícita das dimensões relevantes de compra.
O parser pequeno aceita campos de `contexto.identidade` em entradas locais ou
linhas rotuladas da mensagem (`Vendedor:`, `SKU:`, `Variante:`, `Estado:`,
`Quantidade:`, `Kit:`, `Elegibilidade:`, `Pagamento:`, `Cupom:`, `Restrições:`,
`Frete:`, `Assinatura:`, entre outros documentados no módulo). Não aplicabilidade
estruturada exige motivo; omissão é desconhecida, nunca default comercial.
O adaptador Telegram não inventa esses metadados. Texto livre restritivo não
interpretado impede chave; muitos posts comuns continuarão provisórios por
insuficiência de prova. Isso evita prometer fusão baseada apenas no link final.

#### Cópias de publicação — revisão da etapa 3

A identidade **comercial forte v2** permanece inalterada. Para novas decisões,
`copia_versao: 1` habilita uma assinatura **independente** de cópia: destino
verificável do formato Amazon/ML suportado + texto integral + preço exato em
centavos + evidências/contexto preservados. Só CRLF vira LF; caixa, espaços,
cupons, condições, outros links e rótulos de entidades/botões não são apagados.
Substitui-se apenas a ligação de compra selecionada por um marcador; ligações
selecionadas múltiplas/ambíguas não geram assinatura. A tag Amazon reconhecida
pode sair do destino de comparação; `smid` e `linkCode` são conservados. Query
desconhecida, fragmento ou formato não suportado impedem cópia, não são removidos
para fabricar equivalência. Cada observação mantém seu link original navegável.

Assim, dois posts `Notebook 16 GB / Por R$ 2.499,90 no Pix / <compra>` com o mesmo
link ML, ou Amazon diferindo só na tag reconhecida, convergem localmente sem rede.
Não é dedup por título+preço ou URL+preço: mudar condição, vendedor/variante,
conteúdo, outro link ou preço mantém separado. Ausência continua desconhecida.
Por conservadorismo, cópia só reúne registros **sem identidade comercial forte**;
não liga forte↔fraca nem fortes incompatíveis. Chave **e** comparação completa
são conferidas na transação, e preço da observação precisa concordar com a cópia.

Dois encurtadores permanecem disponíveis em cards provisórios até o resolvedor
isolado comprovar o destino; depois a mesma RPC de fusão reúne cópias elegíveis,
preservando aparições, aliases, fotos/pins e IDs antigos. Cache válido evita rede;
falha/timeout não impede publicação. A decisão inicial/hash/checkpoints não são
reescritos. Decisões antigas sem `copia_versao` não recebem essa regra nova no
retry/enriquecimento. Não há backfill/reclassificação do histórico.

Fontes primárias conceituais: modelo oficial Amazon Catalog Items 2022-04-01,
documentação Mercado Livre de variações e requisitos Amazon Associates de links.
Referências/limites estão no PRD e docstrings. Fixtures em
`bot/tests/test_identidade_etapa3.py` são **sintéticas**, não mensagens reais.
Não se acessam canais para amostras, lojas para preço ou APIs autenticadas de lojas.

### Resolução sem atrasar a oferta

Fluxo: identificação local → cache SQLite válido → salvar oferta → worker de
enriquecimento → eventual fusão. Oferta e mídia continuam com seus workers;
resolução tem orçamento próprio, default um worker. Um cache positivo pode
fornecer destino imediatamente após reinício, mas as demais condições ainda
precisam ser equivalentes. Negativo expira; não se repete indefinidamente o mesmo
ciclo impossível. Link original navegável e representação de identidade são
distintos; resultado incerto mantém original.

Allowlist exata: `amzn.to`, `a.co`, `meli.la` e hosts BR de Amazon/Mercado Livre
listados em `resolvedor.py`. Somente HTTP/80 ou HTTPS/443, DNS público validado
em cada salto e socket no IP validado, com certificado/SNI corretos. Sem proxy
de ambiente, autenticação, cookies de conta, JS ou browser. HEAD primeiro;
GET Range apenas em 405/501, lendo somente cabeçalhos e fechando o transporte
sem ler/descomprimir HTML/corpo. Limites default: 5s totais, 5 redirects,
64KiB consumidos pela aplicação, cabeçalhos até 16KiB por resposta. Buffers
finitos de SO/TLS podem antecipar bytes; isso não é teto de tráfego na placa.
Loopback/redes privadas/link-local/metadata/IPv6 não público são recusados.

Cache positivo default 24h, negativo 15min; até 3 tentativas por ciclo. Resultado
HTTP positivo só confirma destino candidato, **não** identidade comercial.
Resolução e reconciliação têm checkpoints separados: falha na RPC de fusão não
refaz rede já confirmada. Falha/timeout nunca rejeita ou esconde a oferta aprovada.
Novos parâmetros e limites estão nos `.env.example`, sem mudança de credenciais.

### Tempo, expiração, aliases e retenção

Datas de mensagem, ingestão, observação de preço e última aparição válida são
distintas. Ordem de preço: maior tupla `(data original válida, canal Telegram
numérico, mensagem)`. Empate usa política determinística, não ordem de chegada.
Sem data confiável não se inventa recência. Histórico atrasado não reduz preço
novo nem renova validade pelo relógio de recepção.

Janela inicial 48h, gravada por instância: `expira_em` depende da última aparição
realmente nova e válida. Retry não renova; uma lacuna após expiração permite nova
instância, sem mover eventos antigos. A API lista/conta só canônicos ativos;
GET por ID fundido resolve o canônico, DELETE por alias remove aquela instância,
não todas as ofertas futuras do produto. Falha técnica não vira falso 404.

Uma instância expirada pode receber uma observação válida **mais recente** dentro
da sua janela temporal original e voltar a ficar ativa, desde que a validade dessa
observação alcance o presente e não exista instância posterior conhecida. Isso
independe de já ter passado pelo limpador e usa a data original, nunca a ingestão:
49h atrás/R$300 seguido de 2h atrás/R$250 resulta em uma visível a R$250 até a
data da mensagem recente +48h, assim como na ordem inversa. Lacuna maior que a
janela mantém instâncias separadas; histórico sozinho não reativa, retry antigo
não renova/muda vínculo e remoção manual continua terminal.

Fusão escolhe menor ID elegível, preserva aparições/observações e foto válida;
aliases são persistentes e não podem ciclar. Jobs/mídia resolvem ID antigo.
Remoção de objeto conhecido exige reserva transacional que impeça novo vínculo,
além de confirmação retomável após Storage. Não há varredura geral de bucket.

Estado local evolui aditivamente à v6. Eventos v2 só são elegíveis para limpeza
local depois do ack remoto; este só ocorre quando oferta, mídia/compensação e
enriquecimento estão terminais. Referências recuperáveis remotas não expiram só
porque passaram 48h. Retenção normal compacta é 7 dias após terminalização/ack;
pendência recuperável é exceção explícita. Não se promete dedup eterna de replay
arbitrário depois de perder/purgar todos os registros locais e remotos.

Jobs legados recuperáveis têm preflight próprio antes da recepção: o bot fixa
referências usando somente decisão/hash/aliases/ID congelados e, ao terminar,
libera o gate remoto `oferta_controle.legado_pronto`. Até lá o limpador novo não
expira/purga legado. `eventos.referencia_remota` mantém essa proteção separada da
identidade antiga, sem reclassificar histórico. Pendência antiga cujo card já foi
apagado antes desta migração exige diagnóstico; não se recria silenciosamente.
Observações confirmadas antigas e aliases elegíveis são purgados em lotes,
inclusive em cards renovados continuamente; o resumo vencedor é preservado.

A unicidade nova usa `(canal_id, telegram_msg_id)` numéricos; username continua
em `canal_origem` somente para apresentação e reconciliação legada delimitada.
`produtos.canal_id` identifica o evento de origem do card, não todos os seus
canais (estes são aparições). Os índices textuais antigos passam a valer apenas
para linhas com `canal_id IS NULL`; assim, um username reutilizado não bloqueia
eventos de canais distintos. O schema não atribui números ao histórico em massa:
somente uma reconciliação legada inequívoca pode fixar a posse da própria linha,
preservando IDs, hashes, grafia e datas. Texto não permite adotar evento v2 nem
linha comprovadamente pertencente a outro canal numérico. Um legado totalmente
sem evidência numérica conserva a compatibilidade textual e sua incerteza.

A migração substitui transacionalmente apenas as definições globais conhecidas,
valida os quatro índices parciais e aborta sobre tipos/definições/dados incompatíveis,
sem apagar duplicatas ou usar CASCADE. `oferta_legado_pronto` confere esses índices
antes de liberar o gate. Escritores antigos com `ON CONFLICT` textual direto são
incompatíveis com essa transição: não os executar junto das RPCs novas, inclusive
para jobs congelados (estes usam `oferta_legado_registrar`). Reaplicar o schema
completo não recria índices globais nem elimina usernames repetidos legítimos.

### Ordem segura de atualização futura e reversão

1. Fazer backup consistente do SQLite e conferir schema/contratos/dados, somente
   em operação futura autorizada. Nunca copiar apenas o arquivo principal com WAL
   ativo, apagar fila ou inventar canal numérico a partir de username.
2. Parar coletor **e suspender limpador antigo**: ele remove por `criado_em` e não
   entende aliases/fotos adotadas. Preparar/aplicar primeiro schema aditivo da etapa
   3; esta entrega executa SQL apenas em bancos locais descartáveis de teste.
3. Atualizar backend/limpeza compatíveis, depois bot com mesmo `BOT_STATE_DIR` e
   único coletor, conferindo RPCs/grants/índices/versões; frontend mínimo por último.
   Retomar limpeza só com protocolo novo. Sem coexistência de limpador antigo.
4. Não recalcular decisões/hash pendentes, refiltrar aprovados, fundir histórico
   em massa ou executar backfill remoto. Migração não transforma legado em prova.
5. Rollback: parar escrita/limpeza, preservar SQLite/schema/aliases/pins e usar
   versão compatível ou manter processamento pausado até correção. Não voltar
   automaticamente a bot/limpador antigos sobre dados novos. Restaurar backup com
   perda de eventos exige decisão explícita; downgrade transparente não existe.

RPCs de gravação/fusão são SECURITY INVOKER, com EXECUTE restrito ao papel servidor
necessário, não PUBLIC/anon/authenticated; não relaxar RLS para testes. Nenhuma chave
de serviço vai para frontend. Testes SQL devem provar duas sessões independentes;
PGlite isolado ou HTTP fake não provam essa concorrência.

**Migração da revisão de cópias/expiração:** antes do bot revisado, em atualização
futura autorizada e com backup/escritores antigos pausados, reaplicar o bloco
`ETAPA 3 OFERTAS` de `supabase/schema.sql` (também é reaplicável no schema completo).
Ele acrescenta somente o índice de expressão de cópia e o comparador invoker
`_oferta_equivalentes`, com grants restritos, e substitui as RPCs no mesmo bloco
transacional. Há16 funções/auxiliares ao final. Não acrescenta confiança às linhas
antigas nem recalcula hashes, apaga dados ou muda o SQLite v6. Os payloads v2
congelados sem cópia continuam aceitos. Não executar o bot revisado sobre as RPCs
anteriores: elas não conhecem cópias nem a correção temporal. Rollback segue a
regra de pausar e preservar schema/fila, sem bot/limpador antigo sobre dados novos.

### Diagnóstico e verificações

Logs correlacionam canal/mensagem/card/versão/motivo/estado, sem URL completa,
cupom, texto ou segredos. Inspecione cópia consistente privada do SQLite para
`eventos.identidade`, `cache_urls`, `enriquecimentos`, `remoto_confirmado` e jobs de
mídia. `estado_local` inclui contagens de enriquecimento/confirmações pendentes.
Motivos distinguem evidência incompleta, campos conflitantes, formato não
suportado, falha DNS/redirect/transporte e reconciliação pendente. Evidências
completas podem conter dados privados: não publicar a saída de inspeção.

Comandos de teste/medições finais e suas limitações são registrados no PRD;
não confundir simulação/fakes com latência, PostgREST, Storage ou RLS de produção.
Esta etapa não autoriza deploy, commit/push ou início da etapa 4.

```bash
# Em bot/, ambiente de teste sem .env/credenciais:
python -m unittest discover -s tests -v
python -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1
python -m simulacao_identidade --seed 42 --pares 10 --cenario todos --db-ms 20 --resolucao-ms 200 --oferta-workers 4 --enriquecimento-workers 1

# Em backend/, somente PostgreSQL LOCAL descartável VAZIO, sem senha real:
DEALBOT_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/dealbot_teste_etapa3 \
DEALBOT_TEST_POSTGRES_DISPOSABLE=SIM npm run test:sql:etapa3
```

Runner SQL aceita `DEALBOT_TEST_PSQL` absoluto quando `psql` não está no PATH;
recusa host remoto, banco não protegido/não vazio, senha/query de conexão e não
lê `.env`/arquivo de senha do usuário. Preserva fixtures para inspeção, sem DROP.
Testa DDL repetido, legado, invoker/RLS/grants, duas sessões com barreira real de
lock, rollback de fusão e corridas. Papéis/auth/storage do Supabase são sintéticos;
não comprova PostgREST/Storage/infraestrutura reais. O modo alternativo PGlite
termina com saída2: não atende concorrência de sessões e não aprova a etapa.

O simulador de identidade usa uma espera por RPC fake, contra cinco operações
lógicas no benchmark original; não comparar diretamente esses tempos como ganho
de produção. Cenários frio/quente/lento compartilham dataset e medem card antes
de liberar resolução, convergência posterior, aparições, filas e máximos de workers.
Limpeza da API usa `RETENCAO_DIAS=7`, `LIMPEZA_LOTE=100`, `LIMPEZA_MAX_LOTES=10`;
os exemplos estão também em `backend/.env.example`.

#### Validação local da revisão (2026-11-09)

Os dois problemas foram reproduzidos no commit `2a6d962` antes de editar:

| Caso sintético | Antes | Depois |
|---|---|---|
| Mesmo post/link ML ou Amazon diferindo só na tag reconhecida | 2 cards | 1 card/2 aparições, sem rede |
| Mesmo post com dois encurtadores | 2 cards mesmo após resolver | 2 visíveis antes de liberar a resposta falsa; depois 1 card/2 aparições e IDs antigos resolvidos |
| Mensagem de49h/R$300 seguida de2h/R$250 | Preço250 numa instância invisível | Uma visível a250, até a data recente+48h, nas duas ordens e com/sem limpeza |

`python -B -m unittest discover -s tests -v` passou **403/403**, sem skips,
em Python3.12.3/WSL,245,409s. Fontes/fixtures Linux com66 hashes iguais ao
checkout; debug, watchdogs e SQLite WAL/FULL preservados. `pip check` passou.
`npm test` passou **63/63** em `backend/` e **13/13** em `frontend/`.
`npm run test:sql:etapa3` passou **47 grupos** em PostgreSQL17.5 local novo,
com sessões independentes (PIDs1300/18348) e barreira `pg_locks`; não PGlite.
Os novos casos cobrem preço/condições/conflitos, ausência de ponte forte↔fraca,
aliases/fotos/pins, replay, concorrência e as duas ordens temporais. Uma prova
complementar ligou `Telegram.envelope`/pipeline/repositório reais às RPCs reais,
sem `contexto.identidade`, confirmando os três pares e os links originais.

Falhas intermediárias não foram descartadas: o runner novo tentou leituras
paralelas numa única sessão e reutilizou uma identidade comercial da fixture
antiga; ambos os erros de instrumentação foram corrigidos sem relaxar asserts.
Na primeira suíte completa houve9 erros porque o venv temporário usado ficou
ausente durante a execução (httpx/subprocessos indisponíveis, causa externa não
determinada). Sem mudar código/testes para contornar isso, foi criado um venv
isolado no filesystem Linux com o requirements existente; SDK/sinais passaram
22/22 antes da nova suíte integral. O Ubuntu não tinha ensurepip: pip foi
inicializado por wheel do PyPI com SHA256 conferido, sem apt/sudo ou alteração
das dependências do projeto. Logs separados `dealbot-revisao3-suite.log` e
`dealbot-revisao3-suite-linux.log` preservam os dois resultados no temporário
local de teste. A fixture negativa antiga agora usa destino não suportado:
o destino Amazon anterior passou a comprovar cópia legítima, não falta de prova.

Nenhuma medição acima prova latência de produção ou suporte comercial universal.
Supabase/Auth/Storage/Telegram/lojas reais não foram acessados; não há browser
E2E ou deploy. O cluster local foi parado limpidamente, com bases sintéticas
preservadas. Revisão final estática sem novos achados no delta; seis prompts do
usuário preservados, nada staged/commitado/publicado e etapa4 não iniciada.
