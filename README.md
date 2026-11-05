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
