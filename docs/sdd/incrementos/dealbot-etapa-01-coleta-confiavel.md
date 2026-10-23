---
id: dealbot-etapa-01-coleta-confiavel
titulo: "Dealbot — Etapa 1: coleta confiável com baixa latência"
status: concluido
modo: rigoroso
risco: alto
versao: 1
aprovacao: usuario
versao_aprovada: 1
aprovado_em: 2026-10-22
criado_em: 2026-10-22
atualizado_em: 2026-10-23
implementacao_iniciada_em: 2026-10-22
base_branch: main
base_commit: 83b6845b6335caf5331f5da34df2831252f6c9b6
---

# PRD de Entrega — Dealbot: coleta confiável com baixa latência

## 1. Resumo

Tornar a coleta pessoal de promoções do Telegram durável e retomável, priorizando a gravação das ofertas novas em poucos segundos, sem aguardar imagens e sem deixar recuperações grandes monopolizarem o processamento. Manter Python/Telethon, Supabase, API Express e frontend Next.js; nesta etapa, imagens continuam no Supabase Storage, atrás de um adaptador substituível.

Este documento especifica somente a etapa 1 de `PROMPT_DEALBOT_ETAPA_01.md`. O planejamento anterior não implementou código; a invocação explícita posterior de `sdd-implementar` aprovou a versão 1, conforme os metadados e o registro da seção 15. Nenhuma etapa seguinte, operação Git de publicação ou alteração remota está autorizada.

## 2. Classificação

- **Modo:** `rigoroso`, por alterar a arquitetura de execução, introduzir persistência local e tratar consistência entre Telegram, SQLite e Supabase.
- **Risco:** `alto`, por risco de perda silenciosa de mensagens, cards duplicados, bloqueio do event loop e falhas nas fronteiras entre efeitos locais e remotos.
- **Proteções adicionais:** testes de interrupção e falhas ambíguas, contratos de idempotência, limites de concorrência, compatibilidade com dados existentes, plano de reversão e proteção do conteúdo local. Tudo permanece neste PRD, sem artefatos adicionais obrigatórios.

## 3. Contexto e comportamento atual

### Comportamento confirmado

| Evidência | Constatação relevante |
|---|---|
| `bot/dealbot.service:8-12`, `bot/railway.toml:5`, `README.md:73-85` | Entrada configurada: executar `python -m src.main` no diretório `bot/`. Não comprova o processo atualmente instalado na VPS. |
| `bot/src/main.py:20-28,87-106` | Cliente Telethon global; apenas `NewMessage`; canais carregados uma vez; filtros carregados sincronamente em cada evento; tasks por mensagem sem fila durável. O semáforo 10 limita processamentos, não a quantidade de tasks aguardando. |
| `bot/src/main.py:31-74` | Extração → filtros → busca de duplicata → download/upload → gravação da oferta. Foto atrasa a disponibilidade da oferta. |
| `bot/src/extractor.py:90-107`, `bot/src/filters.py:15-45` | Extrator por regex/heurísticas; sem IA. Lista válida vazia de filtros aceita tudo; com filtros, basta passar em um. |
| `bot/src/dedup.py:20-56`, `bot/src/repository.py:9-11,32-95` | Já existe deduplicação entre canais: hash de link normalizado + preço, ou título normalizado + preço; busca em janela de 48h por `criado_em`; registra `produto_aparicoes`. Não é apenas deduplicação por mensagem. |
| `bot/src/repository.py:49-95` | Oferta usa upsert por `(canal_origem, telegram_msg_id)`; aparições também. Erros podem ser convertidos em prints/retornos sem retry; comentário de race no chamador não equivale a unicidade por hash no banco. |
| `bot/src/db.py`, `bot/src/repository.py:14-29`, `bot/src/filters.py:10-12` | Cliente Supabase síncrono, inclusive upload síncrono dentro de função `async`. Mídia usa `/tmp/` e nome determinístico por canal/mensagem. |
| `bot/requirements.txt` | Versões diretas fixas: `telethon==1.36.0`, `supabase==2.9.1`, `python-dotenv==1.0.1`; sem lock das transitivas. |
| `supabase/schema.sql:7-49,63-76` | `foto_url` nullable; índices únicos por canal textual/mensagem em ofertas e aparições; índice de hash não é único; `canais.id` é ID da linha no Supabase, não ID Telegram. `bot_state` é por username. |
| `bot/bot.py:17,197-207`, `CLAUDE.md:45-54` | Caminho legado usa Gemini, `bot_state` e histórico limitado a 50; não reativar nem copiar essas limitações. Não há uso de `bot_state` no caminho ativo. |
| `backend/src/models/produto.model.js:16-22`, `backend/src/services/produto.service.js:12-35`, `frontend/lib/types.ts:1-14`, `frontend/components/ProdutoCard.tsx:54-67` | API expõe ofertas/aparições e frontend já suporta foto nula com “Sem foto”. Nenhuma alteração de interface é necessária. |
| `backend/src/services/limpeza.service.js`, `backend/src/config/env.js:34-35`, `backend/src/server.js:11-15` | API já remove ofertas/fotos antigas, por padrão após 48h, em rotina própria. Nome da foto é extraído do último componente da URL e precisa terminar em `.jpg`. Essa retenção é diferente da nova retenção local. |
| `backend/src/services/canal.service.js:23-27` | Criação de canal adiciona `@`; bot usa username do evento sem `@`. Normalização precisa preservar compatibilidade com chaves remotas existentes. |
| `CLAUDE.md:43`, manifests e árvore inspecionada | Não há suíte automatizada do bot nem configuração de lint Python; frontend possui lint/build. Não há PRD anterior em `docs/sdd/incrementos/`. |

### API assíncrona e limitações da inspeção

Consulta somente de leitura às fontes da versão fixada, em 2026-10-22:

- [supabase-py v2.9.1 — exports](https://raw.githubusercontent.com/supabase/supabase-py/v2.9.1/supabase/__init__.py): exporta `AsyncClient`, `acreate_client`, `create_async_client`, `AsyncClientOptions`.
- [cliente assíncrono](https://raw.githubusercontent.com/supabase/supabase-py/v2.9.1/supabase/_async/client.py) e [opções](https://raw.githubusercontent.com/supabase/supabase-py/v2.9.1/supabase/lib/client_options.py): PostgREST/Storage assíncronos e timeouts configuráveis por serviço. Preferir essas APIs, sem atualização automática de dependência.
- [manifest dessa versão](https://raw.githubusercontent.com/supabase/supabase-py/v2.9.1/pyproject.toml): `storage3 ^0.8.0`, `httpx >=0.26,<0.28`; transitivas efetivamente resolvidas ainda precisam ser registradas na implementação.
- [storage-py v0.8.0](https://raw.githubusercontent.com/supabase/storage-py/v0.8.0/storage3/_async/file_api.py): `upload` e `get_public_url` são assíncronos. Upload com arquivo pode fazer leitura síncrona; isso exige cuidado separado com I/O local e memória, não apenas trocar `create_client`.

Não foram consultados Telegram, Supabase do usuário ou VPS. Schema remoto, acessos dos canais, Python da VPS, desempenho real e API efetivamente instalada não foram confirmados. Python local é 3.14.4; `pip show` não encontrou Supabase, Telethon, Storage3 ou HTTPX. Compatibilidade executável não está validada.

### Base e preservação

Worktree: `C:/Users/Alexandre_HP/Documents/DellBot/dealbot`, branch `main`, commit base indicado no cabeçalho. Antes do planejamento havia somente `?? PROMPT_DEALBOT_ETAPA_01.md`; preservar esse arquivo do usuário, sem incluí-lo automaticamente em futuras operações Git. Não criar branch, commit, push, PR, migração remota ou deploy neste comando.

## 4. Problema e objetivo

### Problema

Mensagens podem se perder entre recepção e conclusão; indisponibilidade de Supabase e imagens lentas prejudicam a latência; reinícios não recuperam o que ficou pendente; tarefas e chamadas síncronas podem saturar ou bloquear a recepção. Aumentar o semáforo não resolve esses problemas.

### Objetivo observável

Após registrar uma mensagem localmente, conseguir retomá-la depois de falhas sem outro card para o mesmo evento; salvar ofertas aprovadas sem aguardar mídia; recuperar histórico paginado sem saltos; manter progresso das mensagens novas durante recuperação, com recursos limitados. Medir latência até a confirmação da gravação remota, separada do horário original e da renderização do frontend. “Poucos segundos” é prioridade operacional, não SLA garantido para redes ou máquinas não medidas.

## 5. Escopo

### Incluído

- Inbox/fila SQLite local persistente; controle de coleta por canal; estados independentes para oferta e mídia; retenção segura.
- Recepção rápida, consumidores contínuos limitados, I/O não bloqueante, timeouts, retries duráveis e classificação de falhas.
- Oferta antes de imagem; idempotência de evento e preservação da deduplicação/aparições atuais.
- Recuperação inicial, pós-reconexão e periódica; prioridade live com justiça para histórico.
- Cache de filtros e atualização dos canais ativos durante execução.
- Logs estruturados, tempos distinguíveis, encerramento/retomada, testes offline e simulação reproduzível.
- Atualização local de exemplos de ambiente, documentação e configuração de serviço quando necessária para persistência/encerramento.

### Fora do escopo

- Etapa 2; IA/Gemini; reescrita de extração, filtros, categorias ou nova identidade de produto/oferta.
- Migração de imagens para VPS, segundo armazenamento completo, mudança de banco, frontend, autenticação, novas funcionalidades ou contratos públicos da API.
- Redis, RabbitMQ, serviços pagos ou infraestrutura distribuída; suporte a múltiplas instâncias coletoras simultâneas.
- Executar migrações ou outras alterações remotas, apagar dados remotos manualmente, deploy, acessar VPS, push/PR/merge. Testes desta entrega usam exclusivamente fakes/mocks e arquivos temporários locais.
- Prometer processamento exatamente uma vez, recuperação de mensagens apagadas antes da coleta ou canais inacessíveis; validar latência de renderização do frontend.

## 6. Requisitos

### Requisitos funcionais

#### RF-001 — Entrada local durável

- Inserir eventos live e históricos na mesma inbox SQLite, com unicidade `(telegram_channel_id, telegram_msg_id)`. ID do canal deve ter representação numérica Telethon consistente em todos os caminhos, sem confundir `canais.id` com ID Telegram. Guardar username para exibição e aliases conhecidos.
- Persistir texto necessário ao extrator, data original UTC, primeiro recebimento UTC, origem live/histórico, referência mínima para reencontrar mensagem/mídia, estados, tentativas, próximo retry e erro saneado. Não serializar cliente/evento em memória como única fonte de recuperação, nem depender de referências de mídia que expiram sem possibilidade de refetch por ID.
- Confirmar aceitação apenas depois do commit. Evento duplicado não cria outro job; chegada live pode promover a prioridade de um job histórico pendente, sem refazer um finalizado.
- Diretório configurável e persistente, com permissões restritas. Banco indisponível/corrompido não pode resultar em sucesso fictício ou recriação vazia automática. Logar falha, não avançar coleta, reduzir/parar recepção de forma explícita e retomar via conferência quando possível.

#### RF-002 — Consumo contínuo e recursos limitados

- Notificar consumidores imediatamente após commit; SQLite é a fonte de verdade no início e durante execução. Não usar cron, lotes com janela de espera ou polling de vários segundos para iniciar uma oferta elegível.
- Separar recepção, ofertas e mídia, com número fixo/configurável de workers; acompanhar todas as tasks e limitar buffers, requisições, executor de disco e objetos de mídia em memória. Não criar uma task permanente por mensagem aguardando semáforo.
- Acordar no próximo retry elegível e conferir pendências após reinício mesmo sem sinalização em memória. Seleção e claim devem impedir dois workers de possuir o mesmo job.
- Priorizar live com orçamento explícito de histórico e justiça entre canais, incluindo pelo menos uma oportunidade para histórico a cada ciclo configurado quando ambos estiverem elegíveis. Não reservar toda a capacidade de ofertas ao histórico; com apenas um worker, ceder a vez entre jobs. Mídia usa workers separados.

#### RF-003 — Integrações não bloqueantes e falhas retomáveis

- Usar APIs assíncronas do Supabase 2.9.1 para banco e Storage, verificando os métodos e as transitivas efetivamente instaladas. Definir timeouts de rede e da operação; cancelar uma espera não comprova que o servidor não gravou.
- Isolar SQLite e I/O de arquivos potencialmente lento em executor limitado/serializado, respeitando afinidade da conexão SQLite. Se houver adaptação de qualquer cliente síncrono por threads, comprovar isolamento/segurança por worker, timeout real da chamada e limite do executor; `to_thread` irrestrito não atende.
- Rede indisponível, timeouts, 429 e 5xx: retry persistido com backoff exponencial, teto e jitter; respeitar `Retry-After` e `FloodWait` como espera mínima, sem bloquear indevidamente workers de outra classe.
- Erro permanente, como dado inválido irrecuperável, deve ter estado/motivo claros. Falhas de acesso/configuração devem ficar visíveis e recuperáveis após correção; não descartar silenciosamente por atingir tentativas arbitrárias. Contagem de tentativas não substitui classificação.

#### RF-004 — Oferta primeiro, mídia depois

- Ordem: extrair com o extrator existente → aplicar snapshot válido dos filtros → reconciliar evento já salvo e executar dedup existente → salvar oferta/aparição → persistir conclusão/vínculo remoto e trabalho de mídia → processar imagem → atualizar somente a foto da oferta existente.
- Uma oferta nova pode ter `foto_url=null`; nenhuma operação de download/upload começa como pré-condição da gravação. Falha de mídia não apaga, esconde ou reprova a oferta.
- Tornar atômicos localmente o vínculo `produto_id`, a conclusão de oferta e o agendamento de mídia. Retomar a lacuna entre commit remoto e commit local pela reconciliação do evento, sem inserir outro card.
- Distinguir “produto salvo” de “aparição ainda pendente”: falha de aparição deve ser propagada e retomada sem duplicar produto. Retornos vazios/ambíguos não são sucesso sem resolução do ID remoto.
- Adaptador simples para mídia, com somente uma implementação Supabase Storage. Upload idempotente com chave determinística persistida, vinculada à oferta/mensagem escolhida; retries não geram nomes aleatórios novos nem recursos órfãos previsíveis.
- Foto já válida nunca é substituída por nulo. Duplicata não agenda mídia desnecessária; se a oferta não tiver foto, pode usar uma única fonte persistida com claim exclusivo. Não recriar oferta removida apenas para concluir mídia; reconciliar uploads sem vínculo e prever compensação de órfãos conhecidos, sem varredura destrutiva geral do bucket.

#### RF-005 — Coleta recuperável sem saltos

- Manter por ID estável do canal um marcador de **coleta confirmada**, separado dos estados de processamento e da maior mensagem live observada.
- Fazer conferência ao iniciar, após reconexões relevantes e periodicamente. Usar supervisor de conexão e mecanismos públicos disponíveis no Telethon 1.36.0; não depender somente de `catch_up`, reconexão automática ou evento de conexão suposto.
- Paginar integralmente desde a fronteira persistida até o limite superior de cada varredura. Processar em ordem crescente ou manter prova equivalente de cobertura. Gravar página/mensagens e seu avanço de coleta em transação local; falha em qualquer registro impede ultrapassar aquele trecho.
- Uma mensagem live de ID alto não move o marcador por cima de mensagens antigas ainda não coletadas. Lacunas normais nos IDs não são erro: comprovar cobertura pela paginação do Telegram, não por contiguidade numérica.
- Primeira ativação sem marcador: fixar/persistir início da janela recente (proposta: últimas 24h) e limite superior da varredura. Não importar todo o histórico. Reinícios durante o bootstrap não recalculam uma janela móvel que pule o restante.
- Com marcador existente, continuar a partir dele; limite de lote/tempo limita trabalho por rodada, não o total recuperável. Não descartar silenciosamente backlog antigo para cumprir um orçamento. Pausas por canal sem acesso preservam marcador e explicam a limitação.
- Limitar orçamento de recuperação por canal/rodada e compartilhar idempotência com live. História progride mesmo com novas mensagens contínuas; live não espera a varredura inteira.

#### RF-006 — Filtros e canais atualizáveis

- Cache de filtros com snapshot válido, versão/horário e estado de carregamento; atualização em intervalo curto configurável. Não consultar filtros por mensagem.
- Antes do primeiro carregamento válido, mensagens permanecem pendentes/aguardando configuração, sem aceitação generalizada. Resposta válida `[]` mantém a regra atual de aceitar tudo. Falha posterior preserva o último snapshot válido e registra sua idade.
- Aplicar um snapshot coerente por decisão de processamento; persistir decisão antes do primeiro efeito remoto e vínculo assim que reconciliado, para não alternar a aprovação de um evento por falhas intermediárias/retries. Finalizados descartados não são retroativamente reavaliados por mudança de filtro.
- Atualizar canais ativos periodicamente sem reinício, normalizando username com/sem `@` e caixa; resolver ID Telegram e manter aliases. Falha individual não afeta canais válidos; erro global de leitura preserva a última lista válida, diferentemente de lista vazia válida.
- Lista inicial vazia mantém serviço aguardando novas configurações, sem sair/reiniciar em loop. Ativação nova usa bootstrap limitado; reativação conhecida usa seu marcador. Desativação interrompe novas coletas daquele canal, mas preserva/conclui o que já foi aceito duravelmente.

#### RF-007 — Estados, retenção e retomada

- Estados de oferta distinguem pendente, aguardando configuração, em processamento, retry, aprovada, descartada (sem produto/filtro), duplicata e falha permanente. Estados de mídia distinguem não aplicável, pendente, em processamento, retry, pronta, falha permanente e oferta removida. Nomes exatos podem seguir o estilo do código, preservando essas distinções.
- Claims em andamento devem ser recuperáveis após queda; impedir segunda instância usando o mesmo estado. Startup retoma jobs elegíveis e não altera conclusões válidas.
- Retenção por idade de finalização, em lotes curtos: só remover eventos cujas partes de oferta e mídia estejam terminadas, sem retry, reconciliação ou compensação pendente. Nunca remover pendências ou falhas ainda recuperáveis, mesmo antigas.
- Marcadores e aliases necessários à continuidade não expiram junto com o payload. Documentar retenção dos terminais e o horizonte da deduplicação local; após descarte local, a proteção remota por evento permanece necessária enquanto a oferta/aparição existir.

#### RF-008 — Observabilidade e encerramento

- Logs estruturados com evento, canal/ID da mensagem, origem, estado, tentativa, próximo retry, duração de fila/processamento/rede e `produto_id` quando disponível. Registrar recebimento, descarte, aceitação, duplicata, recuperação, conexão, refresh e fila/falhas de mídia.
- Distinguir `data_origem` Telegram, `recebido_em` local e `disponibilizado_em` confirmado após gravação da oferta. Usar relógio monotônico para durações. Não confundir backlog antigo com latência local e não atualizar métricas remotas por mensagem.
- Registrar tamanho/idade da fila e trabalhadores ativos de forma agregada. Não logar credenciais, session string, conteúdo integral nem URLs contendo segredos; sanear exceções das integrações.
- Em SIGTERM/SIGINT: parar novas entradas e recuperação/refresh, concluir commits em curso, aguardar trabalho acompanhado por prazo finito e encerrar clientes/executores. Não marcar sucesso por cancelamento; preservar/reliberar claims e mídia para retomada. Interrupção forçada também deve ser retomável pela durabilidade/claims.

#### RF-009 — Documentação e evidência da entrega

- Atualizar inicialização, variáveis, diretório/permissões, persistência em serviço/volume, recuperação/retenção, cache, limites, estados/logs e procedimentos offline de testes/simulação.
- Entregar resultados realmente executados, impedimentos com comandos reproduzíveis, arquivos principais, variáveis sem segredos, decisões para etapas seguintes e resumo de continuidade. Parar após etapa 1.

### Regras de negócio

- **RN-001:** não alterar resultados do extrator, categorias ou semântica de `passa_no_filtro`; nenhuma dependência de IA no caminho ativo.
- **RN-002:** preservar `gerar_hash`, normalização atual e janela de 48h por `criado_em`, assim como aparições entre canais. A melhoria é de execução/idempotência; não criar identidade nova por produto.
- **RN-003:** evento é identificado localmente por canal numérico/mensagem; oferta/aparições remotas continuam compatíveis com `(canal_origem, telegram_msg_id)`. Não trocar indiscriminadamente usernames remotos por IDs numéricos nem mudar índices/esquema nesta etapa.
- **RN-004:** consultar vínculo remoto pelo evento/aliases antes da busca temporal por hash em reprocessamentos, inclusive após 48h. Não sobrescrever foto válida nem `criado_em` de uma oferta existente ao retomar. Serializar decisões concorrentes do mesmo hash dentro da única instância, sem alegar unicidade distribuída.
- **RN-005:** não enviar inbox bruta para Supabase. Manter dados aprovados já usados pelo produto, inclusive `raw_text` limitado a 2000 caracteres, `data_oferta`, cupom e aparições. Descartes e falhas ficam locais/logs.
- **RN-006:** aprovação da oferta independe do sucesso da imagem; nenhum retry de mídia produz novo card. A limpeza remota existente não será reescrita: mídia atrasada deve tratar oferta já removida como terminal e compensar artefato conhecido quando necessário.

### Requisitos não funcionais

- **RNF-001 — Durabilidade:** transações SQLite e configuração explícita de durabilidade (proposta: WAL e `synchronous=FULL`), busy timeout limitado, claims recuperáveis e nenhuma confirmação antes do commit. Falta de disco não pode ser mascarada como fila vazia.
- **RNF-002 — Limites:** memória depende de workers, buffer/página e limite de mídia, não do total de pendências. Excesso fica em disco; limite de mídia gera erro explícito, não perda da oferta. Histórico cede a vez por orçamento.
- **RNF-003 — Responsividade:** nenhuma chamada síncrona de rede no event loop; comprovar com teste de heartbeat e fakes que atrasos de banco/mídia não paralisam recepção. Medir latência até gravação, não até imagem ou renderização.
- **RNF-004 — Segurança:** estado e temporários fora de área pública, diretório do proprietário do serviço e permissões mínimas (exemplo Linux `0700`/arquivos `0600`), nunca versionados. Service role só no servidor; não copiar sessão/credenciais para inbox ou logs.
- **RNF-005 — Compatibilidade:** manter entrada `python -m src.main`, contratos remotos e frontend com foto nullable. Dependência nova só se necessária/justificada e fixada conforme `requirements.txt`; não fazer upgrade geral. Registrar Python e transitivas usados na verificação.
- **RNF-006 — Honestidade:** processamento retomável com efeitos idempotentes, não exactly-once. Garantias dependem de estado persistente íntegro, acesso ao canal e histórico ainda disponível. Métricas com mocks não representam VPS/Telegram reais.

## 7. Fluxo e estados esperados

1. Inicializar armazenamento/lock e clientes; recuperar claims; iniciar cache, canais e supervisão.
2. Receber live ou página histórica; confirmar inbox antes de notificar consumidores. Só o percurso comprovado do histórico avança a fronteira de coleta.
3. Worker obtém job elegível segundo prioridade/justiça; espera configuração válida quando necessário; extrai, filtra e decide conforme regras atuais.
4. Reconciliar evento remoto, preservar dedup, gravar oferta/aparição sem mídia; registrar conclusão e mídia pendente localmente.
5. Oferta já está disponível ao consumo da API. Worker independente obtém mídia, envia ao adaptador e atualiza foto da mesma oferta.
6. Falhas transitórias aguardam retry persistido; permanentes ficam explicadas. Reinício retoma; retenção remove somente terminais antigos sem dependências.

Configuração vazia válida, canal inacessível, mensagem sem oferta, imagem ausente e rede indisponível são estados diferentes e testáveis; não podem virar um único retorno genérico de “sem dados”.

## 8. Impacto técnico e contratos

| Área | Impacto previsto |
|---|---|
| Bot | Composição explícita no startup, injeção de clientes testáveis, inbox/controle de coleta, workers, cache, recuperação e shutdown. Evitar efeitos de rede/credenciais reais durante importação de testes. |
| SQLite local | Eventos, canais/aliases/fronteiras, claims, decisões/vínculos remotos e trabalho de mídia. Índices por unicidade e elegibilidade; esquema local versionado, sem migração destrutiva implícita. |
| Supabase | Mesmas tabelas/bucket/índices; CRUD assíncrono e propagação de falhas. `foto_url` pode ser nula e depois atualizada por ID, sem upsert destrutivo no retry. `bot_state` permanece legado. |
| Backend/frontend | Nenhuma modificação funcional planejada; preservar projeção de canais, busca por `raw_text`, ordenação e placeholder de foto. Guardar compatibilidade do nome `.jpg` sem subpastas com o limpador atual. |
| Serviço/documentação | Diretório persistente e encerramento compatíveis com usuário do systemd. Alterar unit somente localmente; jamais instalar/reiniciar serviço remoto neste trabalho. |

### Dados e consistência

- Persistir um identificador remoto textual por evento, separado do ID estável Telegram e do username de exibição atual. Reutilizar a mesma chave em todos os retries. Na integração com dados anteriores, reconciliar variantes conhecidas com/sem `@` e aliases já registrados antes de nova inserção.
- O esquema remoto não comprova ID Telegram de linhas antigas. Não prometer resolver reassociação histórica de username sem evidência nem migrar chaves remotas silenciosamente. Renomeação conhecida com SQLite preservado deve manter o vínculo remoto e não gerar outro card.
- Commit remoto e commit SQLite não são transação única. Testar interrupção/timeout após a gravação remota, antes da resposta e antes do commit local. Consultar por chave idempotente antes de repetir, e manter efeitos pendentes se a reconciliação falhar.
- Registro de produto, aparição e mídia tem checkpoints separados. Falha parcial não pode converter sucesso parcial em novo produto; uma oferta já removida pela limpeza não deve ser ressuscitada por retry de mídia.
- O nome do objeto de mídia deve ser determinístico, plano e terminar em `.jpg`, usando IDs seguros, sem tratar texto do Telegram como caminho. Guardar chave/URL antes das etapas que precisam ser reconciliadas; retentar o mesmo objeto.

### Migração e rollback

- Somente criação/versionamento local de SQLite; sem migração de Supabase. Se o schema exigido pelo código atual não existir no ambiente real, registrar impedimento e pedir decisão; não executar SQL remoto.
- Instalação futura deve criar o diretório persistente com proprietário correto antes de iniciar e preservar o mesmo caminho em upgrades. Não usar `/tmp` para a inbox nem embuti-la na pasta descartável de deploy.
- Reversão futura: parar o novo processo com prazo de shutdown, preservar SQLite e temporários/vínculos, restaurar versão de código anterior sem apagar dados. A versão anterior volta a ser live-only, perde as garantias novas e não consome o backlog; documentar essa limitação. Nunca executar versões simultâneas nem apagar fila para “voltar ao normal”.

## 9. Estratégia de implementação

### Sequência

1. Preparar testes offline e contratos dos clientes; verificar ambiente compatível e API real das versões fixadas. Remover inicialização global que impeça injeção sem credenciais.
2. Introduzir armazenamento local, transações, claims, fronteiras/aliases, retenção e tratamento de falha de disco; testar retomada antes de ligar ao Telethon.
3. Adaptar repositório/cache para async, timeouts e falhas explícitas; preservar extração/filtros/dedup com testes de regressão e reconciliação por evento.
4. Integrar consumers de oferta e mídia, commit da oferta antes de qualquer imagem, vínculo durável e adaptador Storage único.
5. Conectar recepção, atualização de canais, paginação histórica e supervisor; implementar prioridade/orçamento sem pular fronteira por live.
6. Integrar logs, shutdown, retenção e documentação; executar suíte, injeção de falhas e simulação; revisar diff e encerrar sem etapa 2.

### Arquivos confirmados e áreas propostas

- `bot/src/main.py`: composição, recepção, supervisão e ciclo de vida.
- `bot/src/config.py`, `bot/src/db.py`: configuração validada e fábrica async com timeouts, sem credenciais reais nos testes.
- `bot/src/repository.py`: operações async, reconciliação, aparições e atualização de foto, sem absorver falhas recuperáveis.
- `bot/src/filters.py`: separar carregamento/cache da função pura; `bot/src/extractor.py` e `bot/src/dedup.py`: preservar algoritmos, cobrir regressões.
- `bot/.env.example`, `.env.example`, `README.md`, `bot/dealbot.service`, `.gitignore`: exemplos, operação e proteção de estado local.
- `bot/requirements.txt`: manter pins; modificar somente com justificativa.
- **Áreas novas propostas, ainda inexistentes:** módulos em `bot/src/` para armazenamento local, pipeline, recuperação, cache e adaptador de mídia; `bot/tests/` para testes; `bot/simulacao.py` para runner offline. Nomes finais podem seguir a organização existente sem mudar contratos deste PRD.
- Não modificar `bot/bot.py`, esquema remoto, backend ou frontend por conveniência. Ajuste indispensável fora dessas áreas exige explicar o impacto; mudança material exige reaprovação.

### Configuração proposta

Nomes e defaults abaixo formam uma proposta operacional inicial, não valores já implementados ou desempenho prometido. Validar números positivos/faixas e falhar claramente em configuração inválida. Renomeações equivalentes durante a implementação devem ser registradas e refletidas em testes/docs.

| Variável proposta | Exemplo/default | Propósito |
|---|---|---|
| `BOT_STATE_DIR` | `/home/ubuntu/dealbot-state` | SQLite e temporários privados; default local documentado fora de `/tmp`. |
| `BOT_RETENCAO_DIAS` | `7` | Idade de terminais completos, não TTL de pendências. |
| `BOT_LIMPEZA_INTERVALO_S` | `3600` | Limpeza local em lotes, fora do caminho crítico. |
| `BOT_OFERTA_WORKERS` | `4` | Workers de oferta fixos. |
| `BOT_MIDIA_WORKERS` | `1` | Mídia isolada, sem ocupar worker de oferta. |
| `BOT_IO_WORKERS` | `1` | Executor limitado de disco/SQLite com afinidade explícita. |
| `BOT_BUFFER_MAX` | `100` | Limite de referências em memória; backlog permanece no SQLite. |
| `BOT_FILTROS_INTERVALO_S` | `15` | Refresh de filtros; primeiro carregamento imediato. |
| `BOT_CANAIS_INTERVALO_S` | `30` | Refresh de canais; erro preserva snapshot válido. |
| `BOT_RECUPERACAO_INTERVALO_S` | `60` | Conferência de segurança além do startup/reconexão. |
| `BOT_BOOTSTRAP_HORAS` | `24` | Janela recente inicial fixada, somente sem marcador. |
| `BOT_RECUPERACAO_LOTE` | `100` | Máximo por canal/rodada, nunca limite total do histórico. |
| `BOT_PRIORIDADE_LIVE_COTA` | `4` | Até quatro escolhas live antes de uma histórica elegível; com menos workers manter justiça global. |
| `BOT_REDE_TIMEOUT_S` | `10` | Timeout finito de banco/controle; não é meta de latência. |
| `BOT_MIDIA_TIMEOUT_S` | `30` | Timeout finito de download/upload, configurado também no cliente. |
| `BOT_MIDIA_MAX_BYTES` | `10485760` | Teto de memória/arquivo por foto; excesso falha só mídia. |
| `BOT_RETRY_BASE_S` / `BOT_RETRY_MAX_S` | `1` / `300` | Backoff com jitter; FloodWait/Retry-After pode exigir espera maior. |
| `BOT_SHUTDOWN_TIMEOUT_S` | `25` | Prazo finito para drenar/cancelar com retomada; compatibilizar com systemd. |

Manter as cinco variáveis existentes de Telegram/Supabase. Os defaults acima não alteram `RETENCAO_HORAS`/`LIMPEZA_INTERVALO_MIN` do backend.

## 10. Critérios de aceitação

| ID | Relacionado a | Cenário e resultado verificável |
|---|---|---|
| **CA-001** | RF-001, RF-007 | Dada inbox com pendências e claims interrompidos, reiniciar com o mesmo diretório retoma jobs e conserva decisões/vínculos, sem segundo card. |
| **CA-002** | RF-001, RF-004, RN-003 | Mesmo canal/mensagem chega por live e histórico, inclusive em paralelo e com variantes de username: uma linha lógica, um claim ativo e uma única oferta/aparição resultante, mesmo se chamadas forem repetidas. |
| **CA-003** | RF-001, RF-005 | Injetar falha antes/durante commit da página/entrada: não confirmar aceitação nem ultrapassar a fronteira; restabelecer disco e recuperar mensagens ainda disponíveis, sem salto. |
| **CA-004** | RF-004, RN-006 | Bloquear/falhar download e upload fake: produto é gravado antes de qualquer chamada de mídia e permanece acessível com foto nula; retry atualiza só a foto do mesmo ID. |
| **CA-005** | RF-004, RN-004 | Simular commit remoto seguido de timeout/queda antes de commit local, inclusive retry além de 48h com linhas remotas preservadas no fake: reconciliar pelo evento, manter foto/criado_em existentes, completar aparição pendente e não criar card novo. |
| **CA-006** | RF-003, RF-006, RN-001 | Sem snapshot válido, não gravar oferta; carregar `[]` válido aceita conforme regra atual; erro posterior conserva snapshot; editar filtros muda decisões futuras em até um intervalo mais a duração da consulta. Consultas não crescem por mensagem. |
| **CA-007** | RF-005, RF-006 | Adicionar/retirar/reativar canais sem reinício; isolar canal inválido; iniciar sem canais sem sair do processo; manter pendências de desativados; renomeação conhecida preserva ID e vínculo. |
| **CA-008** | RF-005 | Histórico fake com pelo menos 137 mensagens e IDs com lacunas, em várias páginas, com live de ID maior intercalado: todos os eventos no intervalo são coletados, fronteira não salta trecho e restart no meio retoma. |
| **CA-009** | RF-002, RF-005, RNF-002/003 | Rajada live com recuperação grande: live começa antes de acabar a recuperação, histórico também progride, concorrência nunca excede limites, buffers não crescem com backlog e heartbeat continua durante delays de rede. |
| **CA-010** | RF-007 | Limpar registros antigos remove apenas terminais completos elegíveis; mantém oferta pendente, aguardando configuração, retry, mídia e compensação recuperáveis e fronteiras necessárias. |
| **CA-011** | RF-008 | Solicitar shutdown durante processamento e durante mídia: parar entradas, respeitar prazo, não marcar cancelamento como sucesso; reiniciar retoma sem duplicatas. Testar também interrupção sem shutdown cooperativo. |
| **CA-012** | RF-003, RF-008 | Fakes de 429/5xx/timeout/FloodWait e erro permanente produzem estados/motivos/retries esperados, sem laço agressivo, sem bloquear ofertas independentes e sem credenciais nos logs. |
| **CA-013** | RF-004, RN-002/004/006 | Duplicatas entre canais mantêm um card/aparições; testar concorrência do mesmo hash na instância, falha parcial de aparição, retry de upload e produto removido. Foto válida não vira nula nem sob retry sem mídia. |
| **CA-014** | RF-009, RNF-006 | Suíte e simulação rodam offline sem credenciais; relatório real contém parâmetros, latência/vazão/filas/concorrência, comandos, limitações e documentação das variáveis; nenhuma promessa sobre VPS, Telegram ou frontend real. |

## 11. Plano de validação

### Automatizada — futura implementação

Preferir `unittest`/`IsolatedAsyncioTestCase` da biblioteca padrão para reduzir dependências. Usar diretórios temporários SQLite, relógio/RNG controláveis, Telegram e repositório/Storage falsos, sem ler `.env` real. Testes unitários e de integração local devem cobrir todos os CA, incluindo reconexão, recuperação periódica, retenção, normalização/aliases e fairness. O teste de fronteira precisa verificar IDs realmente persistidos, não apenas o valor final do marcador.

Comandos previstos, a disponibilizar junto dos artefatos novos (não existentes hoje):

```text
# A partir de bot/, usando ambiente virtual compatível e sem credenciais reais
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m simulacao --seed 42 --live 100 --historico 1000 --db-ms 100 --midia-ms 2000 --oferta-workers 4 --midia-workers 1
python -m pip check
```

Instalação será local e somente na etapa de implementação; não mudar pins para acomodar Python 3.14 sem investigar. Registrar versão Python, versões transitivas, código de saída e limitações. Não adicionar ferramentas de lint apenas para preencher checklist; executar as existentes que forem pertinentes. Teste de processo/sinais em Linux é necessário para afirmar comportamento do serviço; se o Windows não permitir exercitá-lo integralmente, registrar teste cooperativo local e comando reproduzível para ambiente Linux local, sem acesso à VPS.

### Simulação reproduzível

- Runner proposto usa seed fixa, latências controladas, dados gerados com identidades distintas para os casos de desempenho e cenários específicos de duplicata. Não usar `sleep` bloqueante para simular rede assíncrona.
- Cenário de referência: 1000 eventos históricos, 100 live intercalados a 50ms, operações de banco de 100ms cada, mídia de 2000ms, 4 workers de oferta e 1 de mídia. Registrar quantas operações de banco compõem cada oferta; `db-ms` não significa latência total de persistência.
- Executar também mídia lenta/falha e comparação sem recuperação, mantendo a mesma carga live. Simulação é finita; registrar backlog de mídia ao fim das ofertas em vez de esconder tempo de espera ou exigir que toda mídia termine para medir disponibilidade.
- Informar: quantidade recebida/aprovada/descartada/duplicada/falha, latência local até confirmação da oferta p50/p95/máximo separada live/histórico, vazão de ofertas/s e duração da janela medida, workers configurados/máximo ativo, fila inicial/pico/final por classe e maior atraso do heartbeat. Informar tempo Telegram→recebimento separadamente, quando simulado.
- Aceite funcional: live e histórico progridem antes do término da outra classe; mídia atrasada não é dependência da oferta; limites não são excedidos e identidade não duplica. O relatório deve explicitar backlog e resultados ruins, sem transformá-los em aprovação de desempenho real. Não estabelecer SLA de VPS a partir desses tempos artificiais.

### Manual/documental e regressões

- [x] Conferir documentação de execução `cd bot`/`python -m src.main`, diretório persistente, permissões e prazo do serviço; ver limitação explícita do `systemd-analyze` na seção 15.
- [x] Examinar logs/estados dos cenários fake e teste de sanitização: descarte, duplicata, retry e mídia pendente correlacionáveis sem texto/segredos.
- [x] Inspecionar estado SQLite somente local de teste; nenhum banco ativo do usuário foi consultado/modificado.
- [x] Revisar contratos da API e placeholder existentes; backend/frontend não modificados, sem alegar renderização/E2E real validado.
- [x] Revisar diff: nada no legado/IA/schema remoto, credenciais ou estado versionado; entrada preexistente preservada e nenhum staging/commit.
- [x] Confirmar regressões prioritárias por testes e código preservado: filtros, categorias, hash/janela, aparições, `raw_text`, `data_oferta`, foto nullable e nomes `.jpg`.

### Evidências já obtidas no planejamento

| Comando/procedimento | Resultado real |
|---|---|
| `git rev-parse --show-toplevel` | Raiz do worktree confirmada. |
| `git log -1 --format="%H %D"` e `git worktree list --porcelain` | Branch `main`, commit base do cabeçalho, único worktree listado. |
| `git status --short` antes da escrita | Apenas arquivo de entrada não rastreado; nenhuma modificação rastreada. |
| Leitura de `_comum.md`, `planejar.md` e template | Runtime global `C:/Users/Alexandre_HP/.config/opencode/.sdd-lite`; não existe `.sdd-lite` na raiz. |
| Leitura de instruções, fontes, manifests, exemplos e contratos | Constatações da seção 3; nenhum `AGENTS.md` encontrado no workspace. |
| `python --version` | Python 3.14.4 local. |
| `python -m pip show supabase telethon storage3 httpx` | Código 1: pacotes não encontrados no interpretador consultado. |
| Fontes públicas versionadas Supabase/Storage | API async disponível no código das versões citadas; não equivale a teste executável do ambiente. |
| Revisão integral do PRD e conferência local por Python (`pathlib`/`re`) | 16 seções, 14 critérios, metadados de rascunho/aprovação pendente e ausência de whitespace final conferidos; não é teste da aplicação. |
| `git status --short` após a criação e `git diff --stat` | Apenas entrada preexistente e `docs/` novos; nenhum arquivo rastreado modificado. |
| Testes/build/simulação | Não executados neste planejamento; não há implementação ou suíte nova a validar. |

## 12. Riscos, premissas e perguntas

### Riscos

| ID | Risco | Probabilidade / impacto | Mitigação e sinal de parada |
|---|---|---|---|
| R-001 | Perder mensagens por avanço de fronteira, live intercalado ou bootstrap móvel | alta / alto | Fronteira só de cobertura persistida, janela inicial fixada e CA-003/008. Parar se não for possível provar ausência de saltos. |
| R-002 | Duplicar card em timeout remoto, retry tardio, username alterado ou race de hash | alta / alto | Chave remota persistida/aliases, reconciliação antes da janela de hash, lock por hash limitado à instância e CA-005/013. Se exigir mudança de identidade/schema, pedir reaprovação. |
| R-003 | SQLite em armazenamento efêmero, cheio ou com duas instâncias | media / alto | Diretório/lock/permissões, falha visível, claims/transações. Não iniciar coleta como saudável sem estado íntegro e exclusivo. |
| R-004 | Event loop bloqueado ou memória crescer com fila/mídia | alta / alto | Async real, executor limitado, teto de mídia, consumers fixos, paginação e heartbeat. Não aceitar “async” apenas pelo nome da função. |
| R-005 | FloodWait, canais inacessíveis ou volume maior que a capacidade | media / alto | Backoff durável, isolamento, justiça e exposição de idade/backlog. Documentar perda de acesso e incapacidade de recuperar conteúdo apagado. |
| R-006 | Upload concluído sem vínculo ou produto removido pelo limpador | media / medio | Chave determinística, checkpoints/compensação conhecida e não recriar oferta por mídia. Não prometer transação atômica entre serviços. |
| R-007 | Dependências antigas incompatíveis com Python local/produção desconhecida | media / alto | Ambiente virtual compatível e registro de transitivas. Parar para decisão se solução exigir upgrade material; não mascarar falha de ambiente como aprovação. |
| R-008 | Conteúdo de canais ou credenciais expostos em logs/estado | media / alto | Dados mínimos locais, permissões, sanitização e nenhum estado versionado; revisar logs de exceções. |

### Premissas

- **PRM-001:** apenas uma instância do bot por estado/conta neste desenho pessoal; confirmar na documentação de operação, sem acessar VPS. Múltiplos escritores exigem outra decisão arquitetural.
- **PRM-002:** schema fornecido representa o contrato pretendido; fakes refletem seus índices, nullable e relações. Estado remoto real permanece não verificado e não será alterado nesta entrega.
- **PRM-003:** defaults da seção 9 são ponto inicial ajustável; janela inicial de 24h evita importação integral. Confirmar os parâmetros no aceite, sem condicionar o PRD a ajuste de tuning.
- **PRM-004:** alterações de filtros valem para decisões futuras; snapshots antigos válidos continuam valendo durante falhas temporárias; desativação de canal não apaga trabalho já aceito.
- **PRM-005:** após remoção de dados locais e remotos, não há prova ilimitada de processamento passado. Retenção, exclusão manual e aliases anteriores desconhecidos limitam idempotência histórica; documentar sem promessa absoluta.

### Perguntas abertas

- **PA-001 — não bloqueante:** a VPS usará o caminho de exemplo `/home/ubuntu/dealbot-state` e qual Python? Afeta instalação futura, não a criação do contrato local. Confirmar sem acesso remoto neste comando.
- **PA-002 — não bloqueante:** confirmar se 24h de bootstrap e 7 dias de terminais locais são adequados. Permanecem configuráveis e não autorizam apagar pendências.
- **Perguntas bloqueantes:** nenhuma para esta versão do PRD.

## 13. Proteções adicionais

- [x] Demonstrar reconciliação das fronteiras local/remota e encerramento com testes de falha: RPC/prefixos, compensação/restart, sinais POSIX e admissão live tardia reconferidos na validação final da seção 16.
- [x] Demonstrar compatibilidade com chaves textuais/aparições e fotos existentes em fakes, sem mudar identidade ou executar migração remota.
- [x] Rever recursos e logs: chamadas remotas async, tarefas acompanhadas, limites explícitos e teste de sanitização; ressalvas do transporte documentadas.
- [x] Registrar rollback e retenções separadas, sem apagar estado nem usar ambiente remoto como laboratório de teste.

## 14. Checklist de implementação

- [x] **T01 — Ambiente e contratos testáveis:** RF-003, RNF-005; APIs fixadas verificadas no Python 3.12.3/WSL, HTTP falso e clientes injetáveis, sem credenciais.
- [x] **T02 — Inbox e continuidade local:** checkpoints de compensação preservados e retry de resolução persistido por username; evolução aditiva do SQLite v3→v4 testada preservando jobs, mídia, bootstrap e fronteiras.
- [x] **T03 — Oferta, dedup e mídia isolada:** corrigidos VAL-002/005; upload confirmado com falha permanente agenda reconciliação antes de terminalizar, e o repositório reconstitui duplicata pela origem persistida. 28 testes dirigidos de checkpoint/repositório passaram, incluindo retomada após encerramento e duplicata na mesma origem com outro ID.
- [x] **T04 — Configuração e supervisão:** RPC público único por página, prefixo confirmado antes da próxima chamada, geração protegendo aceitação e cooldown durável mesmo após reativação. Testes dirigidos de coleta/SDK passaram, incluindo os resíduos identificados na revisão.
- [x] **T05 — Operação segura:** regressões de retenção, estados, backoff entre gerações/restart e SIGTERM/SIGINT/SIGKILL aprovadas na suíte final. Instalação real permanece fora do escopo autorizado.
- [x] **T06 — Verificações e simulação:** suíte expandida final com 91 testes aprovados no Linux, sem skips; três cenários medidos novamente, com limites e saturação explícitos. Cobertura histórica/RPC verificada nos testes específicos, não inferida do benchmark.
- [x] **T07 — Revisar diff e preparar validação final:** revisão independente e validação final executadas, inclusive ciclo curto de VAL-006 e nova suíte completa; diff/status/sintaxe/whitespace e preservação conferidos. Sem etapa 2 ou publicação Git/deploy.

## 15. Registro da implementação

Iniciada em 2026-10-22 pela invocação explícita de `sdd-implementar` para este PRD, aprovando a versão 1. Base `main`/`83b6845b6335caf5331f5da34df2831252f6c9b6` confirmada; entrada do usuário e este PRD eram arquivos não rastreados preexistentes. Runtime global relido integralmente; nenhuma instrução `AGENTS.md` no workspace. Nenhum commit, push, deploy ou acesso a recursos remotos do usuário autorizado.

A implementação declarou **T01 a T07** concluídos em 2026-10-22 e foi encaminhada a `em_validacao`. **A validação de 2026-10-23 encontrou contraprovas adicionais e reabriu T02 a T07**, conforme seção 16. O registro abaixo preserva as evidências históricas, sem substituir o resultado final da validação. Não houve alteração material dos requisitos, identidade, banco remoto ou arquitetura aprovada.

### Alterações realizadas

- `bot/src/estado.py`: SQLite privado com WAL/FULL, executor serial e submissões limitadas; lock de instância, eventos únicos, aliases/peers, fronteiras e bootstrap fixos, decisões, posse durável por hash, vínculos remotos, mídia única por produto, retries, claims retomáveis e retenção segura. Esquema local versão 3 inclui confirmação inicial da oferta e motivo de falha permanente a aplicar após compensação de mídia; evolução local aditiva, sem tocar Supabase.
- `bot/src/pipeline.py`: workers fixos por classe, wake-up após commit, justiça live/histórico e estados explícitos; decisão antes da rede e vínculo antes da aparição; oferta e agendamento de mídia consistentes localmente. Retomada cobre lacunas de confirmação remota/local; foto nunca recria produto.
- `bot/src/repository.py`, `bot/src/db.py`, `bot/src/midia.py`: cliente async 2.9.1, timeouts, reconciliação por evento antes de dedup temporal, locks limitados, inserção não destrutiva, aparições idempotentes, atualização condicional de foto e adaptador Storage único com bytes limitados pelo chamador. Sem cliente/env global na importação.
- `bot/src/telegram.py`, `bot/src/recuperacao.py`, `bot/src/cache.py`: referências de canal persistidas para StringSession, extração preservando a precedência original `.text`/`.message`, páginas crescentes e fronteiras transacionais, refresh independente e supervisão por RPC. Download em blocos e fechamento do iterador em cancelamento/erro.
- `bot/src/main.py`, `bot/src/config.py`, `bot/src/modelos.py`, `bot/src/politica.py`, `bot/src/observabilidade.py`: composição, parâmetros validados, recepção sequencial limitada com reação explícita a overflow, classificação/backoff e logs saneados. SIGTERM/SIGINT, drenagem, encerramento de clientes e preservação de claims.
- `bot/src/filters.py`: apenas retirada do carregamento síncrono/global; predicado preservado. `extractor.py`, `dedup.py`, legado, backend, frontend, schema e pins diretos permaneceram inalterados.
- `bot/tests/`, `bot/simulacao.py`: suíte offline com SQLite verdadeiro, HTTP/Telegram/Storage falsos, testes dos SDKs instalados/iterador real, processos POSIX e runner reproduzível com métricas por origem. Nenhum teste usa `.env`, credenciais ou serviços do usuário.
- `.env.example`, `bot/.env.example`, `README.md`, `bot/dealbot.service`, `.gitignore`: exemplos/limites, persistência, operação/diagnóstico, shutdown e exclusão do estado privado do versionamento. `CLAUDE.md` recebeu apenas sincronização das descrições de runtime/testes/cache, antes obsoletas; nenhuma proteção foi reduzida.

### Decisões técnicas menores e revisão independente

- Acrescentado `BOT_RECUPERACAO_PAUSA_S=0.25`: orçamento/pacing explícito, não janela de acumulação. Lotes maiores configurados são subdivididos em leituras internas de no máximo 100. O iterador reverse do Telethon 1.36.0 foi reproduzido reportando fim artificial após 100; o orçamento cheio nunca é tratado como exaustão. Teste real offline cobre as 137 mensagens com lote configurado 200.
- `BOT_IO_WORKERS` aceita somente 1 nesta etapa para garantir afinidade da conexão SQLite; nenhum pool adicional é necessário com mídia em bytes e download limitado por blocos. Não se adicionou dependência de fila, SQLite async ou testes.
- Adaptação privada e mínima da fila de updates do Telethon, protegida por verificação da versão fixada/teste de contrato. Sem ela, o limite de buffers da aplicação não impediria tasks/fila ilimitadas no transporte. Overflow é logado e força desconexão/conferência; nada não persistido avança a fronteira. Pacotes/respostas e caches do SDK ainda têm custo próprio; não há garantia absoluta de memória em bytes sob qualquer payload.
- Preservadas grafias configuradas/canônicas como aliases. Reconciliação remota usa comparação case-insensitive com `_` literal, para encontrar chaves textuais legadas sem migrá-las. Essa é correção de integração, não nova identidade de produto. Conflito entre vínculos conhecidos fica visível e recuperável, sem reassociação silenciosa.
- Hooks HTTP capturam status/Retry-After/código estruturado saneado antes de conversões dos SDKs; erro próprio evita também uma armadilha de `storage3` ao capturar `HTTPError` originado em hook antes de atribuir sua variável `response`. Teste real/MockTransport cobre espera mínima de 120s para 429, 400 de dado inválido (`22P02`) permanente e 400 de schema/cache (`PGRST204`) ou desconhecido recuperável, sem expor corpo/credenciais. A revisão de acompanhamento identificou e corrigiu a classificação excessiva de qualquer 400 como permanente.
- Checkpoint `produto_id` é gravado antes da aparição e a posse do hash sobrevive ao retry ambíguo; não basta um lock em memória. `disponibilizado_em` registra a primeira confirmação conhecida da oferta antes da aparição, enquanto processamento/drenagem têm duração monotônica. Em reconciliação de oferta antiga, esse horário é confirmação local conhecida, não prova do instante original remoto de criação.
- Mídia tem chave determinística única por produto/fonte; intenção de upload anterior à rede permite compensar objeto de resposta perdida, sem varredura geral do bucket. Limpeza remota concorrente ainda tem janela não transacional explicitada no README; não há promessa de zero órfãos/exactly-once.
- Falha permanente de upload com compensação pendente preserva seu motivo e aguarda a remoção idempotente do objeto conhecido antes de terminalizar. A limpeza pode ser retentada, mas não reinicia indefinidamente um upload já classificado como permanente; a oferta continua salva.
- Unit local ganhou `UMask=0077`, estado fora do deploy e `TimeoutStopSec=60`, com folga para drenagem 25s e fechamento dos transportes. Não foi instalada/reiniciada na VPS.
- Revisão por agente independente apontou seis problemas concretos (paginação >100, caixa de aliases, erros reais dos SDKs, justiça live entre canais, cleanup em erro de disconnect e liberação de sender de download). Correções e testes direcionados foram adicionados; revisão não equivale a validação remota.

### Ambiente de verificação e versões

Python padrão do Windows: **3.14.4**, usado para testes da biblioteca padrão (`-S`). Ambiente adicional **Python 3.12.3 no Ubuntu/WSL local**, criado em `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux`, sem mudar o interpretador global ou pins do projeto. `ensurepip` estava ausente no WSL; o ambiente foi criado sem pip e recebeu bootstrap de pip apenas nesse diretório temporário. A primeira instalação ultrapassou 120s; repetida com prazo maior, concluiu. Nenhum recurso da VPS/Supabase/Telegram do usuário foi acessado.

`pip freeze` do ambiente Linux usado nas verificações:

```text
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.10.19
deprecation==2.1.0
gotrue==2.12.4
h11==0.16.0
h2==4.4.1
hpack==4.2.0
httpcore==1.0.9
httpx==0.27.2
hyperframe==6.1.0
idna==3.20
packaging==26.3
postgrest==0.17.2
pyaes==1.6.1
pyasn1==0.6.4
pydantic==2.14.1
pydantic_core==2.50.1
PyJWT==2.15.1
python-dateutil==2.9.0.post0
python-dotenv==1.0.1
realtime==2.33.0
rsa==4.9.1
six==1.17.0
sniffio==1.3.1
storage3==0.8.2
supabase==2.9.1
supafunc==0.6.2
Telethon==1.36.0
typing-inspection==0.4.4
typing_extensions==4.16.0
websockets==15.0.1
```

### Verificações direcionadas — resultados finais

| Comando/procedimento | Resultado real | Observação |
|---|---|---|
| `python -S -m unittest discover -s tests -q` no Windows | Execução final: 65 testes descobertos; 54 passaram, 11 skips; 9,815s | Inclui regressão de upload permanente: compensar antes de terminalizar, sem loop de novo upload. Skips de SDK/iterador real e sinais POSIX, verificados no WSL. |
| `python -m unittest discover -s tests -q` no Python 3.12.3/WSL | **65 testes passaram, sem skips; 70,929s** | Execução final após benchmark e última regressão de compensação; inclui SDK real com HTTP falso, iterador Telethon real, 400 de configuração recuperável, cancelamento e sinais POSIX. Nenhuma credencial. |
| `python -m unittest tests.test_sdk.TestSDK.test_sdk_429_preserva_retry_after_e_400_permanente -v` no WSL | 1 teste passou | SDKs instalados, HTTP falso, erro próprio saneado e Retry-After preservado. |
| `python -m unittest tests.test_regressoes_telethon -v` no WSL | 6 testes passaram | Iterador real, fechamento de download e cleanup apesar de erro de disconnect; sem rede. |
| `python -m pip check` no WSL | Sucesso | Nenhum requisito quebrado. |
| Compilação/AST em memória de `src/*.py`, `tests/*.py` e `simulacao.py` | 27 arquivos Python, 3815 linhas, sucesso | Sintaxe e ausência de whitespace final também conferidas nos novos arquivos e PRD; não escreve bytecode ou executa rede. |
| `git diff --check` / revisão de diff/status | Sem erro de whitespace nos rastreados | Avisos LF/CRLF do checkout Windows; arquivos novos conferidos diretamente. Nada staged/commitado. |
| `git diff --name-only -- bot/bot.py bot/src/extractor.py bot/src/dedup.py bot/requirements.txt backend frontend supabase` | Saída vazia | Legado, algoritmos, pins e aplicações/esquema remotos inalterados. Build/lint/E2E de frontend/backend não executados, pois não houve alteração nessas aplicações. Não há lint/typecheck Python configurado; não se declara cobertura percentual nem verificação estática de tipos. |
| `systemd-analyze verify .../bot/dealbot.service` no WSL | Inconclusivo: timeout 30s | Checkout `/mnt/c` reportado executável/world-writable pelo filesystem Windows; caminhos/usuário de exemplo não são a VPS nem este WSL. Instalação futura deve usar modo 0644 para unit, 0600 para env e estado privado do proprietário; repetir `systemd-analyze verify` no ambiente local equivalente configurado, sem deploy automático. |

Falhas intermediárias não foram tratadas como aprovação: teste expôs compensação que comparava dois nulos e não removia objeto de upload ambíguo (corrigido); smoke de simulação exigia sobreposição temporal com carga minúscula sem garantir backlog simultâneo (substituído por teste determinístico de justiça na fila); hooks HTTP usando `HTTPError` expuseram a armadilha de Storage3 (corrigida com tipo próprio). Watchdogs de simulação/processo foram ampliados para acomodar fsync/WSL em volume Windows sob carga, sem alterar timeouts operacionais ou invariantes de aceite. Houve timeout de uma suíte Windows durante benchmark e um watchdog de retomada POSIX sob carga; a repetição final após o benchmark passou nos dois ambientes. Aviso de depreciação de GoTrue e avisos de tasks lentas no modo debug do unittest foram observados, sem supressão para obter sucesso; pins preservados.

### Simulação — resultados reais

Executados sequencialmente os três cenários abaixo com `python -S`, Python 3.14.4/Windows, seed 42, 100 eventos live a cada 50ms, 4 workers de oferta e 1 de mídia, buffer/página 100, SQLite real WAL/FULL e cinco operações lógicas de banco de 100ms por oferta. Mídia normal: 2000ms download+upload. Todos produziram os produtos esperados, sem falha de oferta, descarte ou duplicata no dataset de identidades distintas. As invariantes de duplicata são exercitadas em testes próprios, não inferidas desse dataset.

Comandos reproduzíveis a partir de `bot/`:

```text
python -S -m simulacao --seed 42 --live 100 --historico 1000 --db-ms 100 --midia-ms 2000 --oferta-workers 4 --midia-workers 1
python -S -m simulacao --seed 42 --live 100 --historico 0 --db-ms 100 --midia-ms 2000 --oferta-workers 4 --midia-workers 1
python -S -m simulacao --seed 42 --live 100 --historico 1000 --db-ms 100 --midia-ms 2000 --oferta-workers 4 --midia-workers 1 --midia-falha
```

| Cenário | Ofertas | Duração (s) | Vazão (ofertas/s) | Live p50 / p95 / máx (s) | Histórico p50 / p95 / máx (s) | Heartbeat, maior atraso (ms) |
|---|---:|---:|---:|---|---|---:|
| Referência (1000 histórico + 100 live) | 1100 | 467,113 | 2,355 | 19,294 / 23,174 / 23,413 | 122,704 / 458,618 / 465,988 | 30,579 |
| Sem histórico (mesma carga live) | 100 | 14,069 | 7,108 | 4,722 / 8,633 / 9,041 | não aplicável | 16,117 |
| Mídia falhando (1000 histórico + 100 live) | 1100 | 241,506 | 4,555 | 18,098 / 25,476 / 26,060 | 137,356 / 232,810 / 241,184 | 17,356 |

| Cenário | Fila live inicial / pico / final | Histórico inicial / pico / final | Mídia inicial / pico / final | Máximo de workers ativos oferta / mídia |
|---|---|---|---|---|
| Referência | 0 / 86 / 0 | 0 / 1000 / 0 | 0 / 1007 / 1007 | 4 / 1 |
| Sem histórico | 0 / 68 / 0 | 0 / 0 / 0 | 0 / 94 / 94 | 4 / 1 |
| Mídia falhando | 0 / 76 / 0 | 0 / 1000 / 0 | 0 / 1100 / 1100 | 4 / 1 |

Filas incluem jobs em processamento; o fim da medição é a última oferta terminal local, sem incluir shutdown nem drenar fotos. Na referência, 93 mídias prontas, 1006 pendentes e uma em processamento; sem histórico, seis prontas e 94 ainda pendentes/em processamento. No cenário falhando, 163 falhas de download ficaram em retry e 937 pendentes/em processamento; todas as 1100 ofertas foram salvas sem depender delas. Live e histórico tiveram progresso antes do fim da outra classe em ambos os cenários mistos. Páginas máximas observadas: 100, sem task por mensagem.

Confirmação de oferta é medida antes da aparição/foto, usando monotônico; a janela de vazão vai do início dos produtores à finalização das ofertas locais. IDs/hash do dataset live iguais nos três cenários (`d991c14a08dd50fa04be501f789356ef0dec35e9c9d0e42b0ae7ee22a44a68c6`); histórico misto (`824898410200b1301ec271e4cc3747b76fcf6715376be4d7094ab40ceb69d900`). Fonte Telegram artificial: 0h live/12h histórico, não incluída na latência local.

**Limitação importante:** a meta operacional de poucos segundos NÃO foi demonstrada nesta rajada. Só a carga live de 20/s já excede a capacidade teórica de 4 workers com cinco esperas de 100ms por oferta (antes do custo SQLite). A instrumentação consulta agrupamentos após cada operação e acrescenta custo; houve outras verificações locais concorrendo com parte do benchmark, portanto carga do host/filesystem não ficou isolada. Não inferir causalidade da diferença de vazão entre cenários nem desempenho de VPS, Telegram, Supabase ou frontend. Seeds reproduzem entradas/falhas, não tempos exatos do escalonador. É evidência de progresso, isolamento de mídia, limites e saturação, não aprovação de SLA ou desempenho de produção. O resultado preliminar anterior, com p95 live ~32s, foi substituído na tabela pela medição com fronteira de latência corrigida (produto antes da aparição).

### Rastreabilidade dos testes para validação final

| Critérios | Evidência automatizada principal |
|---|---|
| CA-001/002 | `test_pipeline`: live/histórico com mesmo evento, primeiro recebimento preservado, reinício sem outro card e claim interrompido. |
| CA-003 | `test_falha_pagina_rollback_nao_avanca_marcador`: falha no segundo insert reverte toda a página; restabelecimento grava o intervalo. |
| CA-004 | `test_foto_lenta_oferta_salva_primeiro_e_shutdown_retomavel`: oferta já confirmada quando download fake está bloqueado; foto retoma no mesmo produto. |
| CA-005 | `test_repository`: resposta perdida de produto/aparição, retry após 48h e foto/criado_em preservados; `test_pipeline`: vínculo antes de aparição e posse durável por hash. |
| CA-006/007 | `test_pipeline` e `test_recuperacao`: config desconhecida versus `[]`, último snapshot válido, decisões preservadas em retry, canais dinâmicos/vazios/inválidos e aliases. |
| CA-008 | `test_recuperacao`: 137 mensagens com lacunas/live alto/reinício; `test_regressoes_telethon`: iterador SDK verdadeiro, limite configurado 200 sem salto após 100. |
| CA-009 | `test_rajada_concorrencia_justica_e_heartbeat`, `test_rodizio_live_entre_canais_e_cota_de_historico` e simulações de referência/comparação. |
| CA-010 | `test_retencao_preserva_pendencias_midia_retry_e_fronteiras`, além de estados/checkpoints de compensação. |
| CA-011 | `test_sinais`: processos locais SIGTERM/SIGINT/SIGKILL e retomada; cancelamento durante mídia e cleanup mesmo com disconnect falhando. |
| CA-012 | `test_sdk`: HTTP falso 429/400 usando SDK instalado; `test_recuperacao`/`test_pipeline`: FloodWait/backoff, erros permanentes, snapshots e sanitização de logs. |
| CA-013 | `test_repository`/`test_pipeline`: mesmo hash concorrente entre canais, aparições, alias legado, upload ambíguo, foto condicional e produto removido sem ressurreição. |
| CA-014 | `test_simulacao`, CLI e resultados por cenário; README e exemplos de ambiente, sem dependência de credenciais. |

Sem desvio material identificado. Se uma descoberta posterior exigir mudar objetivo, contrato, identidade, esquema remoto ou arquitetura, invalidar aprovação conforme SDD Lite antes de executar a parte afetada.

### Continuidade e pendências operacionais (registro de 2026-10-22, superado pela seção 16)

- Próximo passo: `/sdd-validar docs/sdd/incrementos/dealbot-etapa-01-coleta-confiavel.md`. A versão 1 segue aprovada, implementação em `em_validacao`; nenhum commit/push/deploy foi feito.
- Entrada ativa segue `cd bot` / `python -m src.main`, com Python 3.12 e os pins atuais. Configurações/valores sem segredos em `bot/.env.example` e `.env.example`; diretório persistente é obrigatório na operação real. Apenas uma instância por conta/estado; não executar outro coletor com diretório distinto como forma de burlar lock.
- Imagens ainda no Supabase Storage, por `ArmazenamentoMidia`/`ArmazenamentoSupabase`; próxima etapa pode substituir o adaptador sem trocar o fluxo oferta→mídia. Não iniciar migração de imagens, nova identidade ou frontend nesta entrega.
- Validar futuramente caminhos/permissões/unit e capacidade em ambiente equivalente autorizado, antes de qualquer deploy. `systemd-analyze` ficou inconclusivo neste checkout WSL e desempenho de poucos segundos não foi demonstrado na rajada simulada; dados reais, VPS, Telegram e frontend continuam não verificados.
- Preservar este PRD e `PROMPT_DEALBOT_ETAPA_01.md` preexistentes; toda a alteração permanece local e não staged. Resumo para próxima conversa: inbox SQLite durável + posse de hash/vínculo retomável + consumidores limitados + cache/canais dinâmicos + histórico sem salto + mídia posterior; 65 testes Linux aprovados, benchmark expõe saturação, validação SDD final pendente.

### Retomada da implementação — 2026-10-23

Esta invocação de `sdd-implementar` retoma **VAL-001 a VAL-005** na versão 1 já aprovada, mesma branch/commit base e runtime global. PRD, instruções, resultado integral da validação e testes de regressão foram relidos. Todo o diff anterior é preexistente e será preservado; não há autorização para recursos remotos, publicação Git ou etapa 2.

Roteiro concluído: **I01 — correções e regressões**, **I02 — verificações dirigidas/suíte/simulação** e **I03 — revisão/checklist/encaminhamento**. Estado de saída `em_validacao`, não `concluido`. Sem alteração material de requisito/arquitetura: somente execução correta do contrato aprovado, incluindo evolução aditiva do SQLite local para o retry por endereço antes da resolução do ID.

O resultado da seção 16 registra a reprovação anterior e será preservado como histórico; esta implementação não pode declarar a validação SDD concluída.

#### Correções e verificações parciais desta retomada

- **VAL-002:** em `pipeline.py`, falha permanente com `enviado=1` passa a registrar `compensar=1` e motivo final antes de poder terminalizar. A retomada consulta a foto remota: preserva foto já vinculada, remove somente o objeto conhecido não referenciado e mantém checkpoint protegido da retenção até concluir a compensação. Não há esquema ou armazenamento de imagem novo.
- **VAL-005:** em `repository.py`, a classificação de retomada usa `(canal_origem, telegram_msg_id)` do próprio produto e aliases conhecidos. Se a oferta pertence a outro evento, o resultado continua `duplicado` mesmo com `produto_id` já vinculado ou aparição remota existente. Não muda hash, janela de 48h ou chave remota e não adiciona consultas. Uma expectativa antiga que classificava duplicata como `retomado` foi corrigida para o contrato exigido, sem retirar verificações de unicidade/aparições.
- Regressões da validação preservadas; adicionados casos de compensação interrompida/reiniciada e de duplicata no mesmo canal com mensagem distinta. `python -S -m unittest tests.test_checkpoints tests.test_repository -v`, em `bot/`, passou **28 testes em 0,756s** no Windows, sem SDK/credenciais. Suíte completa, SDKs e revisão independente ainda pendentes.
- **VAL-001, primeira abordagem:** tentou-se reconstruir a continuação do iterador desde o último ID seguro. Os testes então passaram, mas a revisão demonstrou chamadas internas não orçadas; essa abordagem foi substituída pelo RPC público único e checkpoint por página descritos no fechamento abaixo. Os fixtures passaram a respeitar bounds/offsets em cada chamada, sem repetir IDs ignorando o pedido.
- **VAL-003:** `recuperacao.py` relê elegibilidade antes de cada canal e depois de RPCs que cedem execução; `estado.py` compara ativação e sua `geracao` no commit transacional. Desativar/reativar muda a geração; uma página da ativação anterior é descartada sem avançar cursor nem retirar pendências aceitas. Refresh não é serializado atrás da rodada inteira de histórico.
- **VAL-004:** tabela local `resolucoes(username,proxima,tentativas,erro)` e coluna `canais.geracao` em esquema SQLite v4, criado/evoluído aditivamente. Username normalizado identifica o retry antes de existir ID; só resolução bem-sucedida remove o checkpoint. Remoção/reinclusão, refresh, reconexão ou reinício não antecipam deadline. Erros são saneados e outro canal continua operável. Sem mudança de schema Supabase, dependências ou variáveis.
- Onze testes novos de coleta verificam desativação antes/depois do commit, geração antiga após reativação, retry normalizado/expiração e migração preservando estado. Testes dirigidos do agente passaram: Windows 23 casos (21 passaram/2 skips SDK) e WSL 29 casos, todos aprovados.
- A suíte integral Windows `python -S -m unittest discover -s tests -v` passou nesta retomada: **84 casos, 71 passaram e 13 skips esperados, 10,462s**. Skips correspondem a SDK/iterador real/sinais POSIX, sendo conferidos na suíte Linux. Nenhuma expectativa de segurança foi enfraquecida ou marcada `expectedFailure`.
- Revisão independente de mídia/repositório aprovou VAL-002/005, incluindo janelas entre commits e retenção; confirmou 28 testes dirigidos. Naquela etapa ainda pendiam revisão adicional da coleta e suíte Linux, concluídas nos registros abaixo. `pip check` passou; nenhum pacote instalado/atualizado.
- A primeira suíte Linux integral desta retomada passou: **84 testes, zero skips, 75,317s**, com SDKs instalados/HTTP falso e sinais POSIX. Não se concluiu a entrega só por esse resultado: a revisão seguinte demonstrou que o mesmo iterador podia emitir outro RPC depois de desativação e perder prefixo não commitado ao atingir FloodWait após várias respostas curtas.
- Esses dois resíduos de VAL-001/003 motivaram a correção do controle da chamada efetiva de histórico, com regressões adicionais e checkpoints de prefixo descritos abaixo. Não se relaxaram proteções, não se introduziu SLA fictício nem se alterou o contrato público/identidade.

#### Fechamento dos resíduos da revisão

- O adaptador final não reconstrói mais iteradores opacos: cada página faz **um único `GetHistoryRequest` público do Telethon**, com no máximo 100 mensagens. Usa os offsets crescentes da API fixada e valida os bounds localmente. `PaginaHistorico` mantém o desempacotamento de mensagens/fim e explicita o cursor de cobertura; tombstones avançam cobertura sem fabricar texto/data/evento. Respostas sem lista de mensagens são erro, não falsa página vazia.
- Página não vazia/curta confirma somente o prefixo devolvido. A recuperação o grava transacionalmente antes de outra chamada e seu pacing/backoff. Fim só ocorre com leitura vazia ou alcance comprovado do limite superior fixado. Não há segundo RPC interno após desativação, nem perda repetida do prefixo ao encontrar FloodWait em página posterior. Regressão de servidor limitado coletou os 137 IDs em 150 pedidos, com 13 FloodWaits, sem reproduzir prefixos já confirmados.
- A formatação recebida por RPC raw usa o `parse_mode.unparse` público para manter o mesmo texto do caminho ativo, inclusive entidades de código usadas pelo extrator de cupom; não se usa `_finish_init` privado nem muda o extrator. O fixture SDK foi substituído por cliente RPC falso que respeita offsets, exige uma chamada por página e confere a continuação separada, sem enfraquecer a cobertura.
- Uma corrida adicional da mesma proteção foi reproduzida pela revisão: RPC de geração antiga recebia FloodWait depois de desativar/reativar e a guarda de geração descartava o deadline. Corrigido `falhar_canal(..., minimo_remoto=True)` para conservar `MAX(proxima, deadline)` por ID estável mesmo inativo/em outra geração, sem tocar cursor, limite ou ativação. A guarda de geração continua obrigatória na aceitação de dados; erros ordinários antigos não substituem o estado da nova ativação. Duas regressões verificam remoção/reativação/restart sem encurtar o mínimo recebido.
- Revisão independente final da coleta confirmou as três correções, sem novo bloqueante confirmado; revisão independente de mídia/repositório também aprovada. Isso não substitui a próxima execução do adaptador `sdd-validar`.
- Verificação final dirigida no WSL: `python -m unittest tests.test_sdk tests.test_coleta_retoma tests.test_validacao_coleta -v` passou **26 testes, zero skips, 26,537s**. Inclui RPC real tipado/cliente falso, cupom formatado, orçamento, tombstones, prazos e geração. No Windows, conjunto de coleta/checkpoint passou **24 casos, 7 skips SDK, 1,898s**. Essas execuções antecederam a suíte final completa consolidada abaixo; nenhum teste foi pulado para ocultar defeito.

#### Evidências finais da retomada

| Comando/procedimento | Resultado executado | Limite |
|---|---|---|
| Windows, em `bot/`: `python -S -m unittest discover -s tests -q` | **91 testes, 72 passaram, 19 skips; 11,960s** | Skips de SDK/RPC real e sinais POSIX, executados no Linux. |
| Python 3.12.3/WSL, em `bot/`: `python -m unittest discover -s tests -v` | **91 testes passaram, sem skips; 82,488s** | Inclui todas as regressões da validação anterior e resíduos da revisão. Nenhuma credencial/rede real. |
| `python -m pip check` no ambiente Linux existente | Sucesso | Sem nova dependência ou upgrade de pins. |
| AST/sintaxe/whitespace de fontes, testes e runner | **30 arquivos Python / 4818 linhas**, sem erro | Conferência em memória, sem executar integrações. |
| `git diff --check`, `git diff --stat`, `git status --short` e revisão dos novos arquivos | Sem whitespace acidental; somente avisos LF/CRLF do checkout Windows | Nenhum staging, reset, commit, push, PR, merge ou deploy. |
| `git diff --name-only -- bot/bot.py bot/src/extractor.py bot/src/dedup.py bot/requirements.txt backend frontend supabase` | Saída vazia | Legado/IA, algoritmos, pins, frontend/backend e schema remoto preservados. |

Os testes de watchdog/rajada e sinais passaram na suíte final sem aumentar seus timeouts nem excluir assertions. Permanecem os avisos preexistentes de depreciação GoTrue e de tasks lentas em debug sob WSL; não foram suprimidos para obter sucesso. `systemd-analyze`/instalação real e capacidade da VPS continuam com os limites registrados nas validações anteriores, pois a unit não foi instalada nem alterada nesta retomada.

#### Simulação executada nesta retomada

Repetidos sequencialmente os três comandos já reproduzíveis nas seções anteriores: referência com 1000 histórico + 100 live, mesma carga live sem histórico e mídia falhando. Python 3.14.4/Windows, seed 42, 100 live a cada 50ms, cinco esperas lógicas de banco de 100ms, mídia 2000ms download+upload, workers 4 ofertas/1 mídia, buffer/página 100. As suítes completas foram executadas fora do benchmark; revisões/testes dirigidos locais podem ter concorrido e o host não é laboratório isolado. Os datasets/hash continuam iguais.

| Cenário | Ofertas salvas | Duração (s) | Vazão (ofertas/s) | Live p50 / p95 / máx (s) | Histórico p50 / p95 / máx (s) | Heartbeat máx (ms) |
|---|---:|---:|---:|---|---|---:|
| Referência | 1100 | 213,934 | 5,142 | 33,004 / 38,357 / 38,864 | 120,752 / 206,345 / 213,745 | 16,806 |
| Sem histórico | 100 | 14,518 | 6,888 | 4,777 / 9,046 / 9,526 | não aplicável | 15,852 |
| Mídia falhando | 1100 | 199,706 | 5,508 | 7,379 / 13,168 / 14,029 | 102,289 / 191,137 / 199,474 | 16,708 |

| Cenário | Fila live inicial / pico / final | Histórico inicial / pico / final | Mídia inicial / pico / final | Máximo ativo oferta / mídia |
|---|---|---|---|---|
| Referência | 0 / 87 / 0 | 0 / 1000 / 0 | 0 / 1019 / 1019 | 4 / 1 |
| Sem histórico | 0 / 68 / 0 | 0 / 0 / 0 | 0 / 94 / 94 | 4 / 1 |
| Mídia falhando | 0 / 79 / 0 | 0 / 1000 / 0 | 0 / 1100 / 1100 | 4 / 1 |

Referência teve 81 fotos prontas e 1019 pendentes/em processamento ao fim das ofertas; sem histórico, seis prontas e 94 pendentes/em processamento. Mídia falhando teve 156 falhas de download em retry e não impediu salvar as 1100 ofertas. Em ambos os cenários mistos, live e histórico progrediram antes do fim da outra classe; página máxima 100 e nenhuma task por mensagem. Zero descartes/duplicatas/falhas de oferta era esperado nesse dataset de identidades distintas.

**Interpretação obrigatória:** latência encerra na confirmação do produto, antes da aparição/foto; vazão inclui finalização local e exclui setup/shutdown/drenagem das fotos. O produtor histórico do benchmark grava diretamente na inbox, portanto o orçamento RPC, tombstones, short pages e FloodWait real do adaptador são comprovados pelas regressões próprias, não pelo benchmark. A medição não valida Supabase/Telegram/VPS/frontend reais. Saturação de 20 chegadas/s contra 4 workers com cinco operações de 100ms continua produzindo filas; **a meta operacional de poucos segundos não foi demonstrada nessa rajada**. Não inferir melhora/piora causal comparando execuções em host não isolado, nem apresentar esses resultados como SLA.

#### Continuidade após as correções

- **VAL-001 a VAL-005:** causas corrigidas, regressões originais preservadas e aprovadas com cobertura adicional dos RPCs efetivos e cooldown entre gerações; não há bloqueante confirmado na revisão desta implementação. A conclusão final depende de nova execução de `sdd-validar`, não desta afirmação de implementação.
- **Decisões preservadas:** uma instância; Python 3.12 com pins atuais; SQLite privado/persistente; hash/janela/filtros inalterados; ofertas no Supabase e imagem posterior por adaptador único. O SQLite v4 evolui aditivamente sem apagar pendências; não trocar/apagar o diretório para aplicar a correção. Nenhuma migração Supabase ou mudança de recurso remoto foi executada.
- **Variáveis/dependências:** nenhuma variável nova nesta retomada e nenhum pacote novo. Exemplos completos permanecem em `bot/.env.example` e `.env.example`; limites/intervalos/pacing continuam configuráveis pelos mesmos nomes.
- **Pendências:** nova validação SDD da versão 1, configuração/permissões/unit e desempenho real somente em ambiente autorizado futuro. Não iniciar etapa 2, mover imagens, fazer deploy ou publicar Git por conta própria.
- **Próximo comando:** `/sdd-validar docs/sdd/incrementos/dealbot-etapa-01-coleta-confiavel.md`. Resumo para a próxima conversa: cinco achados corrigidos; histórico em RPC único com prefixos, geração e espera mínima durável; mídia compensa/reconcilia sem perder checkpoint; duplicata mantém classificação; 91 testes Linux passaram; benchmark ainda demonstra saturação, não SLA.

## 16. Resultado da validação

### Nova validação após a retomada — 2026-10-23 — APROVADA LOCALMENTE

Execução iniciada pela nova invocação explícita de `sdd-validar`. Runtime global, `_comum.md` e `validar.md` relidos integralmente; PRD completo, aprovação da versão 1, branch `main`, commit base e único worktree confirmados. Sem `AGENTS.md` no workspace. Todo o diff e todos os arquivos de teste atuais eram preexistentes a esta validação e estão preservados; não há autorização para staging/publicação, recursos remotos ou etapa 2.

Roteiro concluído: **VF1 — revisão independente e verificações locais**, **VF2 — ciclo curto de VAL-006 e regressões**, **VF3 — matriz e decisão final**. Estado final `concluido` para o escopo local/offline aprovado, não aprovação de deploy, instalação ou desempenho de produção. Os resultados históricos abaixo foram preservados, não usados como substituto da execução atual.

#### Ciclo curto desta nova validação — VAL-006

A revisão reproduziu uma admissão **live** iniciada com o mapa antigo, mas ainda não commitada quando o refresh confirmou a desativação. Depois dessa confirmação a linha era inserida e gerava card, embora `ativo=0`. Não se confunde com terminar pendência anteriormente aceita; viola RF-001/006 e CA-007. Locais: `main.py`/`Pipeline.receber` faziam seleção inicial, mas `EstadoLocal.registrar` não possuía a guarda atômica da página histórica.

Aplicado ciclo curto autorizado: correção localizada, objetiva, reversível, sem requisito novo, migração, dependência, arquitetura ou contrato público novo. `Pipeline.receber` captura a geração cadastrada; a operação serial `EstadoLocal.registrar` confere ativo/geração imediatamente junto da inserção e sinaliza recusa sem criar job. O uso genérico da inbox sem cadastro de canal continua compatível; no serviço real os canais monitorados possuem cadastro. Pendências já commitadas continuam processando, mesmo inativas. Recusa é registrada como `mensagem_ignorada`, sem expor conteúdo/segredos.

Acrescentadas duas regressões em `tests/test_checkpoints.py`, sem afrouxar testes anteriores: gravação retardada até depois da desativação e gravação de geração antiga após desativar/reativar. Ambas rejeitam a mensagem ainda não aceita e comprovam que mensagem anteriormente gravada conclui e produz somente seu próprio card. Após a correção, **46 testes dirigidos** de checkpoint/pipeline/repositório passaram em **2,817s**; suíte completa Windows passou em **93 casos (74 aprovados, 19 skips), 28,003s**. A suíte Linux final passou **93 testes, zero skips, 141,221s**.

Revisão independente repetiu a reprodução com `servir` real e SQLite temporário/fakes: handler atrasado não criou linha/card depois da desativação; handler iniciado depois da confirmação foi barrado; geração antiga 0 foi rejeitada após geração 2; mensagem 10 previamente aceita concluiu enquanto inativa e produziu exatamente um card. Retorno da recusa foi `False`, com `mensagem_ignorada` e sem log de aceitação. Ambos os cenários encerraram corretamente. **VAL-006 corrigido e encerrado nesta validação**, sem bloqueante residual confirmado.

#### Matriz final atual — requisitos, regras e RNF

Resultados restritos ao escopo local/offline autorizado, com clientes externos falsos. Não há aceite parcial implícito nem SLA de VPS derivado dos testes.

| Item | Resultado | Implementação e verificação atual |
|---|---|---|
| RF-001 | atendido | Inbox SQLite, chave única por canal/mensagem, texto/data/referência, commit antes da aceitação, FalhaLocal e rollback; testes de duplicidade/erro de escrita e nova guarda live passaram. |
| RF-002 | atendido | Workers fixos por classe, executor/gate limitados, wake-up após commit e escolha justa; testes de claims/rodízio/heartbeat e benchmarks repetidos. |
| RF-003 | atendido | SDKs async/timeouts, retries saneados e persistidos por job/username/ID; HTTP 429/400/503, FloodWait e cooldown entre gerações/restart conferidos. |
| RF-004 | atendido | Oferta antes da foto, vínculo/aparição retomáveis, adaptador único e compensação durável; regressões antes/depois do vínculo da foto, retenção e restart passaram. |
| RF-005 | atendido | Um GetHistory público por página, cobertura conservadora explícita, bootstrap fixo, gaps/tombstones, prefixos antes de FloodWait e não avanço por live; regressões de 137 mensagens e respostas curtas passaram. |
| RF-006 | atendido | Snapshot de filtros desconhecido versus vazio, refresh independente, último válido e canais dinâmicos; commit de histórico e admissão live agora rejeitam ativo/geração encerrados sem abandonar pendências. |
| RF-007 | atendido | Estados, tentativas/deadlines/erros, claims recuperáveis, compensações protegidas da retenção e duplicata mantida na retomada; migração local v3→v4 e reinício aprovados. |
| RF-008 | atendido | Logs JSON saneados/correlacionáveis, horários diferenciados, durações monotônicas e métricas locais; revisão de chamadas, sanitização e SIGTERM/SIGINT/SIGKILL/cleanup aprovados. |
| RF-009 | atendido | README/env/unit, operação/retensão/diagnóstico, testes e simulações com limitações e continuidade; log de recusa live documentado no ciclo curto. |
| RN-001 | atendido | AST do predicado/normalização e 216 comparações com baseline; extrator preservado byte a byte; entidade de código de cupom preservada no RPC raw. Sem IA no caminho ativo. |
| RN-002 | atendido | `dedup.py` idêntico ao commit base; hash, janela de 48h e aparições preservados, inclusive testes concorrentes/retomada. |
| RN-003 | atendido | ID numérico local e chave textual remota preservados; nenhuma mudança de índices/schema/API; guardas de geração não mudam identidade de oferta. |
| RN-004 | atendido | Reconciliação por evento antes da janela de hash, posse durável/locks, foto/criado_em preservados; testes de resposta perdida e retry >48h aprovados. |
| RN-005 | atendido | Inbox bruta só local; repositório mantém payload aprovado existente e `raw_text[:2000]`; sem gravações remotas adicionais de métricas. |
| RN-006 | atendido | Foto posterior não impede/apaga oferta, não cria outro card e não ressuscita produto removido; compensação conhecida verificada. Corrida inerente com limpador remoto continua documentada. |
| RNF-001 | atendido | WAL/FULL, busy timeout, executor serial, lock e transações de checkpoint; rollback/claims/aceitação tardia conferidos com SQLite real temporário. |
| RNF-002 | atendido | Limites de workers, buffers, páginas/RPCs e bytes de mídia; orçamento e progresso testados. Custos internos de pacotes/caches do SDK não são promessa de limite absoluto em bytes. |
| RNF-003 | atendido | Rede async real com HTTP falso e I/O SQLite fora do event loop; heartbeat/rajada e tempos de confirmação antes da foto executados. Sem validação de renderização. |
| RNF-004 | atendido | Inspeção POSIX atual confirmou diretório 0700, DB/WAL/SHM/lock 0600 e dono; logs/erros e exclusões de estado do Git revisados, sem credenciais reais. |
| RNF-005 | atendido | Entrada correta, pins e contratos preservados; Python 3.12.3, SDK tipado/MockTransport e `pip check` atuais aprovados. |
| RNF-006 | atendido | Limitações/exatamente-uma-vez/host artificial/sem acesso a canais e sem validação real explicitadas; métricas ruins não foram transformadas em garantia de desempenho. |

**Resumo atual:** 21 requisitos/regras/RNF atendidos no escopo aprovado; nenhum parcialmente atendido, não atendido ou não verificável obrigatório remanescente.

#### Matriz final atual — critérios de aceitação

| Critério | Resultado | Procedimento/evidência atual |
|---|---|---|
| CA-001 | atendido | Reinício com pendências, claim interrompido, efeito remoto ambíguo e mídia; mesmo card/vínculo preservados. |
| CA-002 | atendido | Mesma mensagem por live/histórico/aliases e concorrência: uma linha lógica, claim exclusivo e efeito idempotente. |
| CA-003 | atendido | Falha temporária injetada no segundo insert reverte página/marcador; recuperação posterior não salta dados disponíveis. |
| CA-004 | atendido | Download/upload bloqueados ou falhando: oferta salva antes e continua acessível; retry só atualiza foto do mesmo produto. |
| CA-005 | atendido | Respostas perdidas após commit, intervalo >48h e aparição pendente: reconciliação sem novo card, foto/criado_em preservados. |
| CA-006 | atendido | Configuração inicial desconhecida aguarda, `[]` válido aceita conforme regra, falha conserva snapshot e refresh altera decisões futuras sem consulta por mensagem. |
| CA-007 | atendido | Inclusão/remoção/reativação/lista vazia/canal inválido/aliases; recusa de página e live não commitados após desativação, preservando trabalho anterior. |
| CA-008 | atendido | 137 mensagens, gaps, live alto, resposta curta, página configurada 200 e reinício; cursor seguro, todas as mensagens esperadas persistidas. |
| CA-009 | atendido | Rajada + recuperação progridem ambas antes de terminar a outra, workers e memória de fila limitados e heartbeat ativo; sem impor SLA não aprovado. |
| CA-010 | atendido | Retenção mantém pendências, mídia, compensação e fronteiras; objeto conhecido não perde chave antes da reconciliação/limpeza, inclusive após restart. |
| CA-011 | atendido | Processos Linux locais SIGTERM/SIGINT/SIGKILL, cancelamento de mídia e falha de disconnect encerram/retomam sem falso sucesso ou duplicação. |
| CA-012 | atendido | HTTP 429/503/timeout, erro de dado versus configuração, FloodWait por nome/ID e gerações/restart; backoff/prazo mínimo e sanitização comprovados. |
| CA-013 | atendido | Hash concorrente, aparições, aliases legados, upload ambíguo, foto válida e produto removido; duplicata retomada permanece duplicata. |
| CA-014 | atendido | Suítes, revisões/reproduções e três cenários executados sem credenciais; comandos, métricas e limites registrados, sem alegar produção ou frontend real. |

**Resumo atual:** 14 critérios atendidos; nenhum não executado obrigatório ou bloqueante aberto. As quatro proteções rigorosas da seção 13 foram reconferidas: falhas/retomada, compatibilidade, recursos/segredos e rollback/retenções.

#### Escopo e diff desta validação

- **Previsto:** código bot e artefatos de operação/teste da entrega, conferidos contra PRD/base; toda a implementação prévia e a entrada do usuário foram preservadas.
- **Necessário/desvio menor já documentado:** fila limitada específica do SDK fixado, SQLite serial, pacing e RPC público de histórico; nenhuma nova tecnologia, regra de filtro, identidade ou API pública.
- **Ciclo curto novo:** somente `bot/src/estado.py`, `bot/src/pipeline.py`, duas regressões em `bot/tests/test_checkpoints.py`, um item explicativo no README e o registro deste PRD. Nenhuma mudança de schema local/remoto, dependência, autenticação, permissão, frontend/backend, legado/IA ou pins.
- **Fora do escopo:** nenhuma alteração material identificada; não se fez refatoração geral, deploy, migração remota, publicação Git ou etapa 2.

#### Comandos/resultados desta execução

| Comando/procedimento | Resultado real | Limitação |
|---|---|---|
| Git raiz/base/status/worktrees e revisão de diff | `main`/`83b6845b6335caf5331f5da34df2831252f6c9b6`, único worktree; diff preexistente preservado | Sem staging/reset/commit/push/PR/merge. |
| Windows `python -S -m unittest discover -s tests -v` antes do ciclo curto | 91 descobertos, 72 aprovados/19 skips; 14,382s | SDK/POSIX conferidos no WSL, não ignorados para obter aprovação. |
| WSL `python -m unittest discover -s tests -v` antes do ciclo curto | 91 aprovados, zero skips; 90,343s | Não impediu revisão adicional que encontrou VAL-006. |
| Windows `python -S -m unittest tests.test_checkpoints tests.test_pipeline tests.test_repository -v` após correção | 46 aprovados; 2,817s | Causas e regressões, não só sintaxe. |
| Windows `python -S -m unittest discover -s tests -q` final | **93 descobertos, 74 aprovados/19 skips; 28,003s** | As partes puladas estão no Linux abaixo. |
| WSL `python -m unittest discover -s tests -v` final | **93 aprovados, zero skips; 141,221s** | Rede/Supabase/Storage falsos, SQLite/SDKs/processos reais locais. |
| Revisão independente de consistência/mídia e 16 testes dirigidos offline | Sem bloqueante confirmado; 16 passaram, 1,571s | Limitada ao escopo revisado, combinada à revisão de coleta e matriz desta sessão. |
| Revisão da coleta e reprodução final com `servir` após VAL-006 | Correção confirmada: nenhuma linha/card de admissão tardia; pendência anterior concluída e dois cenários encerrados limpos | Sem credenciais, rede ou recursos do usuário. |
| `python -m pip check` no ambiente existente | Sucesso | Nenhum pacote instalado/atualizado nesta validação. |
| AST/216 comparações de filtro e bytes extrator/dedup contra `HEAD` | Sucesso | Só o carregador síncrono removido foi excluído da comparação AST, não regras. |
| Env de exemplo e Config com ambiente falso, parser da unit, HTTP 503 | 20 variáveis BOT coerentes, cinco inválidas rejeitadas, unit parseável/prazo 60s, 503 recuperável | Nenhum `.env` real ou serviço inicializado. |
| SQLite POSIX temporário atual | Schema 4, diretório 0700, DB/WAL/SHM/lock 0600, proprietário atual | Disco Linux temporário, não inspeção de VPS ou permissões NTFS. |
| AST/sintaxe/whitespace, matriz e `git diff --check` finais | 30 arquivos Python / 4875 linhas sem erro; PRD e 21+14 linhas da matriz coerentes | Avisos LF/CRLF preexistentes do checkout; nenhum staging ou descarte. |

Ambiente/pins/transitivas seguem a seção 15; Python Windows 3.14.4 (`-S`) e WSL 3.12.3 com SDKs existentes. Warnings preexistentes GoTrue/task lenta não foram suprimidos. Lint/typecheck Python não configurados; frontend/backend/schema sem alterações, portanto build/E2E remoto dessas aplicações não é verificação obrigatória deste incremento. Não se declara cobertura percentual, instalação systemd real, autenticação/latência remota ou renderização aprovada.

#### Simulação repetida nesta validação

Repetidos sequencialmente os três comandos reproduzíveis da seção 15, depois das suítes iniciais e **antes do ciclo curto VAL-006**: referência, sem histórico e mídia falhando. Seed 42, 100 live a 50ms, 1000 históricos nos cenários mistos, cinco operações lógicas de banco de 100ms por oferta, mídia 2000ms, workers 4/1 e buffer/página 100. Dados/hash iguais aos anteriores; resultados controlam atrasos/entradas, não o host.

| Cenário | Ofertas | Duração (s) | Vazão (ofertas/s) | Live p50 / p95 / máx (s) | Histórico p50 / p95 / máx (s) | Heartbeat máx (ms) |
|---|---:|---:|---:|---|---|---:|
| Referência | 1100 | 216,622 | 5,078 | 7,407 / 13,044 / 13,905 | 105,152 / 208,477 / 216,418 | 22,300 |
| Sem histórico | 100 | 13,974 | 7,156 | 4,602 / 8,588 / 9,008 | não aplicável | 15,652 |
| Mídia falhando | 1100 | 177,811 | 6,186 | 7,365 / 13,067 / 13,974 | 89,177 / 170,524 / 177,625 | 17,036 |

| Cenário | Live inicial / pico / final | Histórico inicial / pico / final | Mídia inicial / pico / final | Máximo ativo oferta / mídia |
|---|---|---|---|---|
| Referência | 0 / 79 / 0 | 0 / 1000 / 0 | 0 / 1019 / 1019 | 4 / 1 |
| Sem histórico | 0 / 67 / 0 | 0 / 0 / 0 | 0 / 94 / 94 | 4 / 1 |
| Mídia falhando | 0 / 76 / 0 | 0 / 1000 / 0 | 0 / 1100 / 1100 | 4 / 1 |

Referência teve 81 fotos prontas, 1018 pendentes e uma em processamento; sem histórico, seis prontas e 94 pendentes/em processamento; mídia falhando teve 149 retries e 951 pendentes/em processamento. Todas as ofertas esperadas foram salvas, sem descarte/duplicata/falha no dataset de identidades distintas, e ambas as classes progrediram nos cenários mistos. A latência é até produto confirmado, antes da aparição/foto; medição não drena mídia ou inclui frontend.

**Limite importante:** a mudança VAL-006 adicionou a consulta/guarda local de admissão; não se atribuem estes tempos ao código posterior como novo benchmark exato. Após a correção, suíte completa e testes menores de simulação foram repetidos e aprovados. Não houve mudança nos delays de rede/workers; não se exige SLA numérico inexistente no PRD para o ciclo curto. A meta operacional de poucos segundos **continua não demonstrada nessa carga saturada**, e não se infere desempenho de VPS/Telegram/Supabase. O benchmark não exercita o adaptador de histórico, que tem testes próprios. Não comparar execuções em host não isolado como prova causal de melhoria.

#### Achados, limitações e decisão final

- **VAL-001 a VAL-005:** encerrados nesta revalidação pelas correções inspecionadas, regressões executadas e revisões independentes. O histórico abaixo permanece para rastreabilidade, não como pendência atual.
- **VAL-006:** encontrado, corrigido no ciclo curto, testado e reconfirmado independentemente; encerrado. Nenhum bloqueante/importante impeditivo confirmado permanece aberto.
- **Observações operacionais:** desempenho real e a meta de poucos segundos precisam de medição em ambiente autorizado futuro. Caminhos/usuário/venv da unit são exemplos; validação estática anterior apontou executável inexistente no WSL, não erro de sintaxe. Não houve instalação/deploy nem verificação da VPS; a unit não foi modificada neste ciclo, e sua configuração foi revisada novamente por parser/contrato.
- **Limites inerentes:** nenhuma garantia exatamente uma vez, recuperação de mensagens apagadas antes da coleta/acesso inexistente, limite absoluto em bytes dos caches/pacotes do SDK ou transação única com limpador remoto. Permanecem explícitos no README, sem mascarar os defeitos que de fato foram corrigidos.
- **Ações restantes do escopo aprovado:** nenhuma. Não há nova pergunta bloqueante, aceite parcial, mudança material de escopo ou autorização de operação remota pendente necessária à conclusão local.

**Decisão final:** `concluido` para a etapa 1 local/offline aprovada. As 21 linhas de requisitos/regras/RNF e 14 critérios estão atendidas nesse escopo, checklist/proteções completos e evidências registradas. Não significa “pronto para deploy/desempenho de produção”. Parar aqui: etapa 2 não iniciada, sem commit, push, merge ou deploy automáticos. Eventual implantação/medição real exige solicitação/autorização própria.

### Histórico da validação anterior à retomada

Esta seção preserva a contraprova que motivou a retomada. As correções e evidências novas estão na seção 15; ainda é necessária nova validação SDD final. O histórico negativo abaixo não deve ser confundido com uma avaliação posterior das correções.

Validação final iniciada em **2026-10-23** usando o runtime global SDD Lite; `_comum.md` e `validar.md` lidos integralmente. Raiz, branch `main`, commit base e aprovação da versão 1 confirmados. Todo o worktree da implementação e a entrada não rastreada eram preexistentes a este comando e estão preservados. Sem acesso a recursos remotos do usuário, staging, commit ou deploy.

Roteiro concluído: **V01 — revisão independente e verificações dirigidas**; **V02 — triagem do ciclo curto e regressões** (retorno à implementação, sem corrigir produção neste comando); **V03 — matriz e decisão final registradas**. Nenhum item foi considerado atendido apenas por resultados históricos.

### Decisão

**Validação reprovada; retorno a `em_implementacao`.** A aprovação da versão 1 permanece válida porque não se está mudando o PRD, mas exigindo seu cumprimento. Não usar `concluido` ou `parcialmente_concluido` para contornar os achados. Os 65 testes anteriores passaram novamente; reproduções adicionais demonstraram quatro bloqueantes e um importante impeditivo.

### Escopo e classificação do diff

| Categoria | Arquivos/mudanças | Avaliação |
|---|---|---|
| Prevista | Bot ativo, persistência, cache, recuperação, workers, repositório e adaptador, testes/simulação, env/README/unit | Correspondem à entrega; não significam que todo requisito esteja correto. |
| Necessária | `CLAUDE.md` sincronizando descrição de entrada/cache/testes; `.gitignore` protegendo estado local | Relacionadas à operação e preservação, sem redução de proteção. |
| Desvio menor documentado | Fila privada do Telethon 1.36 com guarda de versão; executor SQLite único; pausa de recuperação; aliases case-insensitive | Justificados no registro anterior, sem nova identidade, esquema remoto ou dependência. |
| Preexistente à validação | Todo o diff de implementação, PRD aprovado e `PROMPT_DEALBOT_ETAPA_01.md` não rastreado | Preservados; nenhum staging/revert/reset/commit. |
| Produzido nesta validação | Seção 16/checklist deste PRD e regressões de checkpoint/coleta em `bot/tests/` | Verificação do contrato existente; nenhum módulo de produção corrigido. |
| Fora do escopo | Nenhuma alteração funcional em legado/IA, backend, frontend, schema remoto, pins, deploy ou recursos do usuário | Conferido por diff e comparação com o commit base. |

### Matriz de requisitos, regras e proteções

Os resultados são restritos à validação local/offline autorizada; não aprovam produção. `parcialmente atendido` não é aceite parcial da entrega.

| Item | Resultado | Implementação/evidência da validação |
|---|---|---|
| RF-001 | atendido | `EstadoLocal.registrar/registrar_pagina`, unicidade, metadados, commit e FalhaLocal; testes de mesma mensagem e rollback de página passaram. |
| RF-002 | atendido | Workers fixos, gate/executor serial, sinais em memória e seleção justa; testes de rodízio/heartbeat e três cenários de simulação repetidos. |
| RF-003 | parcialmente atendido | SDK async/MockTransport, timeouts/backoff de jobs, HTTP 429/400 e 503 conferidos; prazo de resolver canal ainda só em memória e perdido no reinício (VAL-004). |
| RF-004 | parcialmente atendido | Oferta antes da imagem, URL nula, ID e efeito idempotente conferidos; falha permanente depois de upload confirmado perde compensação do objeto conhecido (VAL-002). |
| RF-005 | nao atendido | Página real curta provoca falsa exaustão e avanço de cursor sobre mensagens ausentes; contraprova com IDs 1–137, só 50 coletados (VAL-001). |
| RF-006 | parcialmente atendido | Cache desconhecido/`[]`, refresh e isolamento passaram; rodada com snapshot antigo inicia canal B depois da desativação já confirmada (VAL-003). |
| RF-007 | parcialmente atendido | Claims/reinício e pendências normais preservados; retenção descarta chave de objeto conhecido sem compensação e duplicata retomada vira aprovada (VAL-002/005). |
| RF-008 | parcialmente atendido | Logs JSON sem segredo, horários, duração e sinais POSIX passaram; classificação incorreta de duplicata afeta estado/log final de retomada (VAL-005). |
| RF-009 | atendido | README/env/unit/rollback e execução offline documentados; resultados negativos e limitações agora registrados nesta seção. |
| RN-001 | atendido | AST de `_normalizar`/`passa_no_filtro` inalterada; 216 comparações com funções do commit base; extrator sem IA e bytes preservados. |
| RN-002 | atendido | `dedup.py` idêntico ao commit base e janela 48h/aparições mantidas; testes de hash entre canais e retry tardio passaram. |
| RN-003 | atendido | Chave local canal numérico/mensagem e chave remota textual preservadas; schema/índices/contratos sem diff. |
| RN-004 | atendido | Reconciliação por evento anterior ao hash temporal, locks e posse durável; testes de efeito remoto ambíguo, foto/criado_em e retry >48h passaram. |
| RN-005 | atendido | Texto bruto integral fica no SQLite; somente ofertas aprovadas/campos existentes e `raw_text[:2000]` seguem ao repositório remoto; não há métricas remotas adicionais. |
| RN-006 | parcialmente atendido | Foto não impede/apaga oferta e não recria produto removido; compensação de órfão conhecido não é garantida em falha pós-upload (VAL-002), distinta da corrida inerente do limpador. |
| RNF-001 | atendido | WAL/FULL, busy timeout, transações, executor único, lock e recuperação de claims conferidos; falha de página reverte inserts e marcador. |
| RNF-002 | atendido | Quantidade de tasks/workers/página e bytes de mídia limitada; testes do transporte/download e simulação; ressalvas de pacotes/caches do SDK permanecem explícitas. |
| RNF-003 | atendido | Chamadas Supabase/Storage async com HTTP falso e SQL no executor; heartbeat progrediu nos cenários. Não equivale a cumprir SLA de poucos segundos. |
| RNF-004 | atendido | Inspeção local POSIX nova: diretório 0700, DB/WAL/SHM/lock 0600 e dono atual; sanitização e exclusão do Git conferidas, sem ler segredos. |
| RNF-005 | atendido | Entrada `python -m src.main`, pins e API/UI nullable preservados; `pip check` e SDKs no Python 3.12.3 passaram. |
| RNF-006 | atendido | Limitações/rede falsa/sem exactly-once e saturação registradas; nenhum resultado remoto/VPS/renderização é alegado. |

**Resumo dos requisitos/regras/RNF:** 14 atendidos, 6 parcialmente atendidos, 1 não atendido; os achados impeditivos inviabilizam conclusão.

### Matriz dos critérios de aceitação

| Critério | Resultado | Procedimento e evidência |
|---|---|---|
| CA-001 | atendido | Repetidos reinício com claim/pendência e efeito remoto ambíguo, sem outro card; estado da duplicata é falha distinta VAL-005. |
| CA-002 | atendido | Live e histórico do mesmo evento em testes da inbox/repositório: uma linha/claim/efeito lógico, aliases e duplicidade preservados. |
| CA-003 | atendido | Falha injetada no segundo insert: rollback integral, fronteira antiga e coleta recuperada depois de restabelecer escrita. |
| CA-004 | atendido | Download bloqueado/falhando e upload fake: oferta já salva sem foto; foto normal retomada no mesmo produto. Compensação extra é avaliada em CA-010/013. |
| CA-005 | atendido | Commit remoto com resposta perdida, reinício e retry além de 48h: um card, aparição completada, foto/criado_em preservados. |
| CA-006 | atendido | Cache inicial desconhecido não aceita tudo; `[]` válido aceita conforme regra; erro mantém snapshot, decisões e consultas independentes das mensagens. |
| CA-007 | parcialmente atendido | Adição/reativação/lista vazia/aliases passaram; remoção concorrente deixa B iniciar página depois de desativado (VAL-003). |
| CA-008 | nao atendido | Iterador real com primeira resposta de 50 e histórico 137: cursor vai a 137 sem eventos 51–137, apesar dos testes anteriores com páginas cheias (VAL-001). |
| CA-009 | atendido | Workers/rodízio/heartbeat e cenários mistos repetidos: ambas as classes progridem e respeitam limites; não comprova a cobertura histórica do adaptador Telegram. |
| CA-010 | nao atendido | Depois de upload confirmado e falha permanente no vínculo, retenção remove evento/job e chave enquanto objeto segue no fake Storage (VAL-002). |
| CA-011 | atendido | Repetidos SIGTERM/SIGINT/SIGKILL em processos Linux locais, retomada, cancelamento de mídia e cleanup com falha de disconnect. |
| CA-012 | parcialmente atendido | HTTP/timeout/erro permanente e FloodWait de coleta passaram; reinício antecipa FloodWait de resolução de canal (VAL-004). |
| CA-013 | parcialmente atendido | Unicidade, aparições, foto condicional e produto removido passaram; falha permanente pós-upload/vínculo deixa órfão conhecido e checkpoint incorreto (VAL-002). |
| CA-014 | atendido | Suíte anterior, novos contraexemplos e três benchmarks executados sem credenciais, comandos/versões/latências/limitações registrados; resultados não foram falsamente aprovados. |

**Resumo do aceite:** 9 atendidos, 3 parcialmente atendidos, 2 não atendidos. Nenhum aceite parcial da entrega foi solicitado ou inferido.

### Achados impeditivos

#### VAL-001 — Salto definitivo após resposta curta do SDK (P1, bloqueante)

- **Locais:** `bot/src/telegram.py:65-72`, `bot/src/recuperacao.py:85-92`.
- **Prova:** SDK Telethon 1.36 real com transporte falso e 137 mensagens; primeira resposta reduzida a IDs 1–50. Saída: `coletadas=50`, `cursor=137`, `limite=None`, `evento_51=None`, `evento_137=None`, uma requisição `(0,-100,100)`.
- **Causa:** mesmo abaixo do limite interno de 100, o SDK pode encerrar um iterador com resposta curta. `StopAsyncIteration` é tratado pela aplicação como prova de cobertura integral até o limite superior; a proteção anterior só cobre página cheia de 100.
- **Impacto:** mensagens ainda disponíveis são definitivamente saltadas por varreduras seguintes. Viola RF-005, CA-008 e proteção R-001.
- **Correção requerida:** tornar conservadora a conclusão de página não vazia, reconferir o restante e provar que somente exaustão verificável conclui a fronteira. Incluir a regressão real de resposta curta; não assumir contiguidade de IDs.

#### VAL-002 — Objeto conhecido órfão e perda da chave de compensação (P1, bloqueante)

- **Locais:** `bot/src/pipeline.py:112-120,201-207`, `bot/src/estado.py:330-339`.
- **Prova:** upload fake confirmado, depois `vincular_foto` lança erro permanente injetado. Estado observado: `falha_permanente`, `enviado=1`, `compensar=0`, produto com `foto_url=None`, um objeto e zero remoções. A retenção remove o evento e a mídia, perdendo a chave do objeto que continua existente.
- **Causa:** o upload confirmado zera `compensar`; uma falha permanente na etapa seguinte não reativa compensação/reconciliação antes de terminalizar. A correção anterior de upload permanente ainda não cobre vínculo permanente depois do upload.
- **Impacto:** órfão previsível/conhecido e perda do checkpoint recuperável. Não é a corrida inevitável com o limpador remoto. Viola RF-004/007, RN-006 e CA-010/013.
- **Correção requerida:** preservar intenção/motivo depois de upload, reconciliar a foto remota antes de remover o objeto e impedir retenção até a compensação concluída. Testar falha antes/depois do commit da foto para não apagar foto válida.
- **Limite da prova:** o erro permanente/HTTP 422 foi injetado; não se afirma essa ocorrência em produção.

#### VAL-003 — Nova coleta de canal já desativado (P2, bloqueante)

- **Locais:** `bot/src/recuperacao.py:67-69,78-92`, `bot/src/estado.py:148-158`.
- **Prova:** A e B ativos; página A bloqueada; refresh confirma somente A e `B.ativo=0`; liberar A ainda produz `pages_requested=['a','b']`, novo evento B e cursor B avançado.
- **Causa:** rodada mantém snapshot antigo de canais e o commit da página não confere ativação atual.
- **Impacto:** não é apenas terminar RPC já em curso: a coleta de B começa depois da desativação confirmada. Viola RF-006/CA-007.
- **Correção requerida:** revalidar ativação antes do pedido e proteger atomicamente a aceitação da página contra desativação concorrente; preservar só pendências anteriormente aceitas.

#### VAL-004 — FloodWait de resolução desaparece no reinício (P2, bloqueante)

- **Local:** `bot/src/recuperacao.py:24,45-47,62-63`.
- **Prova:** resolver sem ID lança `FloodWait(seconds=120)`; fechar/reabrir o mesmo estado e criar nova recuperação resulta em duas chamadas, com ~119,9s ainda restantes e nenhum canal persistido.
- **Causa:** o prazo fica exclusivamente em `_falhas_resolucao`; canal ainda não resolvido não possui registro no qual guardar o deadline.
- **Impacto:** reinício repete chamada antes do prazo mínimo do servidor, violando RF-003 e CA-012.
- **Correção requerida:** checkpoint durável de resolução por endereço normalizado antes de existir ID Telegram, evolução local segura e teste de restart/deadline. Isso exige armazenamento/checkpoint adicional, portanto deve voltar à implementação, não ser improvisado neste comando.

#### VAL-005 — Duplicata retomada muda para aprovada (P2, importante impeditivo)

- **Locais:** `bot/src/repository.py:160-176,183-188`, `bot/src/estado.py:265-270`, `bot/src/pipeline.py:158-160`.
- **Prova:** produto anterior em outro canal; dedup encontra ID 1; vínculo local confirmado; falha antes da aparição; reiniciar. Resultado: `estado=aprovada`, `resultado=retomado`, um card e duas aparições.
- **Causa:** o checkpoint só guarda o ID e o caminho de retomada retorna genericamente `retomado`; o pipeline o interpreta como aprovação não duplicada.
- **Impacto:** não cria outro card neste contraexemplo, mas perde a distinção obrigatória de estado/observabilidade (RF-007/008).
- **Correção requerida:** preservar ou reconstruir a classificação original de modo consistente no vínculo e na finalização, com regressão de falha de aparição/restart.

### Ciclo curto e preservação

Nenhuma correção de produção foi aplicada nesta validação. Algumas falhas isoladas admitem ajuste localizado, mas o conjunto envolve coleta/ativação, novo armazenamento de retry de resolução, checkpoints de mídia e classificação de retomada. O procedimento `validar.md` exige retorno a `sdd-implementar` quando são necessários vários blocos ou novo checkpoint/migração local. Não se alterou requisito, risco, contrato público, permissão, arquitetura ou aprovação para acomodar os defeitos.

Foram adicionados apenas testes de regressão que expressam os comportamentos já exigidos. Eles ficam intencionalmente falhando enquanto os defeitos persistirem; não foram marcados como `expectedFailure`, pulados para obter verde ou substituídos por verificações mais fracas.

### Comandos e evidências desta validação

Comandos executados a partir de `bot/`, salvo comandos Git/parser da raiz. O ambiente WSL existente continua em `/mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`, Python 3.12.3, com os pins e transitivas da seção 15; nenhum pacote foi instalado/atualizado nesta validação.

| Comando/procedimento | Resultado real | Limite/classificação |
|---|---|---|
| `git rev-parse --show-toplevel`, `git log -1 --format="%H %D"`, `git worktree list --porcelain`, `git status --short` | Base/worktree/aprovação coerentes; somente alterações locais preexistentes | Não houve staging/publicação. |
| `python -S -m unittest discover -s tests -v` em `bot/` antes de adicionar as regressões | 65 descobertos, 54 passaram, 11 skips; 33,565s | Skips esperados SDK/POSIX, cobertos pelo WSL. |
| Python 3.12.3/WSL, `python -m unittest discover -s tests -v` antes das regressões | 65 passaram, zero skips; 79,421s | Mostra que os testes anteriores não detectavam as falhas novas. |
| `python -S -m unittest tests.test_checkpoints -v` | 3 falhas de asserção em 3 testes | Reproduz VAL-002/005, incluindo efeito da foto confirmado e estado local errado. |
| `python -B -S -m unittest tests.test_validacao_coleta -v` no Windows | 2 falhas de asserção, 1 skip; 13,876s; código 1 | Falhas de desativação e FloodWait; iterador real precisa do SDK no WSL. |
| Python WSL, `python -B -m unittest tests.test_validacao_coleta -v` | 3 falhas de asserção, zero skips; 6,594s; código 1 | Confirma VAL-001/003/004 usando SDK e SQLite local reais/transporte falso. |
| `python -S -m unittest discover -s tests -q` depois das novas regressões | 71 testes: 54 passaram, 5 falharam, 12 skips; 89,506s; código 1 | As falhas são as novas regressões, não dependências/credenciais ausentes; cenário da página curta executado no WSL. |
| Python 3.12.3/WSL, `python -m unittest discover -s tests -v` depois das regressões | 71 testes: 64 passaram, 6 falharam e 1 terminou em erro de timeout; zero skips; 121,314s; código 1 | As seis falhas de asserção são os novos contraexemplos (dois do mesmo checkpoint de mídia). O erro adicional foi o watchdog de 3s do teste anterior de rajada; não foi declarado como aprovado. |
| WSL, `python -m unittest tests.test_pipeline.TestPipeline.test_rajada_concorrencia_justica_e_heartbeat -v` após a suíte | 1 teste passou; 2,024s | Reexecução isolada sem mudar/relaxar timeout; intermitência temporal do teste é registrada, sem inferir novo defeito funcional a partir de uma única execução. |
| `python -m pip check` no ambiente Linux existente | Sucesso | Sem instalar/atualizar dependências nesta validação. |
| Comparação AST do predicado/normalização e 216 entradas contra `HEAD`; bytes de extrator/dedup | Sucesso | Comparação exclui apenas o carregador síncrono removido, não regras de filtro. |
| Carregamento das variáveis dos dois `.env.example` com ambiente falso e parser da unit | 20 variáveis BOT coerentes; cinco inválidas rejeitadas; unit parseável e prazo 60s; HTTP 503 recuperável | Não lê `.env` nem inicializa serviço. |
| Inspeção SQLite em temporário POSIX local/WSL | Diretório 0700; DB/WAL/SHM/lock 0600; dono atual | Disco Linux temporário para testar permissões POSIX; não é inspeção de VPS ou NTFS. |
| AST/sintaxe/whitespace e `git diff --check` | 29 arquivos Python e PRD sem erro; avisos LF/CRLF do checkout | Inclui os dois arquivos novos de regressão. Conferência automática contou 21 requisitos/regras/RNF (14/6/1) e 14 critérios (9/3/2), coerentes com as matrizes. |
| `systemd-analyze verify --man=no --generators=no /mnt/c/Users/Alexandre_HP/Documents/DellBot/dealbot/bot/dealbot.service` | Código 1: `/home/ubuntu/dealbot/bot/venv/bin/python` não existe no WSL; avisos de permissões do checkout Windows | Limitação de ambiente/alvo de instalação, não prova de sintaxe inválida ou deploy aprovado. Nenhum serviço iniciado. |

### Simulação repetida na validação — 2026-10-23

Após as suítes anteriores, repetidos sequencialmente os mesmos três comandos da seção 15, com `python -S`, Windows/Python 3.14.4, seed 42, 100 live a cada 50ms, cinco operações lógicas de banco de 100ms, mídia 2000ms, workers 4/1 e buffer/página 100. Os dois datasets SHA256 coincidem com os registrados anteriormente. Não houve suíte completa concorrendo com o benchmark; revisões/repros locais pequenos podem ter concorrido, e o host não é laboratório isolado.

| Cenário | Ofertas salvas | Duração (s) | Ofertas/s | Live p50 / p95 / máx (s) | Histórico p50 / p95 / máx (s) | Heartbeat máx (ms) |
|---|---:|---:|---:|---|---|---:|
| Referência: 1000 histórico + 100 live | 1100 | 234,164 | 4,698 | 14,424 / 26,356 / 27,037 | 145,282 / 226,055 / 233,212 | 29,340 |
| Sem histórico: 100 live | 100 | 15,639 | 6,394 | 5,281 / 9,490 / 10,361 | não aplicável | 16,476 |
| Mídia falhando: 1000 histórico + 100 live | 1100 | 222,792 | 4,937 | 31,032 / 37,491 / 38,500 | 130,330 / 213,579 / 221,947 | 16,069 |

| Cenário | Live inicial / pico / final | Histórico inicial / pico / final | Mídia inicial / pico / final | Workers máximos oferta / mídia |
|---|---|---|---|---|
| Referência | 0 / 94 / 0 | 0 / 1000 / 0 | 0 / 1020 / 1020 | 4 / 1 |
| Sem histórico | 0 / 69 / 0 | 0 / 0 / 0 | 0 / 94 / 94 | 4 / 1 |
| Mídia falhando | 0 / 92 / 0 | 0 / 1000 / 0 | 0 / 1100 / 1100 | 4 / 1 |

Referência terminou a medição com 80 fotos prontas e 1020 pendentes/em processamento; sem histórico, seis fotos prontas e 94 pendentes/em processamento. Mídia falhando produziu 162 retries de download e nenhuma falha de gravação das 1100 ofertas; os demais jobs de imagem ainda pendiam. Nos dois cenários mistos, live e histórico progrediram antes do fim da outra classe, respeitando workers/página e sem aguardar imagem. Nenhum descarte/duplicata/falha de oferta era esperado no dataset de identidades distintas.

**Interpretação:** benchmark controlou atrasos falsos e entradas, não prova comportamento real do Telegram/Supabase/VPS ou renderização. O produtor histórico da simulação escreve diretamente na inbox; por isso o sucesso do benchmark não exercita nem absolve o salto real do adaptador de histórico (VAL-001). Confirmação da oferta é medida antes da aparição/foto; medição de vazão termina com ofertas locais finalizadas, antes do shutdown e sem drenar mídia. Rede falsa, instrumentação e host variáveis impedem extrapolar SLA/causalidade. A meta de poucos segundos não foi comprovada nessa saturação.

### Limitações, pontos positivos e próximo passo

- **Pontos positivos confirmados:** transações/rollback SQLite, isolamento async, oferta antes da foto, preservação do extrator/hash/filtros, reconciliação por evento, lock, testes POSIX e transparência das métricas. São úteis, mas não neutralizam as cinco contraprovas impeditivas.
- **Suíte expandida:** seis testes novos reproduzem cinco achados; dois testes cobrem os lados anterior/posterior ao efeito de vínculo da foto em VAL-002. Um timeout adicional e intermitente do teste antigo de rajada deve ser estabilizado/avaliado na reexecução após as correções, sem apagar as evidências ou enfraquecer as invariantes de concorrência/justiça.
- **Observações não impeditivas por si só:** não há lint/typecheck Python configurado; frontend/backend/schema não mudaram e não exigem build/E2E remoto neste escopo. Instalação systemd/caminhos reais, VPS, Telegram, Supabase e renderização não foram validados nem acessados.
- **Desempenho:** “poucos segundos” continua não demonstrado nas rajadas. O PRD não define SLA numérico garantido; registrar saturação não substitui nem agrava artificialmente os critérios funcionais que de fato falharam.
- **Decisão necessária do usuário:** nenhuma para retornar ao contrato já aprovado. Não se pede autorização para modificar recursos remotos nem se considera aceite parcial implícito.
- **Próximo comando:** `/sdd-implementar docs/sdd/incrementos/dealbot-etapa-01-coleta-confiavel.md`, corrigindo VAL-001 a VAL-005, repetindo suíte expandida, checklist/proteções e depois voltando a `sdd-validar`. A etapa 2 permanece fora do escopo.

**Encerramento desta validação:** `em_implementacao`, não concluído. Pendências objetivas são VAL-001 a VAL-005 e repetição das verificações após correção; não há pergunta bloqueante ou aceite parcial. Alterações deste comando limitam-se ao PRD e aos dois arquivos de regressão. Nenhuma correção de produção, alteração remota, commit, push, merge ou deploy foi executado.

### Autoavaliação do planejamento (histórica, anterior à aprovação)

- [x] Comportamento atual separado do desejado, com evidências que influenciam decisões.
- [x] Escopo/fora de escopo, requisitos, regras e critérios observáveis; preservada a arquitetura e dedup existentes.
- [x] Modo rigoroso e risco alto justificados; proteções focadas nas fronteiras de falha reais.
- [x] Defaults tratados como premissas; versões/fontes inspecionadas não confundidas com execução local/produção.
- [x] Única alteração planejada neste comando: criação deste PRD; entrada do usuário preservada, sem implementação.
