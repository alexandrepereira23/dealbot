---
id: dealbot-etapa-03-identidade-deduplicacao
titulo: "Dealbot — Etapa 3: deduplicação entre canais e identidade de ofertas"
status: concluido
modo: rigoroso
risco: alto
versao: 1
aprovacao: usuario
versao_aprovada: 1
aprovado_em: 2026-11-05
criado_em: 2026-11-05
atualizado_em: 2026-11-09
implementacao_iniciada_em: 2026-11-05
validacao_executada_em: 2026-11-09
concluido_em: 2026-11-09
base_branch: main
base_commit: 9a2e095203172437a66ebea062cb101cc5f524bb
---

# PRD de Entrega — Dealbot: identidade de ofertas e deduplicação entre canais

## 1. Resumo

Entregar somente a etapa 3: reconhecer ofertas por identidade forte e condições de compra, reunir divulgações equivalentes em um card, atualizar preços por recência da mensagem e resolver encurtadores em enriquecimento durável separado. Prioridades: disponibilizar rapidamente ofertas aprovadas, especialmente cupons, e evitar fusões de produtos, variantes ou condições diferentes.

`produtos` continua representando cards de ofertas, não um catálogo comercial. A entrega futura inclui migrações aditivas locais/remotas preparadas, gravação/fusão transacionais no Postgres, compatibilidade com decisões congeladas, limpeza segura, ajustes públicos mínimos e testes locais/offline. Não inclui deploy, SQL remoto, migração de imagens ou etapa 4.

Entrada integral: `PROMPT_DEALBOT_ETAPA_03.md`. O PRD foi criado inicialmente em comando exclusivo de planejamento, sem implementar código. A invocação posterior explícita de `sdd-implementar` aprovou a versão1 em2026-11-05 e autorizou implementação local. A primeira validação formal encontrou V-ET3-001 e devolveu a entrega à implementação; a retomada corrigiu a colisão numérica e as guardas legadas. **A revalidação, iniciada em2026-11-06 e encerrada em2026-11-09, aprovou os56 itens da matriz no escopo local e marcou `concluido`.** V-ET3-001 encerrado, sem bloqueantes abertos. A reprovação anterior, suas matrizes/falhas e a correção permanecem históricas na seção16; a matriz corrente está ao final dela. Não significa publicação ou aprovação do ambiente de produção. O documento é autossuficiente e não depende da conversa nem da presença do prompt não rastreado.

### Política proposta, em poucas linhas

- **Identidade:** evento = canal Telegram numérico + mensagem; produto/variante por evidência forte da loja; oferta = produto/variante + loja/anúncio/vendedor + condições comprovadamente equivalentes. Incerteza mantém cards separados, sem fallback novo por título/foto/preço.
- **Atualização:** preço não faz parte da identidade estável. A observação original mais recente, com desempate determinístico, atualiza tanto subidas quanto quedas; cupom omitido não apaga código anterior nem comprova equivalência.
- **Expiração:** janela inicial configurável de 48h desde a última aparição realmente nova, válida e mais recente, pelo horário original. Retry não renova; após expirar, nova mensagem pode iniciar outra instância, sem deslocar eventos antigos.
- **Migração:** SQLite posterior à v5 e Supabase aditivos, sem recalcular decisões/hashes antigos ou fundir histórico em massa. Prontidão explícita; incompatibilidade preserva pendências. Aplicação em produção depende de autorização futura.

## 2. Classificação

- **Modo: `rigoroso`.** Envolve arquitetura de persistência entre SQLite/Postgres/Storage, segurança de requisições externas, migração e contratos públicos.
- **Risco: `alto`.** Falsa fusão pode ocultar vendedor/restrição, preço vencido pode induzir compra incorreta, corrida pode perder origens/fotos e um resolvedor inseguro pode alcançar serviços internos.
- **Proteções adicionais:** testes SQL com sessões independentes; limites e defesa SSRF no transporte; migrações/preflight/rollback; compatibilidade congelada; coordenação de limpeza/fusão/mídia; evidências de regressão e desempenho. Permanecem neste PRD, sem TechSpec, ADR, tasks ou relatório separado obrigatório.

## 3. Contexto e comportamento atual

### Comportamento confirmado e evidências

| Evidência inspecionada | Constatação que orienta a entrega |
|---|---|
| `git rev-parse --show-toplevel`, `git status --short --branch`, `git log -1`, `git worktree list --porcelain` | Raiz `C:/Users/Alexandre_HP/Documents/DellBot/dealbot`; único worktree listado; `main` no commit base do cabeçalho, acompanhando `origin/main`; nenhum arquivo rastreado modificado. Cinco prompts preexistentes não rastreados, das etapas 1, 2 e 3, devem ser preservados. |
| `CLAUDE.md`, `README.md`, `bot/requirements.txt`, manifests Node | Caminho ativo `bot/src/`, Python 3.12 recomendado, Telethon 1.36.0/Supabase 2.9.1/dotenv 1.0.1; backend Express MVC; frontend Next 14.2.5. Não reativar `bot/bot.py`/Gemini. Identificadores e documentação em português. |
| `bot/src/dedup.py:13-56` | Hash de link normalizado + preço ou título + preço. Reduz toda URL a minúsculas, remove parâmetros universalmente, ordena query, perde vazios/fragmentos/barras. `smid` é removido; `linkCode` na lista não coincide com comparação `k.lower()`; preço zero e ausente produzem o mesmo componente vazio. |
| `bot/src/repository.py:17-42,107-153,169-245` | Janela fixa 48h por `criado_em`; locks Python em uma instância; busca de hash e upsert/aparição em chamadas separadas. Reconciliação de evento remoto usa canal textual/aliases e não tem janela; a unicidade atual não protege ofertas equivalentes entre conexões independentes. |
| `bot/src/pipeline.py:149-199`, `bot/src/estado.py:329-374` | Decide/congela produto, diagnóstico e hash antes da rede; retry lê decisão sem refiltrar; reserva de hash e vínculo remoto duráveis; oferta precede mídia. Preservar esses checkpoints, distinguindo identidade nova de hash legado. |
| `bot/src/estado.py:73-145,412-430` | SQLite WAL/FULL, executor serial limitado, migrações até v5, chave numérica canal/mensagem, fila de mídia e limpeza em lotes. `resolucoes` atual é de usernames Telegram, **não** cache de URLs; não reutilizar seu significado. |
| `bot/src/modelos.py:12-24`, `bot/src/extractor.py:12-18,458-484` | Envelope já contém `data_origem`, recepção e contexto de links; produto público tem título/preços/cupom/link/categoria. Não há identidade estruturada suficiente de vendedor/variante/restrições; será necessário derivado interno conservador, sem mudar decisões já congeladas. |
| `supabase/schema.sql:7-49,130-154` | `produtos` tem `data_oferta` e hash legado; aparições referenciam produto com DELETE CASCADE; unicidade remota é canal textual/mensagem. Não existem aliases de cards, observações versionadas, expiração explícita ou RPC desta etapa. RLS habilitada; políticas atuais de produtos/aparições são de leitura autenticada. |
| `backend/src/models/produto.model.js`, `backend/src/services/produto.service.js` | Lista/detalhe incluem aparições e projetam `canais`; estatísticas contam todas as linhas; ordenação usa `data_oferta`/`criado_em`. Não há resolução de ID fundido. Detalhe converte indiscriminadamente erros de consulta em 404; distinguir indisponibilidade é necessário no contrato novo. |
| `backend/src/services/limpeza.service.js`, `backend/src/config/env.js:34-35`, `backend/src/server.js:11-15` | Limpeza seleciona por `criado_em`, default 48h, remove fotos antes das linhas, em lotes 500. Pode concorrer consigo e com bot; não verifica uso da foto por outro card. Não pode continuar assim para ofertas atualizadas/fundidas. |
| `frontend/lib/types.ts`, `frontend/components/ProdutoCard.tsx` | Preços number/null, lista de canais opcional, foto nula suportada; desconto usa preço anterior anunciado (`preco_original`). Não há campos próprios de atualização/queda. |
| `bot/tests/test_repository.py:255-265`, testes de pipeline/checkpoints/decisões/retenção | Teste concorrente atual compartilha o mesmo repositório e fake; não prova isolamento Postgres. Existem regressões de hash congelado, resposta perdida, aliases de canal, fotos e migração que precisam continuar cobertas. |
| `backend/package.json`, `backend/tests/sql-etapa2.local.mjs`, `frontend/package.json` | API/UI usam `node --test`; SQL existente testa apenas filtros com psql ou PGlite. Runner atual não comprova duas sessões simultâneas. Frontend tem lint/build/tipos; não há lint Python nem build/lint backend configurados. |
| `bot/simulacao.py:132-182,232-362` | Simulação modela cinco operações lógicas para ofertas distintas, não dedup real; mede confirmação do produto antes de aparição/foto. Deve manter cenário comparável e acrescentar cenários que exercitem efetivamente identidade/enriquecimento. |
| `docs/sdd/incrementos/dealbot-etapa-01-coleta-confiavel.md`, `dealbot-etapa-02-extracao-filtros.md` | Ambos têm estado `concluido`; registrar aqui somente a etapa 3. Restrições antigas de manter o algoritmo de dedup eram específicas das etapas anteriores; suas proteções de durabilidade/filtros continuam obrigatórias. |

Não foi encontrado `AGENTS.md` na árvore do workspace. Não há `.sdd-lite` na raiz; runtime escolhido `C:/Users/Alexandre_HP/.config/opencode/.sdd-lite`. Foram lidos integralmente `prompts/_comum.md`, `prompts/planejar.md` e `templates/prd-entrega.md`. Não existe PRD anterior da etapa 3 em `docs/sdd/incrementos/`.

### Fontes primárias consultadas e limites da evidência

Consultas públicas somente de leitura em 2026-11-05, sem canais/contas do usuário:

- [Modelo oficial Amazon Catalog Items 2022-04-01](https://raw.githubusercontent.com/amzn/selling-partner-api-models/main/models/catalog-items-api-model/catalogItems_2022-04-01.json), definições `Item`, `ItemRelationship` e `ItemVariationTheme`: ASIN é identidade de catálogo; há relações pai/filho, temas de variação e hierarquia de embalagem. Isso **não** comprova vendedor, variante selecionada ou condições de uma URL pública. A tentativa de consultar a página genérica `developer-docs.amazon.com/sp-api/docs/identifiers` retornou “Page Not Found” e não é evidência de regra.
- [Documentação oficial Mercado Livre — Variações](https://developers.mercadolivre.com.br/pt_br/variacoes): um anúncio pode conter cores/tamanhos distintos; exemplos distinguem item, `seller_id`, `variations[].id`, `catalog_product_id` e `SELLER_SKU`. Portanto anúncio e catálogo, isoladamente, não autorizam apagar seleção de variante. Exemplos da documentação não são mensagens reais do usuário nem justificam copiar preço ou presumir contratos de query pública.

Os formatos de URLs e parâmetros que se tornarão suportados ainda precisam de fixtures sintéticas e justificativa específica na implementação. Essas fontes justificam **separação de conceitos**, não suporte completo de Amazon/Mercado Livre, nem autorização para chamar APIs autenticadas dessas lojas.

### Não confirmado neste planejamento

- Os 257 testes bot, 40 API e 7 UI são referência informada no pedido, não execução desta sessão. Registros históricos do PRD da etapa 2 não substituem baseline no commit atual.
- Não foram executados testes, simulação, lint ou build. Disponibilidade atual de Python 3.12/WSL, Postgres com múltiplas sessões, SDKs e toolchains não foi revalidada.
- Não foram lidos `.env`, estado privado SQLite ou credenciais; não foram consultados Telegram, Supabase do usuário, VPS ou páginas comerciais para preço. Schema/dados/latência de produção permanecem desconhecidos.
- Não foi identificado corpus real fornecido que comprove formatos de vendedores/encurtadores do usuário. Usar somente fixtures declaradamente sintéticas; não inventar amostras reais.

## 4. Problema e objetivo

**Problema:** o hash atual mistura identidade com preço, perde informação da URL e permite fusões por título. Encurtadores distintos escapam. Nova mensagem com outro preço não atualiza coerentemente a oferta. Faltam transações entre sessões, tempo próprio de validade e referências estáveis após fusão; a limpeza atual pode apagar oferta/foto ainda necessária.

**Objetivo observável:** para os formatos efetivamente suportados, eventos idempotentes e observações equivalentes convergem para um card ativo por instância, com origens preservadas e preço coerente com a data original. Conflitos/incertezas ficam separados e explicáveis. Rede de enriquecimento pode falhar ou permanecer bloqueada enquanto a oferta aprovada já está salva. Todas as garantias serão verificadas localmente, sem alegar dedup perfeita de links opacos ou SLA de VPS.

## 5. Escopo

### Incluído

- Identidades versionadas; normalização URL pura; extratores explícitos por loja; condições, variantes e vendedor tratados conservadoramente.
- Cache persistido de URLs, fila SQLite e workers de enriquecimento independentes/limitados, segurança de rede e retries/checkpoints.
- Transação remota de registrar/reutilizar oferta, evento/aparição e observação; fusão atômica; alias persistente e exclusão sem ressurreição.
- Recência de preço, metadados mínimos de atualização/queda, validade/instâncias e retenção compacta compatível com pendências.
- API/lista/contagem/detalhe/exclusão/limpeza e tipos/card apenas no mínimo necessário.
- Migrações aditivas preparadas/testadas localmente, compatibilidade legada, documentação, testes e medições comparáveis.

### Fora do escopo

- Commit, branch, push, PR, merge, deploy ou alteração remota; implementação sem aprovação explícita. O comando original de planejamento não autorizou código; a implementação posterior foi aprovada nos termos do cabeçalho.
- Etapa 4: realtime, redesign, nova tela de histórico/comparador, alertas, favoritos ou migração de imagens. Storage permanece no adaptador Supabase existente.
- IA, busca semântica, embeddings, similaridade de título/foto como identidade, catálogo completo ou troca de stack/plataforma de filas.
- Scraping, extração de preço em loja, JavaScript/browser no resolvedor, login/cookies/credenciais de loja ou acesso a canais para amostras.
- Fusão/backfill/reclassificação automática em massa do legado; varredura destrutiva de bucket/base. Diagnóstico opcional será somente dry-run.
- Várias ofertas por mensagem, suporte novo a edições/álbuns, múltiplos coletores em produção ou revisão geral de autenticação/filtros.

## 6. Requisitos

### Funcionais

#### RF-001 — Identidades e incerteza explícitas

- Evento novo usa `(canal_id_telegram, telegram_msg_id)` numéricos, estáveis em live/histórico/retry; username serve para exibição e compatibilidade, nunca substitui esse par.
- Representar separadamente produto/variante, oferta/instância e aparição, ainda que compartilhem tabelas. Distinguir catálogo, anúncio, seller e SKU/variação quando fornecidos. Conservar fonte, versão, nível de confiança e motivo de separação/reutilização.
- Identidade de oferta inclui loja/marketplace, produto/variante, anúncio/vendedor quando necessários e condições relevantes: estado novo/usado, kit/quantidade, elegibilidade, pagamento, cupom/restrições e outras evidências que mudem a compra. Preço é observação, não chave estável.
- Campos têm estados distinguíveis: conhecido, desconhecido e não aplicável comprovado. Nulo não é curinga nem prova de igualdade. Conflito conhecido impede fusão, mesmo com mesmo ID de catálogo; nunca remover campo conflitante para fabricar chave igual.
- Sem prova suficiente, usar identidade provisória isolada por evento; título, imagem, preço ou igualdade de URL opaca sozinhos não autorizam fusão cross-evento. Idempotência do mesmo evento independe dessa incerteza.

#### RF-002 — Normalização e extratores locais

- Separar link original navegável da representação de comparação. Normalizar esquema/host pelas regras de URL; não reduzir caixa de path/token/query/fragmento, mudar esquema/domínio/barra final, decodificar tokens ou reordenar/reconstruir query indiscriminadamente.
- Preservar ordem, parâmetros repetidos/vazios, nomes desconhecidos sensíveis à caixa e percent-encoding relevante. URL assinada/fragmento potencialmente semântico fica intacta na parte sensível; se não houver regra segura, não agrupar.
- Tracking só sai sob regra explícita de domínio/formato testada. `ref`, `tag`, `aff`, `smid` e semelhantes não são descartáveis universais. Corrigir `linkCode` com regra de comparação explícita apenas onde justificada; isso não autoriza casefold de todos os nomes.
- Implementar extratores pequenos por loja, com formatos aceitos, exemplos positivos/negativos sintéticos e fontes/limites documentados. Priorizar um subconjunto justificável de Amazon e Mercado Livre; aceitar o host não significa suportar todas as suas URLs.
- ASIN ou catálogo sem seller/seleção suficiente é candidato de produto, não oferta equivalente. Anúncio com múltiplas variações exige seleção inequívoca; SKU é contextual ao vendedor, não chave global. Texto pode registrar atributos/conflitos/restrições explícitos, mas semelhança textual nunca cria identidade forte.
- Uma regra de URL pública não comprovada pode permanecer não suportada, mas a entrega deve demonstrar dedup positiva com formatos fortes suportados, além dos casos conservadores. Não entregar somente um parser que separa tudo.

#### RF-003 — Registro de evento, aparição e observação atômicos

- Operação transacional no Postgres decide reutilizar/criar a instância reconhecida, registra evento/aparição único e observação, aplica atualização e retorna ID canônico/status. Não usar SELECT/INSERT soltos como garantia.
- Serializar por evento e identidade apropriada, inclusive quando não existe card ainda; índices/chaves e locks de banco protegem conexões independentes. Lock Python é otimização. Não usar índice parcial com `now()`.
- Conferir primeiro vínculo do evento, sem recorte de 48h: evento previamente confirmado permanece na instância anterior, mesmo após expiração ou criação de outra instância.
- Resposta perdida após commit permite retry idempotente, sem observação/aparição adicional. Payload do mesmo evento incompatível com decisão persistida gera diagnóstico, não uma segunda gravação ou substituição silenciosa.
- Distinguir resultado novo, reutilizado, atualizado, retomado, removido e aguardando schema conforme necessário, mantendo checkpoint durável antes da confirmação local final.

#### RF-004 — Preços e condições observadas

- Observar preços em centavos/Decimal e publicar number/null. Zero é conhecido; nulo não vira zero. Subida e queda conhecidas atualizam o card se a observação vencer pela política temporal.
- Guardar horário/fonte do preço atual; preço conhecido anterior à atualização e indicador de queda são conceitos próprios. `preco_original` continua sendo o “de/antes” anunciado da observação correspondente, não a última versão do preço do card.
- Observação mais recente com preço desconhecido não inventa preço nem queda: o card passa a preço atual desconhecido se essa observação substituir a anterior; valor conhecido precedente, se retido, fica apenas como metadado explicitamente datado, nunca preço vigente ocultamente vencido. Não comparar nulo com zero para indicador de queda.
- Cupom e restrições são preservados com grafia/fonte. Código omitido é desconhecido, não remoção nem equivalência com “sem cupom”. Códigos diferentes/condições distintas ficam separados, salvo prova explícita de equivalência, registrada e testada. Não inferir equivalência pelo preço.
- Coletar restrições claras disponíveis na mensagem/contexto sem nova rede ou reavaliação de filtros. Se não for possível demonstrar compatibilidade, separar; não copiar cupom/preço entre ofertas incertas.
- Observações/mudanças compactas, uma por evento, têm retenção configurável; sem histórico público infinito.

#### RF-005 — Tempo, validade e instâncias

- Separar data original da mensagem, primeira ingestão, data original da observação de preço, confirmação do efeito remoto e última aparição válida. Datas persistidas em UTC; relógio de ingestão não determina preço/validade.
- Comparar observações pela ordem total `(data_original_valida, canal_id_telegram, telegram_msg_id)`, com comparação numérica crescente para desempate; maior tupla vence. Empate temporal é política determinística, não evidência de que um canal chegou antes. Mesma data sem identificadores/temporalidade confiáveis guarda observação, sem substituir arbitrariamente.
- Observação com data ausente/inválida/futura não comprovada não ganha recência nem renova. Não substituir sua data pelo relógio atual; registrar motivo. Extrato antigo recuperado hoje não vence observação recente.
- Janela inicial 48h, configurável e compartilhada por gravação/fusão/API/limpeza. `expira_em = ultima_aparicao_valida_em + janela`. Somente evento novo que avance a última data válida de uma instância ainda elegível prolonga validade; retry não altera datas.
- Se houver lacuna que encerrou a instância, mensagem posterior inicia outra. Não reativar instância vencida pelo relógio de recepção. Histórico atrasado é vinculado à instância temporal compatível quando comprovada; se não houver, permanece observação/instância histórica não ativa, sem invadir a atual.
- Alterar janela de configuração não reatribui eventos nem recalcula silenciosamente expirações já congeladas: guardar janela aplicada à instância; nova configuração vale para novas instâncias. Fusões não atravessam instâncias expiradas/incompatíveis.

#### RF-006 — Cache, fila e enriquecimento isolado

- Fluxo: identidade local → cache persistido válido → salvar/reutilizar oferta → fila durável de resolução desconhecida → enriquecimento → reconciliação transacional. Nenhum HTTP/DNS de loja/encurtador precede confirmação da oferta aprovada.
- Cache positivo guarda URL final, identidade verificável, versão da regra e expiração; negativo guarda estado/motivo e retry possível após expiração. Chave preserva tokens/caixa/semântica da URL. Reinício reutiliza cache válido sem resolução adicional no worker de oferta.
- SQLite mantém jobs por URL/evento e seu produto/instância, estados/claim/tentativas/próxima execução, resultado de resolução e checkpoint de reconciliação. Separar resolver de reaplicar resultado remoto: falha na fusão não exige refazer rede já confirmada.
- Workers de enriquecimento são fixos e independentes de oferta/mídia, com cliente/pool/orçamento próprios; sem task por mensagem ou fila em memória proporcional ao backlog. Compartilhar executor SQLite serial sem monopolizá-lo; operações/limpeza em lotes limitados.
- Timeout/falha/domínio não suportado mantém oferta visível com original, sem rejeitar/ocultar. Resultado sem identidade verificável não substitui o original nem dispara fusão. Duas URLs opacas podem gerar cards provisórios até resolução comprovada; cache conhecido permite dedup imediata quando os demais campos forem equivalentes.
- Encerramento devolve claims/checkpoints, respeita orçamento finito e retomada. Resolução impossível não entra em loop infinito; diagnóstico distingue terminal do ciclo, negativo temporário e reconciliação ainda pendente.

#### RF-007 — Transporte seguro e limitado

- Somente HTTP/HTTPS, portas 80/443 correspondentes e hosts explicitamente suportados por allowlist exata ou subdomínio com limite de label. Rejeitar userinfo, hosts malformados e protocolos/portas alternativos; sem navegador/JS/login/segredos/cookies de conta.
- Validar URL e todos os endereços DNS em **cada salto**, inclusive primeiro e destinos relativos; rejeitar loopback, privados, link-local/metadata, IPv6 local, IPv4 mapeado e demais endereços não públicos. Destino resolvido precisa ser o IP validado usado pela conexão, com Host/SNI/TLS corretos; validar DNS e deixar o cliente resolver de novo não basta contra rebinding.
- Desabilitar redirects automáticos não validados, proxies de ambiente e propagação de Authorization/cookies. Detectar loops; limitar DNS, connect/read, tempo total, redirects e bytes lidos/decodificados. Não tornar uma resposta “segura” só por retornar status 200.
- Preferir HEAD; fallback controlado para HEAD não suportado, sem GET de corpo irrestrito. Se usar Range, não confiar que servidor respeitará: streaming deve parar/fechar ao limite, inclusive corpo comprimido/resposta sem Content-Length. Não extrair preço/HTML de produto.
- Os testes usam DNS/transporte falsos e afirmam que destino proibido não recebeu conexão. Se o transporte seguro não puder ser garantido com a biblioteca escolhida, parar antes de habilitar rede de resolução, sem aceitar implementação vulnerável.

#### RF-008 — Fusão, aliases e mídia

- Fusão recebe evidência própria do enriquecimento, sem alterar decisão original; reverifica identidade completa, conflitos e compatibilidade temporal dentro da transação.
- Escolher sobrevivente determinístico: menor ID numérico dentre instâncias compatíveis e não removidas, sem trocar esse critério conforme preço/foto. Travar identidades/cards em ordem consistente; transferir explicitamente todas as aparições/observações antes de aposentar o perdedor. Não depender de DELETE CASCADE.
- Persistir alias para ID canônico, sem ciclos e com resolução limitada/determinística; cadeias devem convergir. Preservar origem dos IDs e motivo da fusão. Retry com qualquer ID antigo deve resolver o mesmo sobrevivente ou estado removido, nunca criar outro card.
- Preservar foto válida e dados mais completos sem juntar condições incompatíveis. Em duas fotos válidas, manter a do sobrevivente; se ausente, adotar a do perdedor. Guardar referência da foto adotada, independentemente de qual ID aparece no nome do objeto.
- Jobs de oferta/mídia/enriquecimento e compensações consultam alias antes de operar. Remover foto só com verificação/proteção de referência atual; objeto adotado não é sobra do perdedor. Foto concorrente não pode ser apagada por compensação que consultou ID antigo.
- SQL é tudo-ou-nada; queda antes/depois do commit e resposta perdida são retomáveis pelo checkpoint de fusão. Exclusão/limpeza concorrente registra estado terminal antes de remover e vence enriquecimento tardio; não ressuscitar removido.

#### RF-009 — API, card e exclusão compatíveis

- Preservar métodos/rotas atuais e campos de produto/preço/cupom/link/canais/foto. Lista e estatísticas usam a mesma elegibilidade, contando só instâncias ativas/canônicas; não listar perdedores/expirados como ofertas atuais.
- `GET /api/produtos/:id` antigo retorna representação do canônico existente, com seu ID, canais e preço vigentes; removido/expirado indisponível retorna 404 coerente. Falha de schema/banco não vira falso 404.
- `DELETE` por alias resolve e remove logicamente a instância canônica e seus aliases na mesma decisão transacional; não apaga outra instância temporal da mesma identidade. Retry/enriquecimento/mídia não desfazem a exclusão. Conservar marca mínima para pendências.
- Expor apenas os metadados mínimos necessários de atualização/preço anterior à atualização/queda/validade. Projetar colunas públicas explicitamente para não vazar identidade interna, payload de RPC ou diagnóstico privado via `select('*')`.
- Card pode indicar atualização/queda real com ajuste localizado em tipos/renderização; não usar `preco_original` para esse indicador nem alterar percentual anunciado artificialmente. Sem realtime ou tela de histórico.

#### RF-010 — Retenção e limpeza coordenadas

- Limpeza usa `expira_em`/estado canônico nas instâncias novas, não somente `criado_em`. Legado sem identidade nova conserva política explicitamente documentada por `criado_em`; não se torna identidade confiável por migração.
- Separar expirar/ocultar card, remover dados de apresentação e purgar referências. Aliases, mapa de evento/instância, observações necessárias, jobs/compensações e referências de mídia não podem ser apagados enquanto houver trabalho recuperável que dependa deles.
- Estabelecer protocolo durável mínimo de referência recuperável entre jobs locais e remoto, confirmado/retomável, para limpeza não depender de inspecionar SQLite inacessível à API. A retenção de um job pendente é exceção de recuperação, não histórico infinito. Falta de confirmação não pode expirar silenciosamente e permitir duplicata; expor idade/contagem para diagnóstico.
- Após terminalização/ack durável, purgar em lotes pequenos por retenções configuráveis. Preservar resumo atual de preço/recência/validade mesmo após compactar observações antigas. Explicar limite: sem estado local e sem registros remotos retidos não existe dedup eterna de replay arbitrário.
- Remoção física de mídia é retomável e apenas para chaves conhecidas elegíveis, após decisão transacional impedir nova referência à chave candidata; conferência seguida de DELETE soltos não protege corrida. Falha do Storage não deve perder tarefa de remoção nem reativar card.
- Impedir sobreposição não coordenada de limpadores. Sem varredura geral de bucket/base, cascata destrutiva durante fusão ou expurgo de pendências pelo relógio.

#### RF-011 — Migração, prontidão e compatibilidade congelada

- Preparar SQL remoto aditivo/idempotente, com preflight e privilégios restritos; executá-lo somente em banco local descartável. SQLite migra aditivamente versões suportadas até v5 para versão posterior, preservando IDs/fronteiras/aliases de canais/estados/tentativas/decisões/hashes/mídia/contexto.
- Identidade nova tem versão separada do `dedup_hash` legado. Decisões antigas continuam usando dados/hash congelados; se decisão antiga não tem hash, fallback usa somente algoritmo legado e produto congelado, nunca extrator/filtros novos. Nova decisão não usa fallback por título do legado.
- Jobs antigos podem reconciliar evento/vínculo pelos aliases textuais existentes antes de qualquer nova criação. Seu caminho legado é delimitado e testado; não adota algoritmo novo no restart nem reclassifica registros existentes.
- Enriquecimento tem versão/evidência/checkpoint próprios; não reescreve a decisão original aprovada. Backfill não é automático; se disponibilizado, comando opcional somente diagnóstico/dry-run, sem escrita remota.
- Prontidão confere colunas/funções/versões/permissões necessárias. Schema ausente/parcial gera incompatibilidade visível, preserva trabalho e não declara sucesso nem retorna silenciosamente à comparação insegura por título.
- Serialização/deadlock/indisponibilidade temporária usam retry idempotente com backoff/jitter e limite de tentativas imediatas; esgotar orçamento retorna job ao retry durável, não descarta promoção. Sem loop ocupado ou retries internos multiplicados sem limite.

#### RF-012 — Diagnóstico e documentação de entrega

- Matriz de decisões, formatos suportados/exemplos/limites, semântica de desconhecido, preço/tempo/expiração, cache/provisórias e retenções documentados.
- Diagnóstico deve permitir explicar unir/separar: versão/regra de identidade, IDs de evento/card/canônico, campos conflitantes por nome e motivos, estado de resolução/fusão e tentativas. Logs não contêm texto completo, cupom, URL/token/query completos, segredos ou dados privados de filtros.
- Documentar aplicação futura, ordem segura, prontidão, rollback e proibição de rodar limpador antigo com dados novos. Registrar comandos/resultados reais, falhas/skips/limitações sem excluir testes para obter verde.
- Conclusão futura informa: resumo/arquivos, política com exemplos/limites, testes/medições, migrações preparadas e dependências de produção, decisões para etapa 4 e continuidade curta. Encerrar na etapa 3.

### Regras de negócio

- **RN-001:** mesmo evento tem um efeito e vínculo estável, independente da janela; idempotência precede dedup comercial.
- **RN-002:** preço é observação; identidade forte e equivalência das condições autorizam reunião; qualquer conflito conhecido impede.
- **RN-003:** desconhecido não é zero, sem cupom, vendedor padrão, qualquer cliente ou variante única. Ausência não comprova igualdade.
- **RN-004:** oferta disponível antes de DNS/HTTP de enriquecimento e mídia; falha desses passos nunca invalida aprovação.
- **RN-005:** tempo original governa atualização/validade; retry e ingestão tardia não renovam. Vínculo de evento não migra para nova instância.
- **RN-006:** fusão não perde aparições/observações/foto usada; alias antigo não ressuscita card; exclusão terminal prevalece.
- **RN-007:** retenção curta não elimina referências de trabalho ainda recuperável nem promete idempotência sem evidência retida.
- **RN-008:** evolução nova não recalcula hash/decisão legada nem reabre histórico em massa; restrições das etapas 1 e 2 continuam cobertas.

### Requisitos não funcionais

- **RNF-001 — Recursos finitos:** workers, pools, memória por resposta, hops, timeout, tentativas e lotes configuráveis/validados. Sem task por evento, rede ilimitada ou espera de resolvedor no caminho de ofertas.
- **RNF-002 — Segurança:** RPCs preferencialmente SECURITY INVOKER; revogar EXECUTE de PUBLIC/anon/authenticated nas funções novas, inclusive auxiliares; conceder somente ao papel necessário ao bot (service_role atual). RLS não é relaxada; tabelas internas sem nova permissão pública. Testes verificam negação e acesso permitido.
- **RNF-003 — Compatibilidade:** stack/entrada ativa/MVC preservados; payloads públicos mínimos e tipos compatíveis; `raw_text` remoto continua limitado, derivado interno não vaza no JSON da API.
- **RNF-004 — Durabilidade:** WAL/FULL, executor SQLite serial, prioridade live/justiça histórica, checkpoints, recuperação paginada, sinais/shutdown e compensação preservados. Falha local não simula aceitação.
- **RNF-005 — Evidência:** testes reais de banco para atomicidade, rede falsa para resolver, mesma carga/dataset para comparar; relatar skips/falhas/ambiente. Não prometer exactly-once eterno nem latência real por simulação.

## 7. Experiência e matriz de decisões

Fluxo principal: evento persistido → filtros locais já existentes → congelar decisão/identidade → cache local → transação remota → confirmar disponibilidade → mídia e resolução independentes → eventual fusão atômica → API retorna card canônico.

Todos os exemplos abaixo são sintéticos e pressupõem identidade forte/condições comprovadas quando indicado.

| Situação | Resultado esperado |
|---|---|
| Mesma oferta e condições, preço igual, novo canal | Um card e outra aparição, não outra observação do mesmo evento. |
| Mesmo evento live/histórico/retry, inclusive após 48h | Mesmo vínculo/efeito; não altera validade nem move para nova instância. |
| Nova mensagem mais recente, 300 → 250 | Mesmo card, preço 250 e metadado próprio de queda de 50; `preco_original` não vira 300 por isso. |
| Nova mensagem mais recente, 250 → 300 | Mesmo card, preço 300; não manter 250 como atual. |
| Observação antiga 200 chega após a mais recente 300 | Registrar observação antiga, preço atual continua 300, sem renovação por ingestão. |
| Observação realmente mais recente sem preço | Atual desconhecido, sem zero/queda fictícia; preço conhecido antigo apenas datado, se retido. |
| Mesmo produto, outra loja/seller; outro kit, quantidade ou variante | Cards separados e motivo de conflito. |
| Primeira compra versus qualquer cliente; Pix versus condição incompatível | Cards separados; não apagar restrições para unificar. |
| Cupom `AbC10` versus `XYZ10`; cupom omitido | Sem equivalência automática; omissão desconhecida não limpa o código. |
| Mesmo título/foto/preço, IDs de produto diferentes ou ausentes | Não fundir; provisório por evento quando incerto. |
| Dois encurtadores desconhecidos, destino equivalente comprovado depois | Duplicatas provisórias disponíveis antes da rede; depois um ativo, duas aparições, aliases preservados. |
| Cache positivo válido após restart | Dedup local imediata para oferta equivalente, sem aguardar rede. |
| Falha/timeout/URL não suportada | Card original permanece; diagnóstico/cache negativo e retry com orçamento. |
| Instância expirada, mensagem realmente posterior | Nova instância; retry antigo continua na anterior ou em seu estado terminal. |
| ID perdedor consultado/removido | Resolver canônico; detalhe/exclusão coerentes, sem outro card ativo. |

Sem garantia de ausência imediata de duplicatas quando falta informação; sem bloqueio da oferta para resolver essa incerteza. Erro de schema mantém pendência explícita; erro de banco da API não é “produto inexistente”.

## 8. Impacto técnico e desenho proposto

### Modelo mínimo, sem catálogo novo

Nomes de campos/tabelas novos abaixo são **propostos**, não caminhos ou schema existentes. Podem ser ajustados internamente mantendo todos os contratos e registrando a decisão.

| Estrutura | Evolução proposta |
|---|---|
| `produtos` existente | Continua card/instância; acrescentar versão/representação de identidade, chave reconhecida ou provisória, estado canônico/removido, início/última aparição válida/expiração, observação vencedora e metadados próprios de atualização. Preservar colunas públicas/legadas. |
| `produto_aparicoes` existente | Acrescentar canal numérico nullable para legado e unicidade de evento novo; datas original/ingestão/observação, dados compactos observados/proveniência. Pode abrigar observações por evento, evitando tabela de histórico separada; não apagar informação da fusão por cascata. |
| Registro de identidade/instância, novo | Linha/chave estável que possa ser travada antes de haver card; aponta instância atual e permite decisão serializada de expiração/nova instância. Chave de lock pode ser mais ampla que identidade, mas não apaga conflitos na decisão. |
| Aliases/terminalização, novos | ID antigo → canônico/estado removido; regra anti-ciclo e referência recuperável. Pode conservar linha mínima do perdedor em vez de tabela adicional se a semântica e retenção forem equivalentes. |
| Referências/remoção de mídia | Checkpoint durável mínimo para proteger objetos ainda referenciados e retomar limpeza conhecida. Não é nova plataforma nem migração de armazenamento. |
| SQLite posterior à v5 | Versão de identidade nova separada, cache/fila de URL e checkpoint de reconciliação/ack; não confundir com `resolucoes` de canais nem reescrever decisões antigas. |

Não criar tabela separada de produto global/vendedor/SKU/catálogo por padrão. Representação estruturada pequena e versionada permite distinguir conceitos sem construir catálogo. Índices estáveis por evento, identidade/instância, alias e expiração; nenhuma expressão temporal volátil em índice parcial.

### Transações e contratos

- Gravação e fusão por RPCs Postgres propostas, idempotentes e SECURITY INVOKER. Campos de entrada/saída são versionados, validados e projetados explicitamente; schema completo é requisito de prontidão.
- Gravação trava evento/registro da identidade, reconcilia vínculo anterior, avalia instância/condições/recência, grava aparição/observação e devolve canônico. Fusão trava identidades/IDs em ordem, revalida, transfere dados/referências, publica alias e aposenta perdedor no mesmo commit.
- Exclusão/limpeza/foto usam protocolo compatível com essas travas/estados. Foto não pode ganhar referência depois de ter sido reservada para remoção. Não há transação global com Storage: registrar intenção/resultado e compensação idempotente.
- O modelo deve permitir confirmar/liberar duravelmente referências de jobs; crash entre commit remoto e confirmação local conserva proteção. Não depender apenas de timeout curto ou de API acessando disco privado do bot.

### Defaults propostos para configuração e teste

| Política | Valor inicial proposto |
|---|---|
| Janela da instância | 48h, congelada ao criar instância. |
| Workers oferta/mídia/SQLite | Manter 4 / 1 / 1 e buffer/página existentes. |
| Workers/pool enriquecimento | 1 worker, no máximo 1 resolução de rede ativa por padrão; ajuste explícito, separado dos outros pools. |
| Resolução | Tempo total 5s incluindo DNS/redirects; até 5 redirects; leitura de corpo até 64KiB, com limites de headers/URL também definidos no transporte. |
| Tentativas de resolução | Até 3 por ciclo de job; negativo sem identidade/falha expira em 15min, sem reabrir indefinidamente o mesmo ciclo por polling. Nova tentativa exige novo ciclo elegível/evento ou ação diagnóstica explícita. |
| Cache positivo | 24h; expiração não estende oferta; versão de extrator incompatível invalida uso como prova. |
| Observações compactas | 7 dias, preservando resumo vencedor e o que jobs recuperáveis ainda exigem. |
| Aliases/mapa de evento/tombstones | Mínimo 7 dias após terminalização e liberação das referências recuperáveis; nunca purgar pendência só por TTL. |
| Estado local finalizado | Manter 7 dias; novos jobs/compensações entram nas mesmas proteções de não expurgo. |
| Limpeza remota | Em lotes limitados e sem sobreposição; validade governa ocultação e retenção governa purga. Legado usa política atual documentada de 48h. |

Valores são proposta desta versão, não medidas reais ou garantia de SLA. Validar positivos/finitos/inteiros e relações entre retenções/limites; mudanças materiais de política exigem revisar PRD. Não reduzir garantias de recuperação para obedecer TTL de observações. Referências pendentes podem durar além da retenção normal, com diagnóstico explícito, não histórico comercial infinito.

### Migração, aplicação futura e rollback

1. **Somente preparo/teste local nesta entrega:** fotografar estado compatível e simular backup/migração em arquivos temporários, sem abrir dados privados do usuário. Preparar bloco aditivo identificável/idempotente em `supabase/schema.sql`, seguindo padrão existente; testar banco vazio e legado. Ausência de seller/identidade legada continua desconhecida.
2. **Preflight remoto futuro autorizado:** conferir backup consistente SQLite (incluindo WAL corretamente), versão do schema/RPC/grants/índices, duplicidades legadas e configurações. Não fabricar IDs numéricos de canal a partir de usernames ou `canais.id`. Não criar constraints novas sobre dados incompatíveis sem diagnóstico.
3. **Evitar coexistência insegura:** parar coletor antigo e suspender limpador antigo em atualização futura. Ele não compreende validade/aliases e poderia apagar ofertas/fotos ativas. Backend novo precisa estar pronto antes de permitir gravações novas; não deixar processos antigos e novos competirem pela mesma base.
4. **Schema primeiro, serviços compatíveis depois:** aplicar SQL apenas mediante autorização separada futura; instalar backend/limpador compatíveis; bot migra SQLite aditivamente no startup e confere prontidão; frontend mínimo depois. Retomar limpeza somente com protocolo novo. Preservar mesmo diretório privado e único coletor.
5. **Legado:** eventos já congelados reconciliam dados/hash/vínculo antigos sem nova extração/filtro. Colunas novas são nullable/defaults que não atribuem confiança ao legado. Não fundir histórico automaticamente; dry-run opcional não escreve nada.
6. **Falha de migração/prontidão:** transação não confirma versão parcial, conserva fila e informa erro; nenhuma recriação vazia ou sucesso fictício. Testar reaplicação e reinício em cada fronteira.
7. **Rollback:** parar serviços que escrevem/limpam, preservar schema aditivo/SQLite e pendências; usar versão compatível com identidade/aliases ou deixar processamento pausado até correção. Não executar limpador/bot antigo sobre dados novos, apagar colunas/aliases/fila ou restaurar backup perdendo eventos sem nova decisão explícita. Downgrade automático não é prometido.

## 9. Estratégia de implementação futura

1. Reconfirmar instruções/base/worktree e preservar prompts/alterações posteriores; executar baseline bot/API/UI e simulação original, registrando ambiente, resultados/skips e dados comparáveis antes de editar.
2. Definir representação versionada/condições/recência e fixtures sintéticas com fontes; implementar camada URL e extratores locais com casos positivos e de incerteza. Manter algoritmo legado imutável no caminho congelado.
3. Preparar schema/RPC/privilégios e testes SQL locais de gravação/expiração/observações/aliases. Provar duas sessões independentes, inclusive primeira criação, mesma mensagem e resposta perdida, antes de integrar efeito remoto novo.
4. Migrar SQLite/cache/checkpoints e integrar gravação rápida com versão nova; provar retomada legada e schema ausente sem refiltro/perda de trabalho.
5. Implementar transporte seguro e worker de enriquecimento isolado, cache/negativos/retries/shutdown. Integrar fusão e resolução de ID antigo nos jobs/mídia.
6. Ajustar API/limpeza/exclusão/contagem/projeção pública e card/tipos mínimos; exercitar corridas entre fusão, remoção, mídia e limpeza de objetos conhecidos.
7. Rodar regressões completas, SQL/segurança/contratos, lint/tipos/build, simulação antes/depois e cenários novos; atualizar README/instruções e este PRD com fatos. Revisar diff sem staging/commit, entregar continuidade e parar antes da etapa 4.

### Arquivos confirmados e áreas propostas

- `bot/src/dedup.py`: preservar contrato legado e separar identidade nova; módulos novos propostos sob `bot/src/` para URLs/identidade/resolvedor, sem nomes finais presumidos.
- `bot/src/extractor.py`, `bot/src/avaliacao.py`, `bot/src/modelos.py`: derivar evidências locais mínimas para identidade, sem reescrever decisão antiga ou semântica de filtros.
- `bot/src/repository.py`, `bot/src/pipeline.py`, `bot/src/estado.py`, `bot/src/politica.py`: RPC/checkpoints/versionamento/retries/aliases/workers e retenção.
- `bot/src/config.py`, `bot/src/main.py`, `bot/src/midia.py`, `bot/src/observabilidade.py`: composição/limites/shutdown, referência segura de foto e logs. Mudanças só para integração desta etapa.
- `bot/tests/`, `bot/simulacao.py`, `bot/tests/test_simulacao.py`: ampliar comportamentos e preservar regressões; novos cenários de identidade/rede fake e fixtures sintéticas, caminhos finais definidos na implementação.
- `supabase/schema.sql`: bloco aditivo remoto preparado e funções/índices/grants. `backend/tests/sql-etapa2.local.mjs` mantém regressões; **novo runner SQL da etapa 3 proposto** precisa múltiplas sessões de verdade.
- `backend/src/models/produto.model.js`, `backend/src/services/produto.service.js`, `backend/src/services/limpeza.service.js`, `backend/src/config/env.js`, `backend/src/server.js`: consultas canônicas, erros, retenção e coordenação. Manter MVC; novo acesso a banco deve ficar em models, inclusive para a limpeza evoluída.
- `backend/tests/`, `backend/package.json`: testes de produtos/limpeza/RPC, runner local isolado; não iniciar servidor/ler `.env` real nos testes.
- `frontend/lib/types.ts`, `frontend/components/ProdutoCard.tsx`: atualização/queda mínima e compatível; testes existentes/novos de renderização, sem layout novo.
- `README.md`, `CLAUDE.md`, `.env.example`, `bot/.env.example`: documentação e novos parâmetros somente quando a implementação os confirmar. Nenhum deles é alterado neste planejamento.

## 10. Critérios de aceitação

Cada linha define dado/quando/então verificável; fixtures de loja e mensagens são sintéticas. Não basta aprovar função de hash.

| ID | Relacionado a | Critério verificável |
|---|---|---|
| **CA-001** | RF-001/002/003 | Dadas duas mensagens de canais distintos com identidade forte/condições equivalentes e apenas tracking irrelevante diferente segundo regra comprovada, gravar um card ativo e duas aparições únicas. |
| **CA-002** | RF-001/002 | Mesmo título/preço/foto com IDs fortes diferentes, sem identidade confiável ou com catálogo sem oferta selecionada não funde; registrar motivo de separação. |
| **CA-003** | RF-001/004 | Loja/seller diferentes, SKU/variante/cor/capacidade/tamanho/kit/quantidade conflitantes preservam cards separados; ausência crítica não é curinga. |
| **CA-004** | RF-001/004 | Primeira compra versus qualquer cliente, códigos diferentes e condições incompatíveis ficam separados sem equivalência comprovada. Cupom omitido não limpa código anterior nem é prova de “sem cupom”. |
| **CA-005** | RF-002 | Tokens `/AbC`/`/abc`, valores e nomes desconhecidos de query que diferem em caixa não colapsam; repetidos/vazios/ordem/fragmentos/assinaturas preservam semântica; `smid`/SKU/variação não somem. |
| **CA-006** | RF-002 | Regras de tracking/`linkCode` são restritas ao domínio/formato justificado; `ref`/`tag`/`aff` de domínio desconhecido ficam; HTTP/HTTPS, hosts ou barras não equivalentes não se fundem por normalização genérica. Link navegável original é preservado. |
| **CA-007** | RF-003/011 | Mesmo evento por live/histórico/retry, com renomeação de canal e após 48h, tem um vínculo/aparição/observação; se já existe nova instância, retry antigo permanece na anterior. |
| **CA-008** | RF-003/004 | Duas conexões independentes disputam criação da mesma oferta e do mesmo evento: um card por instância, aparições/observações exatas e decisão determinística, sem depender de lock Python compartilhado. |
| **CA-009** | RF-004/005 | Observações conhecidas 300→250→300 realmente mais recentes atualizam em ambas as direções; queda própria só em 300→250; `preco_original` continua anunciado, não preço anterior de atualização. |
| **CA-010** | RF-004/005 | Zero e nulo são distintos. Observação vencedora sem preço não vira zero ou desconto; valor antigo não é anunciado como vigente. Uma observação antiga nula não apaga preço recente conhecido. |
| **CA-011** | RF-005 | Histórico antigo de 200 chega após preço recente 300: preço/última aparição/expiração não retrocedem nem são renovados pela recepção. Empate de data usa a tupla documentada, reproduzível em ordem de chegada inversa; sem recência válida não substitui. |
| **CA-012** | RF-005/010 | Expirar instância, criar nova e retentar evento antigo preserva instâncias distintas. Atualização realmente nova prolonga elegibilidade por horário original; limpeza não apaga card ativo por `criado_em` antigo. |
| **CA-013** | RF-006/008 | Dois encurtadores em rede fake resolvem para identidade/condições equivalentes: ofertas já estavam salvas antes de liberar resposta; depois há um ativo, duas origens/observações e alias funcional. |
| **CA-014** | RF-006/007 | Resolver bloqueado/lento/falhando com todos os seus workers ocupados: novas ofertas continuam salvando e mídia/oferta não ultrapassam seus limites; timeout não oculta card. Resultado incerto preserva original e separados. |
| **CA-015** | RF-006/011 | Reiniciar com cache positivo válido permite dedup sem rede extra; negativo evita novas chamadas antes da expiração. Versão/TTL incompatível não vira identidade confiável e retry respeita orçamento/ciclo persistido. |
| **CA-016** | RF-007 | DNS/redirecionamentos fake para loopback, privados, metadata/link-local, IPv6 local/mapeado, host disfarçado, portas/protocolos proibidos são bloqueados antes de conectar; rebinding não troca IP validado. |
| **CA-017** | RF-007 | Loops, hops excedidos, DNS lento, tempo total, HEAD 405/501, servidor ignorando Range, corpo sem tamanho/comprimido/grande respeitam limites e fechamento; sem browser/auth/preço de página ou escape via proxy de ambiente. |
| **CA-018** | RF-003/008/011 | Commit confirmado com resposta perdida, crash/restart depois de 48h e retry de RPC não geram outro card/aparição/observação; decisões/filtros/hash originais não são recalculados. |
| **CA-019** | RF-008 | Injetar falha antes/durante/depois da fusão e da resposta: rollback não perde origens; retry conclui uma vez. Sobrevivente é menor ID elegível; aliases não ciclam e ID antigo continua consultável. |
| **CA-020** | RF-008/010 | Fundir cards com aparições/observações/foto válida preserva todos os registros e foto adotada. Mídia/compensação pendente pelo ID perdedor resolve canônico e não remove arquivo referenciado. |
| **CA-021** | RF-008/009/010 | Remoção/limpeza em sessão independente concorre com enriquecimento/fusão/vínculo de foto: oferta removida não ressuscita; nenhuma foto ainda referenciada é apagada; falha Storage conserva remoção recuperável. |
| **CA-022** | RF-009 | Lista/estatísticas contam só canônicos ativos; GET por alias retorna canônico, DELETE por alias remove só aquela instância; schema/banco indisponível não retorna falso 404. Nenhum payload interno/segredo vaza. |
| **CA-023** | RF-009 | Tipos/card continuam aceitando legado, foto/preço nulos/zero/cupom/canais; atualização/queda mínima é coerente e não fabrica percentual a partir de histórico. Sem realtime/redesign. |
| **CA-024** | RF-010 | Avançar relógio/rodar lotes purga dados finalizados elegíveis e cache expirado, conserva resumo vencedor/alias/mapa/referências de pendências e retoma lotes sem dupla execução destrutiva. Após ack e retenção, referências elegíveis são purgadas. |
| **CA-025** | RF-011 | Migrar SQLite v5 e versões anteriores suportadas com decisões/hash/jobs/mídia pendentes preserva conteúdo/vínculos/fronteiras; falha de DDL mantém versão anterior/dados; restart não reavalia aprovação. |
| **CA-026** | RF-011 | Aplicar SQL duas vezes em banco local vazio/legado preserva IDs/hash/dados e não funda histórico. Prontidão ausente/parcial conserva trabalho e reporta incompatibilidade, sem fallback novo por título. |
| **CA-027** | RF-003/011 | Falhas temporárias SQLSTATE 40001/40P01/indisponibilidade seguem backoff/retry idempotente e orçamento; esgotar tentativas imediatas mantém job durável, sem descartar promoção. |
| **CA-028** | RNF-002 | No banco local, PUBLIC/anon/authenticated não executam RPCs/auxiliares de escrita/fusão; papel autorizado executa. Políticas RLS não são relaxadas; limitações do ambiente Supabase simulado ficam explícitas. |
| **CA-029** | RF-012, RNF-004/005 | Suítes base bot/API/frontend e novos testes passam em ambiente compatível; skips/falhas são relatados e nenhum teste/debug/watchdog/WAL/FULL é removido/relaxado para verde. Mudança intencional de expectativa de identidade tem explicação/cobertura legada. |
| **CA-030** | RF-006/012, RNF-001/005 | Comparação offline conserva comando/dataset base, mede p50/p95/máximo até salvar, cards/aparições/pendências e máximos de workers; cenários extras de duplicatas/resolver lento provam disponibilidade antes da rede e reconciliação. Não atribuir tempos simulados à VPS. |
| **CA-031** | RF-012 | Documentação/entrega final cobrem matriz, formatos/fontes/incertezas, migração/rollback/ordem, retenção/diagnóstico sem segredos e continuidade para etapa 4, sem iniciá-la ou executar ações remotas. |

## 11. Plano de validação

### Automatizada — somente após aprovação/implementação

Os procedimentos abaixo foram executados/conferidos na revalidação ou possuem evidência primária anterior explicitamente reusada. A marcação registra a categoria verificada com os limites indicados, não execução de produção. As matrizes históricas e a matriz final corrente constam da seção16.

- [x] **Baseline antes das mudanças:** evidência primária anterior conferida/reusada, com257 testes Linux,saída externa1 explicada e falhas/skips Windows preservados; não recriada após a implementação. `pip check` repetido na revalidação. Ver seções15/16.
- [x] **Regressões API/UI:** `npm test` em `backend/` e em `frontend/`,63/63 e13/13 na revalidação,sem skips. Fakes não acessam Supabase/Auth reais; UI renderizada não é browser E2E.
- [x] **Identidade/tempo:** R-BOT356/R-SQL37/R-PROBE cobrem positivos/conflitos/tempo/recência/retentiva e pipeline com SQLite real temporário, não apenas hashes.
- [x] **Rede falsa:** R-BOT/R-SIM2 com DNS/transporte falsos,barreiras/limites/cache/restart/encerramento; oferta confirmada antes de liberar rede.
- [x] **SQL existente:** R-FILTROS, `npm run test:sql`, Postgres local novo descartável. Não representa teste de concorrência da etapa3.
- [x] **SQL etapa 3:** `npm run test:sql:etapa3`,R-SQL37 grupos; guardas de host/nome/banco vazio,sem `.env`/senha real. Aplicação dupla/legado/falha/preflight/RPC/tempo/aliases/RLS/grants.
- [x] **Atomicidade real:** R-SQL PIDs34604/34684,barreira `pg_locks` e terceira leitura; criação/mesmo evento/preço/fusão/exclusão/mídia/limpeza. Não substituída por coroutines em fake.
- [x] **Limite do substituto SQL:** conferido; foi usado Postgres real de sessões independentes,não PGlite como prova concorrente. RLS preservada,sem Supabase real como laboratório.
- [x] **Migração SQLite:** R-BOT migra0–5→6/reabre6,com decisões/hash/jobs/mídia/contexto preservados e falha DDL atômica.
- [x] **Qualidade UI:** R-QUAL,lint/typecheck/build aprovados com variáveis fictícias. Lint Python/build backend não configurados,ausência justificada sem toolchain adicional.
- [x] **Revisão final:** R-REVIEW,projeção/logs/grants/RLS/transporte/limites e trabalho preexistente conferidos. Sem staging/commit/chamada remota.

### Simulação comparável e cenários novos

Executar antes e depois em `bot/`, conservando seed/carga e identificando dataset/ambiente:

```text
python -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1
```

Registrar p50/p95/máximo live/histórico até confirmação da oferta, vazão, heartbeat, filas inicial/pico/final, contagem de eventos/cards ativos/aparições, enriquecimentos pendentes, cache hits e máximos ativos de oferta/mídia/resolução. Medir disponibilidade antes de drenar mídia/enriquecimento; depois medir convergência separadamente com prazo finito.

Conservar cenário original de cinco esperas lógicas para comparabilidade; se RPC alterar número de roundtrips, acrescentar medição com modelo atualizado explicitamente identificado, sem atribuir ganho fictício a CPU/dedup ou trocar dataset antigo silenciosamente. O fake atual não deduplica ofertas de verdade: cenário novo deve exercitar a lógica de identidade/reconciliação utilizada, com testes SQL independentes para a garantia remota.

Novos cenários reprodutíveis propostos, com nomes/flags finais registrados na implementação: (a) mesmas ofertas fortes entre canais, (b) encurtadores diferentes para mesmo destino, (c) resolver bloqueado/timeout e cache frio/quente após restart, (d) preço novo seguido de histórico antigo e expiração. Para o caso pequeno de dois eventos/encurtadores equivalentes, esperar dois provisórios antes de resolver, um canônico ativo e duas aparições depois; se informação insuficiente, permanecer dois e explicar motivo.

Não definir SLA de milissegundos para VPS. Causalidade de independência é provada por barreiras, não por um tempo fake abaixo de limiar. Comparação observada deve separar custo de fsync/ambiente/roundtrips e não apagar caudas/falhas anteriores com repetições até verde.

### Manual/documental local

- [x] Formatos/fontes/sintéticos revisados; R-PROBE demonstra duas uniões e duas separações Amazon/ML,sem dados privados em logs.
- [x] JSON público/card inspecionados com apoio de R-API/R-UI/R-SQL:subida/queda/nulo,alias/foto nula,sem redesign.
- [x] Migrações/falha/rollback transacional exercitados em bancos sintéticos por R-BOT/R-SQL. Rollback operacional é pausa/preservação,não downgrade produtivo; ordem futura proíbe limpador antigo.
- [x] Limitações/fora de escopo expostos na conclusão da seção16; produção intocada,nenhuma pendência obrigatória local.

### Regressões prioritárias

Coleta paginada/gerações e IDs estáveis; filtros/cache preparado/motivos das etapas 1 e 2; decisões/hash congelados e commits ambíguos; oferta antes da foto; upload confirmado/compensação; justiça live/histórico; limites do executor; sinais/shutdown; retenção em lotes; condições pós-preço e frete com destino. Não remover controles para acomodar o novo contrato.

## 12. Riscos, premissas e perguntas

### Riscos

| ID | Probabilidade / impacto | Mitigação e sinal de parada |
|---|---|---|
| **R-001 — Falsa fusão** | alta / alto | Identidade forte + condições comprovadas, desconhecido explícito, fixtures negativas e fontes. Parar se equivalência exigir adivinhar seller/variante ou apagar conflito. |
| **R-002 — SSRF/rebinding/resposta grande** | media / alto | Allowlist, DNS/IP de conexão por salto, streaming e orçamentos separados. Parar antes de habilitar resolvedor se transporte não sustentar essas garantias. |
| **R-003 — Corrida remota/perda de origem** | media / alto | RPC/locks/chaves, duas sessões reais e falha injetada. Sem ambiente de concorrência, validação permanece impedida, não aprovada com fakes. |
| **R-004 — Limpeza apaga card/foto viva** | alta / alto | Validade própria, aliases, referência recuperável/terminalização e remoção conhecida coordenadas. Parar se precisar executar limpador antigo com cards novos ou depender de cascata para preservar dados. |
| **R-005 — Mudança de decisão congelada** | media / alto | Caminho legado versionado, dados/hash imutáveis e migração com pendências. Parar se retry exigir refiltrar/recalcular para concluir efeito ambíguo. |
| **R-006 — Backlog/retentiva indefinidos** | media / medio | Limites, cache/ciclos negativos, retenção após ack e métricas de idade. Pendência recuperável não é descartada para reduzir contagem; erro exige diagnóstico, não TTL cego. |
| **R-007 — Ambiente/caudas de SQLite** | media / medio | Baseline real, fontes/FS/versões registrados e barreiras nos testes. Não relaxar watchdog/debug/WAL/FULL nem reiniciar/configurar WSL/Windows sem autorização específica. |

### Premissas

- **PRM-001:** permanece um coletor em produção com diretório persistente privado; provar concorrência de banco não autoriza múltiplos coletores. Confirmar composição na implementação.
- **PRM-002:** service_role é o papel servidor já utilizado e candidato ao EXECUTE das RPCs; não será enviada ao navegador. Confirmar grants localmente e documentar conferência futura de produção.
- **PRM-003:** sem corpus real fornecido, fixtures serão sintéticas e suporte conservador. URLs públicas de documentação não provam todos os formatos de query da loja.
- **PRM-004:** 48h de janela, defaults de cache/retentiva/limites e política temporal acima são propostas completas desta versão, sujeitas à aprovação do PRD, não comportamento já entregue.
- **PRM-005:** bancos locais descartáveis e credenciais exclusivas de teste podem ser preparados na implementação sem credenciais do usuário; disponibilidade ainda não confirmada. Falta deles é impedimento de validação, não autorização para acessar remoto.
- **PRM-006:** idempotência pós-48h vale com evidência preservada, especialmente jobs recuperáveis; replay arbitrário depois de purga total não tem garantia eterna. Essa limitação não permite purgar vínculo ainda necessário à retomada.

### Perguntas abertas

- **PA-001 — não bloqueante:** quais lojas/encurtadores aparecem com maior frequência em exemplos que o usuário queira fornecer futuramente? Sem amostras, priorizar o subconjunto justificável documentado; não acessar canais nem bloquear planejamento por isso.
- **PA-002 — não bloqueante:** qual ferramenta local oferecerá duas sessões Postgres independentes no momento da implementação? Verificar baseline e escolher Postgres descartável ou alternativa efetivamente compatível. Sem prova, marcar CA-008/021 e atomicidade impedidos.
- **Perguntas bloqueantes atuais:** nenhuma. O escopo e as proteções permitem uma especificação útil; disponibilidade de ambiente e comprovação das regras são gates de implementação/validação, não fatos presumidos.

## 13. Proteções adicionais

- [x] Preflight e migrações aditivas repetíveis, com preservação de legado/pendências e plano de rollback sem apagar dados.
- [x] Revisão de RPCs/permissões/RLS e concorrência com sessões independentes.
- [x] Revisão SSRF do caminho inteiro, inclusive DNS/uso do IP/proxy/redirect/fallback/limites.
- [x] Testes de interrupção e resposta perdida na gravação/fusão, alias antigo e exclusão concorrente.
- [x] Prova de referência de mídia/limpeza segura e protocolo de retenção de trabalho recuperável.
- [x] Evidências honestas de suítes/medições e nenhuma operação remota. Não criar artefatos paralelos por padrão.

## 14. Checklist de implementação

- [x] **T01 — Baseline e contratos:** RF-001/002/004/005/012; ambiente/resultados reais, fixtures sintéticas, representação/condições/tempo e matriz de suporte.
- [x] **T02 — Identidade local conservadora:** RF-001/002, RN-002/003; normalização e extratores com casos positivos/negativos e legado intacto.
- [x] **T03 — Schema e operações atômicas:** V-ET3-001 corrigido em implementação: índices parciais/escritores/preflight numéricos, proteção de legado/aliases e37 grupos SQL reais aprovados, incluindo concorrência/reaplicação/falha atômica. Revalidar formalmente.
- [x] **T04 — Persistência local e caminho rápido:** RF-003/006/011, RN-001/004/008; migração SQLite, decisões/cache/checkpoints e retomada sem rede de resolução no caminho crítico.
- [x] **T05 — Resolvedor seguro e retomável:** RF-006/007/008, RNF-001; worker/pool separados, rede fake/cache/restart/retries/shutdown e reconciliação idempotente.
- [x] **T06 — Aliases, mídia, API e limpeza:** RF-008/009/010; contagem/detalhe/exclusão canônicos, retenção/ack e fotos referenciadas preservadas em corridas.
- [x] **T07 — Card/tipos mínimos:** RF-004/009; preço anunciado distinto de atualização/queda, sem realtime/redesign.
- [x] **T08 — Verificações e evidências finais:** regressões permanentes, SQL37 grupos, bot356/356,API63/63 e revisão independente do delta concluídos. Evidências/limites/checagens reusadas registrados abaixo; pronta para nova validação, sem publicação/etapa4.

## 15. Registro da implementação

### Início da implementação — 2026-11-05

Invocação explícita de `sdd-implementar` aprova a versão 1. Runtime global, prompts comuns/implementação e PRD lidos integralmente. Checkout permanece na base; seis arquivos não rastreados preexistentes (cinco prompts e este PRD), sem diff rastreado. Nenhuma autorização de escrita remota/publicação. Checklist ativo: T01 baseline/contratos; T02–T08 pendentes. Histórico de planejamento abaixo preservado como registro, não estado corrente.

### Baseline e ambiente desta implementação

- API: `npm test` em `backend/`, **40/40**, sem skips, saída 0, 1227,5293ms. UI: `npm test` em `frontend/`, **7/7**, sem skips, saída 0, 1990,6881ms.
- Windows/Python 3.14.4 não é o ambiente recomendado: baseline bot executou 257 testes em 42,395s, **7 erros e 26 skips**, saída 1; log privado temporário `dealbot-etapa03-baseline-bot.log`. Não foi tratado como baseline aprovado nem corrigido relaxando testes.
- WSL inicialmente parado. Usuário autorizou explicitamente iniciar Ubuntu, sem reinício/reconfiguração/serviços remotos. Python 3.12.3 e venv de teste já existente disponíveis; `pip check`: nenhuma dependência quebrada.
- Primeira execução Linux no checkout excedeu timeout externo de 120s da ferramenta; log `dealbot-etapa03-baseline-linux.log`, resultado incompleto, não aprovado. Para obter referência independente das edições concorrentes, `git archive` do commit base foi extraído em pasta temporária própria, sem criar worktree/branch ou copiar dados privados.
- No snapshot imutável, `python -B -m unittest discover -s tests -v` pelo venv Linux executou **257/257 em 176,486s, OK, sem skips**. A ferramenta PowerShell reportou saída 1 por encapsular stderr do unittest como `NativeCommandError`; não alegar saída externa 0. Log integral `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa03-base-imutavel.log`. Nenhum watchdog/debug/WAL/FULL foi alterado; essa referência não explica causalmente lentidão anterior.
- Simulação original no Windows/Python 3.14: 130 ofertas/produtos aprovados, zero falhas/duplicatas; 17,307319s, 7,511273 ofertas/s; live p50/p95/máx 500,048/806,518/863,599ms, histórico 4570,738/11418,465/16313,178ms; heartbeat máximo 32,4448ms; workers máximos oferta4/mídia1, mídia pendente105. Hashes de dataset live `606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb` / histórico `27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805`. Comparação posterior deve usar mesmo ambiente/cenário; não é medição VPS.

### Decisões técnicas locais já aplicadas

- `PipelineIdentidade` e `RepositorioIdentidade` compõem o caminho ativo em `main.py`; classes/algoritmo legados ficam disponíveis apenas para decisões antigas e regressões explícitas. Ausência de RPC nova propaga erro/preserva trabalho, sem fallback por título.
- SQLite v6 adiciona identidade separada, confirmação remota, cache e enriquecimentos; não redefine `resolucoes` de canais. Ajustadas somente expectativas intencionais de versão/defaults de colunas em dois testes antigos; assertions de preservação/falha continuam presentes.
- Contrato de identidade: comparar hash **e** `componentes.comparacao`; evidências/fonte/URL original ficam separadas, pois podem diferir entre canais sem mudar a oferta.
- Referência de recuperação permanece remota até confirmação local durável após terminalização de oferta/mídia/enriquecimento; limpeza local não apaga evento v2 sem esse ack.

### Verificações direcionadas em andamento

- Novo contrato RPC Python: sete testes passaram; comando incluiu por engano classe inexistente `TestEstadoContexto`, gerando um erro de seleção adicional, sem falha nos sete testes. Corrigido o seletor (não o teste): `tests.test_contexto.TestContextoSQLite`, **6/6 em 2,055s**, Python3.12/WSL, saída0.
- Agentes executaram testes novos de identidade/resolução e API/UI; resultados serão consolidados após revisão dos contratos/integridade e verificações finais. Ainda não constituem conclusão/validação desta entrega.

### Continuação de implementação — 2026-11-06

Três agentes atingiram limite de uso antes de entregar revisão/integração completas; seus arquivos parciais foram preservados e revisados pelo agente principal. Nenhum relatório de revisão ausente é tratado como aprovação. Usuário solicitou continuar. Estado permanece `em_implementacao` até concluir verificações, sem mudança de escopo/aprovação.

- Encontrados e corrigidos contratos de retorno SQL `reutilizado`/conflito, confirmação remota sem resposta completa e foto com remoção reservada. Confirmação inválida não libera a referência local; conflito de decisão preserva pendência.
- Acrescentado preflight de jobs legados: RPC `oferta_legado_registrar` reconcilia aliases/ID e hash congelado sob o mesmo lock SQL, fixa pin sem reextração/refiltro; `oferta_legado_pronto` libera gate de limpeza somente depois do preflight. SQLite mantém `referencia_remota` separada da identidade antiga. Esse detalhe implementa RF-010/011, sem backfill/fusão em massa nem alterar hashes/decisões.
- Serialização escolhida: um advisory lock transacional fixo para todas as RPCs de escrita/fusão/foto/limpeza. É mais conservador que locks por identidade; não há rede no lock. Valida atomicidade entre sessões, mas não promete escala de múltiplos coletores ou throughput real Supabase.
- Revisão detectou metadados de evento/alias/mídia que poderiam persistir enquanto um card fosse renovado indefinidamente. A limpeza agora purga dados confirmados fora de 7 dias, conserva a observação vencedora e nunca purga pins. Tombstones de mídia só saem sem trabalhos recuperáveis. A garantia de replay após purga total continua limitada conforme RN-007/PRM-006.
- Primeira execução SQL desta continuação (`dealbot_teste_etapa3_r4`) parou no grupo de gap temporal: fixture construía duas datas com âncoras `Date.now()` diferentes exatamente na fronteira de 48h. Corrigida a fixture para uma âncora fixa e gap inequívoco, sem relaxar assert de instâncias distintas. Grupos anteriores ficaram aprovados; essa execução não validou concorrência.
- Postgres 17.5 Windows já instalado, fora do PATH; cluster temporário exclusivo em `.../Temp/opencode/dealbot-etapa03-pg-isolado`, porta55439, apenas127.0.0.1, papel sintético postgres sem senha. Nenhum serviço do sistema ou banco do usuário foi alterado. Reinício desse cluster teve erro de compartilhamento do log dentro do próprio diretório de dados; log movido para fora do cluster na nova invocação e recuperação completou sem mudar parâmetros de durabilidade. Bases sintéticas anteriores preservadas, sem DROP.
- Execução SQL seguinte (`dealbot_teste_etapa3_r5`): **22 grupos aprovados**, saída0, incluindo duas sessões reais com PIDs27792/5828 e barreira `pg_locks`, primeira criação, mesmo evento, recência inversa, falha/rollback de fusão, exclusão por alias, reserva/foto em ambas as ordens e limpeza concorrente. Testes adicionais de relógio/retentiva estão sendo incorporados em banco novo, não reusando banco preenchido para mascarar falha.
- Contratos Python/SQLite direcionados após correções: **34/34 em16,687s**, saída0. A falha anterior no teste novo de timeout era expectativa de terminalização após1 tentativa; foi substituída por assertions de retry espaçado, preservação da oferta e teto de3 tentativas, sem aumentar timeout ou remover cobertura.
- Primeira suíte integral pós-implementação: **353 testes/351 aprovados/1 falha/1 erro,215,654s,zero skips**, saída1; log `.../Temp/opencode/dealbot-etapa03-suite-final.log`. Erro: fixture de encerramento ainda injetava Pipeline legado sem preflight; agora exercita PipelineIdentidade real com todos os workers. Falha: novo `time.time()` na manutenção consumia o relógio controlado e rompia cutoff estável; corrigida produção para reutilizar o mesmo instante da drenagem, preservando asserts de cutoff/espera. Nenhum watchdog/debug/WAL/FULL/assert de durabilidade foi relaxado.
- API final até aqui **63/63**, UI **13/13**, zero skips; lint e typecheck aprovados. Build frontend aprovado com três variáveis públicas fictícias e nenhum `.env.local` real. SQL de regressão etapa2 passou em banco local novo `dealbot_teste_etapa3_filtros_final`.

### Fechamento da implementação local — bloqueado para aceite

Arquivos principais: `bot/src/identidade.py`, `resolvedor.py`, `pipeline_identidade.py`, `repository_identidade.py`; evolução de `estado.py`/`main.py`/`midia.py`/`config.py`; bloco etapa3 em `supabase/schema.sql`; models/services de produtos/limpeza; tipos/card mínimos. Novos testes Python/API/UI e runner SQL; `cenarios_identidade.py`/`simulacao_identidade.py` são exclusivamente offline, não outra implementação de persistência de produção. README/CLAUDE/exemplos de ambiente documentam política, suporte estrito, migração/rollback, diagnóstico e limites.

Revisão final feita pelo agente principal: projeção de payload público/SQL, invoker/grants inclusive helpers, proteção de aliases/foto/limpeza, caminho legado, cache/checkpoints, URLs/DNS/IP/TLS/proxies e diff. A revisão independente solicitada não terminou por limite do agente; não é alegada como aprovada. DNS usa executor próprio de1 worker e no máximo1 syscall submetida; timeout não libera vaga enquanto SO não terminou. `aclose` não aguarda syscall, mas thread não daemon ainda pode atrasar saída do interpretador: limitação explícita, sem prometer encerramento físico rígido.

Fonte primária complementar consultada somente em leitura em06/11: [Amazon Associates — Program Policies, §2 Links](https://affiliate-program.amazon.com/help/operating/linking). Define `tag`/Associates ID para atribuição de referências/comissões. A regra restrita não remove `tag` do link navegável, não vale universalmente e não comprova seller/variante/condições; `linkCode` permanece conservado. Nenhuma página de produto/preço, canal ou conta real foi consultada.

#### Resultados reais finais

| Comando/ambiente | Resultado | Limites |
|---|---|---|
| `npm run test:sql:etapa3` / PostgreSQL17.5 local / banco vazio `dealbot_teste_etapa3_r6` | **24 grupos aprovados**, saída0; sessões independentes PIDs19460/19360 e barreira real em `pg_locks`. | Auth/Storage/papéis Supabase sintéticos; sem PostgREST/Storage de produção. |
| SQL etapa3, grupos finais adicionais | Recepção local adiantada não descarta observação original válida; aliases/tombstones confirmados são purgados após retenção, nunca com referência recuperável. | Relógio de ingestão não é fonte de validade; não se afirma equivalência de relógios da VPS. |
| `npm run test:sql` / banco local `dealbot_teste_etapa3_filtros_final` | Aplicação dupla, legado, defaults, constraints e preflight da etapa2 aprovados, saída0. | Mantida a regressão SQL anterior. |
| `python -B -m unittest` com os seletores de retenção/encerramento corrigidos, pipelineIdentidade e repositórioIdentidade / Python3.12.3 WSL | **35/35 em16,146s**, saída0. | Inclui teste de40001/40P01 em retry sem nova decisão; não substitui suíte completa. |
| `python -B -m unittest discover -s tests -v` / Python3.12.3 WSL, log `dealbot-etapa03-suite-final-02.log` | **354 executados,352 aprovados,2 erros,113,352s,zero skips**, saída1. | **BLOQ-ET3-001**, não aprovado. Os97 testes novos passaram; dois controles antigos de checkpoints/rajada excederam watchdogs. |
| `npm test` / backend | **63/63**, saída0,1492,7635ms,zero skips. | HTTP/Storage/Auth falsos; contratos/query strings com SDK, não infraestrutura real. |
| `npm test` / frontend | **13/13**, saída0,1931,3135ms,zero skips. | Componentes renderizados, API/Auth/hooks falsos; não browser E2E. |
| `npm run lint`, `npx --no-install tsc --noEmit --incremental false` / frontend | Ambos aprovados, saída0. | Nenhum lint Python/build backend existe configurado. |
| `npm run build` / frontend Next14.2.5 | Compilação/lint/tipos/6 páginas aprovados, saída0. | Variáveis públicas fictícias (`https://teste.invalid`, chave fictícia, API localhost); não deploy. |
| `git diff --check`, revisão de arquivos novos e status | Sem erro de whitespace; avisos LF→CRLF do Git. | Sem staging/commit/push; cinco prompts do usuário preservados. |

Conferência final adicional:17 arquivos novos de código/testes/PRD sem whitespace final. Uma sonda com `core.autocrlf=false` interpretou CRLF de linhas originais como whitespace e retornou1; `git diff --check` com a configuração normal do repositório retornou0, apenas avisos de EOL. Não foram normalizados arquivos inteiros nem alterada a configuração Git do usuário para mascarar isso.

**BLOQ-ET3-001 — Suíte integral ainda vermelha:** `test_checkpoints.TestCheckpoints.test_compensacao_pos_upload_sobrevive_a_encerramento_e_reinicio` e `test_pipeline.TestPipeline.test_rajada_concorrencia_justica_e_heartbeat` terminaram em `TimeoutError` dos watchdogs existentes. A segunda falha envolve espera em leitura `estado.evento` no executor SQLite. Não foi comprovado se a causa é ambiente, regressão de custo da entrega, escalonamento ou combinação. O fato de testes antigos/novos direcionados passarem não invalida a falha integral. Não houve nova repetição integral/isolada para obter verde, alteração de watchdog/debug/WAL/FULL, reset/reconfiguração de WSL/Windows ou remoção de asserts. Próxima investigação deve separar espera de fila, execução SQL/fsync e retorno ao loop antes de propor correção.

#### Medições offline antes/depois

Mesmo comando base solicitado, Windows/Python3.14.4, seed42, live30/histórico100, banco20ms/operação, mídia200ms, workers4/1. Dataset idêntico pelos hashes registrados no baseline. A simulação original mantém cinco operações lógicas por oferta e NÃO mede nova RPC/dedup real. Os horários de execução diferem; não é experimento causal controlado nem SLA de VPS.

| Métrica do cenário original | Antes | Depois |
|---|---|---|
| Recebidas/cards/aprovadas/falhas |130/130/130/0 |130/130/130/0 |
| Duração / vazão |17,307319s /7,511273ofertas/s |28,193044s /4,611066ofertas/s |
| Live p50/p95/máx até confirmação |500,048/806,518/863,599ms |20288,336/21672,516/21822,960ms |
| Histórico p50/p95/máx |4570,738/11418,465/16313,178ms |25747,772/27810,697/28155,933ms |
| Workers máximos oferta/mídia |4/1 |4/1 |
| Ofertas pendentes ao fim / mídia pendente |0/105 |0/107 |
| Heartbeat máximo |32,4448ms |16,9483ms |

**BLOQ-ET3-002 — Piora observada ainda não explicada:** a medição depois foi mais lenta, principalmente no live. Não se atribui automaticamente a disco/ambiente nem se alega ganho com o modelo RPC novo; preservar os números negativos e investigar antes de aceitar desempenho. Saída íntegra depois: `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa03-simulacao-depois.json`.

Novo comando executado: `python -B -m simulacao_identidade --seed 42 --pares 10 --cenario todos --db-ms 20 --resolucao-ms 200 --oferta-workers 4 --enriquecimento-workers 1`, Windows/Python3.14.4, saída0. SQLite real temporário, identificar real, rede/Telegram/Storage/repositório de cards exclusivamente falsos. Uma espera por operação RPC fake, produtores e janela distintos: não comparar diretamente os tempos abaixo com o benchmark legado. Saída íntegra: `.../Temp/opencode/dealbot-etapa03-simulacao-identidade.json`.

| Cenário v2 (20 eventos) | Live p50/p95/máx(ms) | Histórico p50/p95/máx(ms) | Cards/aparições antes→depois | Enriquecimentos pendentes antes→depois | Convergência após liberar |
|---|---|---|---|---|---|
| Fortes |56,498/80,281/80,281 |137,055/152,018/152,018 |10/20→10/20 |0→0 |0,504333s |
| Cache frio |68,673/107,605/107,605 |179,565/209,684/209,684 |20/20→10/20 |20→0 |0,968087s |
| Cache quente após restart |62,738/71,414/71,414 |122,758/159,660/159,660 |10/20→10/20 |0→0 |0,489607s |
| Resolvedor lento |64,892/89,263/89,263 |143,708/164,312/164,312 |20/20→10/20 |20→0 |5,089651s |

Frio/quente/lento compartilham hash de dataset `e273f766880cda5b9bb37ed261f3f83fb775e495b579ac7e2db1b9f0f2ccd263`. Nos dois cenários com barreira, todas as20 ofertas estavam salvas enquanto a resposta de rede permanecia bloqueada. Máximos4 oferta/1 mídia/1 enriquecimento/1 rede fake; cache quente teve20 hits e zero resoluções; frio/lento tiveram20 resoluções cada,10 aliases e todas as pendências de mídia/enriquecimento/ack drenadas. Isso prova a separação de fases no modelo, não latência real, isolamento SQL ou compatibilidade de todas as lojas.

#### Migrações e continuidade

- Preparadas: SQLite v6 (0–5 e reabertura6), bloco SQL aditivo/idempotente etapa3,14 funções invoker restritas, referências/pins/gate legado, aliases/estados/retentiva. Sem dados históricos reclassificados em massa. Nenhum SQL remoto executado.
- Aplicação futura depende de backup/preflight autorizado, parada de coletor/limpador antigos, schema primeiro, backend/limpeza compatíveis e bot no mesmo diretório, gate de legado liberado pelo próprio preflight, frontend por último. Rollback não deve rodar limpador antigo sobre dados novos ou apagar pins/aliases/fila.
- Cluster temporário usado nesta continuação foi parado de forma limpa com `pg_ctl ... -m fast -w stop`, saída0; bases sintéticas/logs preservados para inspeção. Nenhum serviço Postgres/WSL do usuário foi reiniciado/reconfigurado.
- T01–T07 implementados e com verificações direcionadas; **T08 pendente** por BLOQ-ET3-001/002. Aprovação v1 permanece registrada, mas não autoriza declarar entrega validada. Sem desvio material de requisitos ou correção fora do escopo; limites/diagnósticos mantidos explícitos.
- Para etapa4 futura: consumir somente IDs canônicos/campos públicos, respeitar expiração/aliases e distinguir preço anunciado de atualização; não presumir dedup imediata de links opacos nem oferta equivalente com identidade incompleta. Nenhum realtime/redesign/migração de imagem iniciado.
- Resumo de continuidade: não refazer implementação nem repetir até verde. Começar pelos logs da suíte final02 e benchmark depois, investigar os dois bloqueios preservando código/decisões/hash e proteções, executar verificações justificadas pela correção e só então encaminhar para validação formal.

### Investigação autorizada dos bloqueios — 2026-11-06

Usuário solicitou executar o diagnóstico proposto. Git/base e alterações anteriores preservados. Sem autorização de reinício/reconfiguração de WSL/Windows, SQL remoto ou publicação. Ubuntu estava parada ao consultar distribuições; iniciar para diagnóstico continua dentro da autorização explícita anterior, sem reinício forçado.

Plano finito, sem repetir até verde:

- **D01 (executado):** uma execução nativa dos dois testes que falharam; depois controle instrumentado base/atual/atual/base, registrando hashes, debug/watchdogs, espera até executor, tempo de execução/thread CPU e retorno ao loop. Sucesso isolado não apaga falha integral.
- **D02:** comparar simulação original da base e atual sob o mesmo ambiente; investigar separadamente armazenamento/execução SQL versus escalonamento/metadados de fontes. Não usar o simulador RPC diferente para alegar correção do benchmark legado.
- **D03:** somente se houver causa demonstrada, corrigir de forma mínima ou documentar invocação compatível de teste; acrescentar prevenção e executar verificação final justificada. Não aumentar watchdogs, desabilitar debug, trocar WAL/FULL ou apagar evidência negativa.

Hipóteses iniciais, ainda não confirmadas: H1 espera dominante em commit/fsync/executor; H2 custo de retorno/agendamento/debug ao acessar fontes Windows pelo WSL; H3 custo novo de schema/consultas. A medição deve distinguir as três antes de qualquer patch produtivo.

#### D01 — controles finitos dos dois watchdogs

- Execução nativa única dos dois seletores: **2/2 em2,480s**, saída0, log `.../Temp/opencode/dealbot-etapa03-d01-nativo.log`. Não apaga os dois erros da execução integral anterior.
- Sonda temporária `dealbot-etapa03-d01-fases-v1.py`, fora do repositório, mede submissão→início do executor, execução/CPU da thread e retorno ao loop. Conserva watchdogs, debug do unittest, executor serial e WAL/FULL (`synchronous=2`,busy_timeout2000). Perfis/amostras completas registram hashes de fontes e FS.
- Ordem predefinida **base/atual/atual/base**, sem parada após sucesso: **4,631s/falha de rajada**, **15,318s/falha de compensação**, **2,645s/aprovado**, **2,580s/aprovado**. O runner diagnóstico termina0 para salvar dados mesmo quando o teste falha: o campo `testes.sucesso` e os stacks são a autoridade; não são quatro execuções aprovadas.
- Na base lenta, gravação levou475,082ms; leitura de evento enfileirada esperou850,701ms e executou em0,109ms. No atual lento, `midia_checkpoint` levou2126,200ms com0,231ms de CPU; leitura atrás esperou2120,009ms e executou em0,157ms. Nas duas amostras rápidas, execução máxima14,639/13,569ms, mas retorno ao loop p50≈19ms com fontes9p/debug. Resultado em `dealbot-etapa03-d01-resumo.json` e quatro JSONs/logs correspondentes.
- **Conclusão limitada:** o problema se manifesta também no commit base e contém espera não CPU na thread serial, propagada às leituras pelo executor; não é prova de defeito novo em SELECT/identidade nem prova do componente físico responsável. H1 tem evidência; H2 precisa controle específico. Não foi corrigido código produtivo por palpite.

#### D02 — benchmark original e COMMIT isolado

- Sondas temporárias `dealbot-etapa03-d02-{commits,ordem}-v1.py`, mesmas esperas/dataset/flags originais, mesma instrumentação nos quatro controles Windows/Python3.14.4. A subclasse SQLite só mede `execute` e saída transacional, sem suprimir commits ou mudar PRAGMAs. Hashes do dataset conferem com baseline. Nenhum benchmark concorreu com testes/sondas de I/O.

| Ordem fixa | Código | Duração(s) | Live p50/p95/máx(ms) | Histórico p95(ms) | COMMIT máximo(ms) |
|---|---|---|---|---|---|
|1|Base|6,719784|328,960/499,723/521,132|6226,809|4,611|
|2|Atual|6,687932|411,350/565,236/612,841|6437,112|8,814|
|3|Atual|6,658801|347,594/591,052/640,073|6419,835|21,888|
|4|Base|32,013827|1911,742/4176,971/4265,216|31617,971|2545,975|

- Na última base, execução acumulada no executor28,978s; os `execute` individuais medidos não passaram2,414ms, mas COMMITs chegaram2545,975/1544,995/1229,622ms. Retorno ao loop máximo8,062ms. CPU Windows tem granularidade15,625ms e não mede submilissegundos com precisão; não interpretar0,0 como CPU literalmente nula. Isso localiza a cauda em finalização transacional/sincronização, não no cálculo da identidade ou no tempo de query SELECT.
- **BLOQ-ET3-002 diagnosticado como variabilidade do caminho de gravação do ambiente, não regressão reproduzida da etapa3 nesse modelo.** Não se conhece a causa física (disco, VM, filtro/antivírus, escalonamento etc.), não foi autorizada intervenção e não se promete eliminar caudas. A comparação antiga17,307→28,193s permanece íntegra; não há prova retroativa de qual commit/fsync atrasou naquela execução. Os novos pares não demonstram ganho produtivo nem validam a nova RPC por benchmark legado.
- Controle independente sem importar bot:50 transações WAL/FULL +50 `os.fsync` em cada plataforma. Windows SQLite p50/p95/máx0,747/0,876/1,047ms, fsync0,702/1,354/1,458ms; Linux SQLite2,896/4,231/9,045ms, fsync2,763/4,465/8,346ms. Estas amostras não capturaram cauda de segundos: não negam a cauda medida no benchmark. JSONs `dealbot-etapa03-d02-io-{windows,linux}.json`.
- A primeira execução da sonda I/O Windows falhou somente ao limpar seu banco temporário porque `with sqlite3.connect` não fecha o handle. Corrigida a sonda temporária com `db.close()` e executada uma vez; não houve patch no bot, manipulação de serviços, varredura/apagamento geral ou alteração de teste para isso. Artefato temporário da falha preservado.
- Próximo controle D03: comparação única de fontes9p/ext4 com cProfile/mesmos hashes e commits medidos; depois uma suíte integral sem instrumentação no snapshot Linux compatível, independentemente do resultado. Não repetir automaticamente se falhar.

#### D03 — fontes Linux sem enfraquecer verificações

- Snapshot em `/home/alexandre_hp/.cache/opencode/dealbot-etapa03-d03-91e5mali`, criado em diretório exclusivo;64 arquivos Python/fixture JSON, cada cópia conferida com SHA256. Não inclui `.env`, sessões, SQLite privado, node_modules ou dados reais. Manifesto salvo no snapshot e em `dealbot-etapa03-d03-snapshot.json`; digest canônico do mapa de hashes `af14799a04db4f2431e5c48506f032e51ad1cf6a9801117234e56e099e685ed1`. Nova conferência do checkout após criar snapshot:64/64 hashes iguais, saída0.
- Comparação única instrumentada dos mesmos dois testes: fontes9p **2/2,3,765s**, fontes Linux **2/2,1,970s**. CPU de processo1,110/1,057s; `posix.stat`16.194/16.119 chamadas, tempo próprio2,876/1,048s; `linecache.checkcache`17.048/17.190 chamadas. Maior COMMIT/operação não deve ser confundido com esse tempo no loop. A captura de stacks do debug consulta fontes por `stat`, e o compartilhamento Windows acrescenta custo; venv/dependências continuam em9p, não houve reinstalação ou alteração de bibliotecas.
- Perfil é diagnóstico com overhead; somas por operação/fases concorrentes e tempos cumulativos cProfile podem se sobrepor e não são duração total nem latência produtiva. Não se atribui todo timeout a9p: as caudas transacionais D01/D02 são outro componente comprovado e ainda podem ocorrer com fontes Linux.
- Correção operacional mínima proposta: testes POSIX com fontes/temporários Linux, hashes conferidos e mesmas dependências/flags; README agora explicita esse caminho e exige preservar falhas/caudas anteriores. **Nenhum patch produtivo, watchdog, modo debug, PRAGMA ou assertion foi alterado nesta investigação.** Não foi encontrada justificativa para modificar algoritmo de oferta/identidade ou descartar commits.
- Verificação final prescrita: `wsl --distribution Ubuntu --cd /home/alexandre_hp/.cache/opencode/dealbot-etapa03-d03-91e5mali/bot --exec /bin/sh -c 'exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python -B -m unittest discover -s tests -v > /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa03-d03-suite-linux.log 2>&1'`. Uma execução sem sonda, sem seleção/skip de teste, iniciada após concluir todos os controles: **354/354 em149,976s,OK,zero skips,saída0**. Os dois seletores que falharam anteriormente passaram (linhas1/157 do log). Nenhum ciclo de repetição da suíte para obter verde.

#### Encaminhamento após diagnóstico

- **BLOQ-ET3-001 liberado para validação formal:** suíte integral em ambiente POSIX compatível aprovada, com64 hashes iguais ao checkout. As falhas integrais anteriores continuam sendo falhas reais registradas, não reinterpretadas como sucesso. Há dois componentes de ambiente demonstrados: espera transacional/pressão de I/O e custo de metadados das fontes9p no debug. No D01 lento atual, `/proc/pressure/io` acumulou≈9,69s de pressão `some` durante15,318s; nas amostras rápidas,≈0,04s por execução. É sinal sistêmico, não atribuição exclusiva ao processo nem identificação de hardware/antivírus.
- **BLOQ-ET3-002 liberado para validação formal:** pares finitos do benchmark mantiveram carga/dataset e reproduziram cauda maior na base; COMMITs, e não queries/cálculo novo de identidade, dominaram essa amostra. CA-030 exige medição honesta/separação de efeitos, não um SLA arbitrário de milissegundos. Não há ganho de produção alegado, nem prova de que todas as caudas desapareceram.
- `python -B -m pip check` no mesmo venv Linux: **No broken requirements found**, saída0. `git diff --check`: saída0, apenas avisos LF→CRLF já conhecidos. API63/63,UI13/13,SQL24 grupos,SQL etapa2,lint/tipos/build mantêm resultados anteriores desta implementação; **não foram reexecutados nesta investigação**, pois nenhum código/schema/dependência/teste foi modificado após essas verificações.
- Alterações desta investigação no checkout: **somente este PRD e o parágrafo de diagnóstico do README**. Sondas/JSON/logs/perfis/snapshot ficam exclusivamente em diretórios temporários de teste, preservados para auditoria. Nenhum hook de medição, patch de performance especulativo ou instrumentação entrou no caminho produtivo. Prevenção: documentar fontes Linux, hashes/ambiente e controles finitos; manter testes/durabilidade intactos.
- Sem reconfiguração/reinício de WSL/Windows, interferência em serviços, SQL remoto, commit/push/deploy ou etapa4. Não foram lidos segredos/estado privado. A causa física das caudas ainda pode merecer investigação operacional autorizada no futuro; não constitui garantia de latência de VPS ou inexistência de timeout neste host.
- T01–T08 concluídos na implementação. **Estado de saída `em_validacao`**, versão1/aprovação preservadas: não houve mudança material de requisito/política. Próximo comando: `/sdd-validar docs/sdd/incrementos/dealbot-etapa-03-identidade-deduplicacao.md`. Ainda não há aceite formal nem estado `concluido`.

### Retomada de implementação — correção V-ET3-001 (2026-11-06)

Nova invocação explícita de `sdd-implementar`; runtime global/PRD integral lidos, aprovação v1 preservada e base Git inalterada. Escopo: apenas corrigir unicidade/reconciliação numérica mantendo legado, apresentação e proteções. Todas as alterações anteriores/prompt do usuário são preservadas. Sem SQL remoto/publicação/etapa4.

Plano curto (uma atividade em andamento):
- **Concluído:** reproduzir com regressões permanentes e corrigir índices/escritores/preflight de modo transacional/idempotente.
- **Concluído:** verificar colisões com legado, replay da migração e concorrência em duas sessões reais; contratos Python/API e regressões direcionadas.
- **Concluído:** revisão independente do delta, suíte integral/documentação/evidências e retorno a `em_validacao` após verificações satisfatórias.

Exploração independente somente leitura identificou também a necessidade de limitar reconciliação textual a evidência legada sem outro proprietário numérico e evitar recriar os índices globais no começo de uma reaplicação integral do schema. Não será apagado dado legado nem inventado username/versão para passar testes.

Resultados parciais desta retomada (ainda não aprovam o incremento):
- Acrescentadas primeiro as duas regressões permanentes ao runner SQL. Banco novo `dealbot_teste_etapa3_v01_red`:18 grupos anteriores passaram e o novo caso provisório falhou no índice `uq_produto_msg`, saída1. Evidência negativa mantida; não foi reduzido assert ou renomeada a fixture para passar.
- Correção em código acrescenta `produtos.canal_id` nullable como proprietário do evento de origem, quatro índices parciais e helper invoker `_oferta_verificar_indices`. Somente índices globais herdados com definição exata conhecida são substituídos dentro da transação. Preservadas regras de negócio/permissões/nomes públicos; não há backfill numérico em massa. Ajustado também o escritor de decisões congeladas para confirmar a aparição por par numérico, nunca por OR textual de outro canal.
- Bloco atualizado aplicado somente ao banco sintético anterior `dealbot_teste_etapa3_validacao_20261106`, saída0. Os dois probes originais passaram a registrar: provisórios IDs42/43 e forte ID44 para ambos, em transação encerrada por ROLLBACK. Isso não substitui o runner novo completo/migração/concorrência.
- `python -B -m unittest tests.test_repository_identidade -v` no Python3.12/WSL: **13/13 em0,039s,saída0** (dois casos novos: separação de ID/texto nas duas RPCs e prontidão incompatível sem fallback). `npm test` backend: **63/63,1534,4399ms,zero skips,saída0**; fixture pública agora inclui `canal_id` interno inesperado e comprova que a whitelist não o publica.
- README/CLAUDE atualizados para índices parciais, limite de reconciliação e proibição de escritores antigos sobre o schema novo. Alterações anteriores à retomada preservadas em snapshot restrito `.../Temp/opencode/dealbot-v01-antes-7hubb6es` para revisão do delta, sem staging/reset. Snapshot novo para verificação POSIX: `/home/alexandre_hp/.cache/opencode/dealbot-etapa03-v01-hev88ypr`,64 arquivos Python/fixture com hashes iguais ao checkout, sem estado/credenciais.
- Agentes independentes: um explora/revisa somente SQL, outro acrescentou regressões somente ao runner SQL, sem executar DB/testes; não houve sobreposição de escrita. O agente principal revisou e ampliou os testes depois da entrega do agente.
- A revisão independente encontrou uma ambiguidade na primeira correção: aparência com outro nome pode ser renomeação do próprio dono, não prova de que o nome antigo ficou disponível. Removida essa inferência: mapa estrangeiro retido do mesmo produto/mensagem bloqueia claim textual; checkpoint explícito continua provando vínculo, mas não autoriza inventar posse da origem ambígua. Acrescentado teste do dono renomeado e asserts mais fortes: origem/aparição antigas permanecem intactas, e o checkpoint recebe sua aparição numérica própria. Não se mudou o requisito nem se relaxou um controle existente para passar.
- Outro achado condicional da revisão: evidência da origem de um alias não deve atribuir posse à origem do sobrevivente. Preservado o ID da linha de origem ao avaliar o claim e usada comparação canônica consistente na aparição; teste sintético cobre essa estrutura permitida pelo schema, sem alegar que escritores normais a produzam.
- Banco novo `dealbot_teste_etapa3_v01_green1`, mesmo comando `npm run test:sql:etapa3` com guardas locais anteriores: **36 grupos aprovados,saída0** em PostgreSQL17.5. Duas sessões reais PIDs11952/33652, barreira `pg_locks`, incluindo novos casos concorrentes de mesmo username/mensagem (provisórios separados e forte compartilhada). Repetição do bloco e do schema completo após duplicatas textuais manteve dados/índices; definições erradas, índices ausentes, tipos errados e duplicatas fazem preflight/gate falhar sem alterar dados/OIDs. Os15 helpers/RPCs permanecem invoker/restritos; não há relaxamento de RLS.
- SQL etapa2 `npm run test:sql` passou,saída0, em banco local novo `dealbot_teste_etapa3_v01_filtros`. Suíte bot integral do snapshot novo executada uma única vez sem sonda: **356/356 em100,483s,OK,zero skips,saída0**, log `.../Temp/opencode/dealbot-v01-suite-final.log`.
- A segunda revisão encontrou ainda a mesma proteção de ownership atravessando alias→sobrevivente: comparações de posse estrangeira precisam usar ID canônico, enquanto o claim da origem precisa preservar ID da linha original. Ajustadas ambas as exclusões e acrescentado contraexemplo permanente com mapa estrangeiro ligado ao sobrevivente. A terceira revisão estática retornou **nenhum achado restante no delta revisado**, sem alegar testes executados pelo revisor ou aprovação integral da etapa.
- Verificação SQL final em banco novo `dealbot_teste_etapa3_v01_green2`: **37 grupos aprovados,saída0**, mesmas guardas/comando; sessões independentes PIDs32752/808. O grupo novo protege origem/aparição não numeradas do alias quando a evidência de dono está no sobrevivente. Não houve falha nas duas execuções SQL posteriores à correção; a segunda foi motivada pela guarda adicional, não por repetição até verde.
- Conferência posterior do snapshot Python:64/64 arquivos ainda iguais ao checkout. A última alteração foi somente em SQL/teste SQL; não houve mudança Python após V-BOT356. `git diff --check` passou com os avisos EOL já conhecidos; revisão do delta SQL contra snapshot anterior confirmou somente mudanças necessárias ao achado.
- UI13/13,lint/typecheck/build e simulações mantêm evidência da validação anterior da seção16; **não reexecutados nesta retomada**, pois seus fontes/contratos públicos não mudaram e o benchmark fake não exercita SQL real. Não se atribui a esta correção ganho de desempenho nem validação em produção. Catálogo do helper de índices verificado em PostgreSQL17.5; compatibilidade de versão/schema de produção continua sujeita ao preflight autorizado futuro.
- Estado de saída: **`em_validacao`**, T03/T08 novamente marcadas completas na implementação; aprovação/versão1 preservadas. Nenhuma regra/requisito/risco foi ampliado; a troca restrita dos índices globais conhecidos é necessária à identidade numérica já aprovada, sem apagar dados ou relaxar a unicidade das linhas legadas sem número.
- Cluster local exclusivo parado limpidamente por `pg_ctl -D .../dealbot-etapa03-pg-isolado -m fast -t 90 -w stop`,saída0; bancos e artefatos preservados. Nenhum SQL remoto/credencial real, commit/push/deploy, imagem migrada ou etapa4. Mudanças desta retomada: `supabase/schema.sql`, runner SQL, testes de contrato Python/API, README/CLAUDE e este PRD; restante do trabalho preexistente preservado.

### Registro original de planejamento (continuação histórica)

- Planejamento: runtime global e prompts/template lidos; base/worktree registrados; código/contratos/schema/testes/documentação relacionados inspecionados; fontes públicas primárias consultadas com limites explícitos.
- Criado somente este PRD. Nenhum código, schema, manifest, documentação preexistente ou prompt do usuário foi alterado; nenhum commit/push/deploy/SQL remoto.
- Na saída do planejamento a implementação ainda não havia iniciado: estado `rascunho`, versão1, aprovação pendente. A aprovação e implementação posteriores estão registradas acima.

### Verificações de planejamento

| Comando/procedimento | Resultado | Limite |
|---|---|---|
| `git rev-parse --show-toplevel` | Raiz do cabeçalho confirmada. | Consulta local somente leitura. |
| `git status --short --branch` | `main...origin/main`; cinco prompts não rastreados preexistentes; sem modificações rastreadas antes do PRD. | Não significa sincronização remota recém-verificada; sem fetch. |
| `git log -1 --format="%H%n%s"` | Commit base confirmado: `9a2e095203172437a66ebea062cb101cc5f524bb`. | Não executa nem valida testes desse commit. |
| `git worktree list --porcelain` | Um worktree, na raiz atual, branch `main`. | Nenhum worktree/branch criado. |
| Inspeção de runtime/instruções/PRDs/código e fontes públicas | Evidências na seção 3; não encontrado PRD da mesma entrega. | Não comprova schema/dados/serviços em produção. |
| Status/diff após criação | Apenas este PRD novo além dos cinco prompts preexistentes; `git diff --stat` sem alterações rastreadas. | PRD ainda não rastreado, sem staging/commit. |
| `git diff --no-index --check -- NUL docs/sdd/incrementos/dealbot-etapa-03-identidade-deduplicacao.md` | Sem diagnóstico de whitespace; aviso de conversão LF→CRLF, saída 1 da comparação com arquivo vazio. | Não é teste funcional nem build. |
| Testes, simulação, lint, tipos, build e migrações | **Não executados neste planejamento.** | Execução e evidências obrigatórias na implementação/validação futura. |

### Autoavaliação

- [x] Comportamento atual separado do desejado e sustentado por evidências relevantes.
- [x] Escopo/fora de escopo explícitos; nenhum requisito de implementação do anexo executado neste comando.
- [x] Identidade, recência, expiração, desconhecidos, legado e migração definidos; decisões propostas não apresentadas como fatos já entregues.
- [x] Requisitos/critério/testes verificáveis, incluindo concorrência real e suas limitações.
- [x] Modo/risco e proteções justificados; arquitetura existente e linguagem preservadas.
- [x] Sem pergunta bloqueante atual; premissas/gates explícitos; aprovação pendente.
- [x] Único artefato criado: este PRD; nenhuma implementação ou operação Git/remota de escrita.

## 16. Resultado da validação

**Registro histórico da primeira validação formal em2026-11-06. Veredito então: solicitar correções; estado de saída então: `em_implementacao`.** Havia um bloqueante funcional, apesar das suítes existentes verdes. As matrizes abaixo descrevem o código anterior à correção e não foram retroativamente aprovadas. A implementação posterior e a situação corrente estão ao final desta seção; aguarda-se nova validação formal, sem aceite parcial ou alteração material da versão1 aprovada.

### Pré-condições e classificação do diff

- Raiz confirmada por `git rev-parse --show-toplevel`; runtime local inexistente, usados integralmente `_comum.md`/`validar.md` de `C:/Users/Alexandre_HP/.config/opencode/.sdd-lite/prompts/`. PRD integral, CLAUDE/README, contratos, padrões e testes revisados. Não há AGENTS.md no workspace. Git em `main`, mesmo commit9a2e095203172437a66ebea062cb101cc5f524bb e único worktree; aprovação v1 válida. Estado de entrada `em_validacao`, T01–T08 então marcados completos.
- **Previstas:** identidade/resolvedor, RPC/SQLite/cache/checkpoints, models/services API/limpeza, card/tipos mínimos, configuração/exemplos, testes/simulações e documentação. **Necessárias:** gate/pins dos jobs legados, reserva de remoção e confirmação remota, whitelist pública e propagação de erro técnico. Não constituem etapa4.
- **Desvios menores explicados:** advisory lock global em vez de locks por identidade (mais conservador, serializa escrita); expectativas antigas de versão5→6/defaults e classe/contagem de workers do teste de encerramento. Revisado o diff: não foram removidos asserts de watchdog/durabilidade/compatibilidade nem alterados os dois testes antigos de checkpoints/rajada ou o benchmark original para obter verde.
- **Preexistentes do usuário:** cinco prompts não rastreados; não editados/incluídos. Toda a implementação anterior permaneceu preexistente a esta invocação de validação. **Fora do escopo acrescentado nesta validação:** nenhum. Não foram modificados código, migração, dependências ou testes permanentes; somente este PRD foi atualizado. Reprodutor/SQL/saídas locais ficam no temporário aprovado, não em relatório paralelo do projeto.

### Comandos e evidências desta validação

Prefixo dos artefatos abaixo: `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/`. Todos os testes usam dados sintéticos; nenhum `.env`/estado privado real foi lido.

| ID | Comando/procedimento exato ou parâmetros | Resultado real e limite |
|---|---|---|
| V-BOT | `wsl --distribution Ubuntu --cd /home/alexandre_hp/.cache/opencode/dealbot-etapa03-d03-91e5mali/bot --exec /bin/sh -c 'exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python -B -m unittest discover -s tests -v > /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa03-validacao-suite.log 2>&1'` | **354/354,107,354s,OK,zero skips,saída0**, execução única. Python3.12.3/WSL, fontes Linux;64 hashes do manifesto conferidos contra checkout antes de executar. Testes de migração, sinais, SDK, retenção e limites incluídos, sem sondas/debug/WAL/FULL relaxados. |
| V-PIP | Mesmo Python Linux: `python -B -m pip check` | **No broken requirements found**, saída0. Dependências existentes, sem instalação/atualização. |
| V-API | Em `backend/`: `npm test` | **63/63**,1469,9484ms,zero skips,saída0. SDK/rotas/serviços com HTTP/Auth/Storage falsos; não PostgREST real. |
| V-UI | Em `frontend/`: `npm test` | **13/13**,1674,0887ms,zero skips,saída0. Renderização real do componente com fronteiras falsas; não browser E2E. |
| V-SQL | Em `backend/`: `npm run test:sql:etapa3`, `DEALBOT_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/dealbot_teste_etapa3_validacao_20261106`, `DEALBOT_TEST_POSTGRES_DISPOSABLE=SIM`, `DEALBOT_TEST_PSQL=C:/Program Files/PostgreSQL/17/bin/psql.exe` | **24 grupos aprovados,saída0** em banco novo vazio/Postgres17.5. Sessões reais PIDs16720/32916, barreira `pg_locks`; DDL duplo, legado/preflight/rollback, preços/tempo, fusão, exclusão/mídia/limpeza/grants/RLS. Papéis/auth/storage sintéticos; o caso V-PROBE não existe nesse runner. |
| V-FILTROS | Em `backend/`: `npm run test:sql`, URL local de banco novo `dealbot_teste_etapa3_validacao_filtros`, `PGPASSFILE=NUL`, diretório PostgreSQL17/bin no PATH | Aplicação dupla/defaults/constraints/preflight/legado de filtros aprovados,saída0. Não substitui concorrência etapa3. |
| V-QUAL | Em `frontend/`: `npm run lint`; `npx --no-install tsc --noEmit --incremental false`; `npm run build` | Os três **aprovados,saída0**, build6 páginas. Next14.2.5/Node24.11.1; não foi validado Node20 de produção. Somente `.env.example` presente; variáveis fictícias `NEXT_PUBLIC_SUPABASE_URL=https://teste.invalid`, `NEXT_PUBLIC_SUPABASE_ANON_KEY=chave-ficticia-validacao`, `NEXT_PUBLIC_API_URL=http://localhost:3333`, `NEXT_TELEMETRY_DISABLED=1`. |
| V-SIM | Em `bot/`, Windows/Python3.14.4: `python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1` | Saída0;130/130 ofertas/cards,zero falhas,workers máximos4/1.6,420712s,20,246976ofertas/s; live p50/p95/máx365,273/595,431/644,159ms; histórico3973,207/6173,984/6387,834ms. Dataset igual ao baseline. Arquivo `dealbot-etapa03-validacao-simulacao.json`; modelo legado de5 esperas, não benchmark da RPC nova. Caudas anteriores preservadas, sem ganho produtivo alegado. |
| V-SIM2 | Em `bot/`: `python -B -m simulacao_identidade --seed 42 --pares 10 --cenario todos --db-ms 20 --resolucao-ms 200 --oferta-workers 4 --enriquecimento-workers 1` | Saída0; arquivo `dealbot-etapa03-validacao-simulacao-identidade.json`. Frio/lento:20 ofertas salvas enquanto resolução bloqueada,20→10cards,20 aparições mantidas,10 aliases; convergência0,901310/7,271754s após liberação. Quente:20hits,zero rede,10cards/20aparições. Todos terminam sem pendências de oferta/mídia/enriquecimento/ack; máximos4/1/1 e1rede. Uma espera fake/RPC; não comparar com5 do cenário original. |
| V-MANUAL | Inspeção de implementação/JSON whitelist/testes renderizados/ordem de migração/rollback; chamada pura de `identificar` com fixtures Amazon/ML | Duas uniões (Amazon com apenas `tag` diferente, ML com declaração completa igual) e duas separações (seller Amazon, variante ML) retornaram os quatro booleanos esperados. Casos de subida/queda/nulo/foto nula confirmados nos asserts V-API/V-UI, sem ambiente de usuário/browser real. Rollback transacional/migrações exercitados em V-BOT/V-SQL; rollback operacional documentado é pausa com preservação de estado, não downgrade destrutivo executado. |
| V-PROBE | `python -B .../dealbot-etapa03-validacao-probes.py`, depois `psql -X -w -h 127.0.0.1 -p 55439 -U postgres -d dealbot_teste_etapa3_validacao_20261106 -v ON_ERROR_STOP=1 -P pager=off -f .../dealbot-etapa03-validacao-probes.sql`, `PGPASSFILE=NUL` | **Dois contraexemplos de V-ET3-001**, em transação com ROLLBACK. Script captura a exceção e sai0 para mostrar SQLSTATE/índice; isso **não é aprovação**. Saída: `cards_provisorios:23505:uq_produto_msg`; `aparicoes_mesmo_card:23505:uq_aparicao_canal_msg`. |
| V-DIFF | `git diff --check`; revisão de fontes/entradas/erros/logs/projeção/privilégios | Saída0, apenas avisos LF→CRLF; sem normalização global. Nenhum código temporário no caminho produtivo, chave real no diff ou uso de clientes reais nos testes identificado. |

Baseline anterior não foi recriado como se fosse anterior às mudanças: conferida a evidência da seção15 (257/257 bot no snapshot base,40/40 API,7/7 UI, simulação e diagnósticos D01–D03), preservando saída externa1 do PowerShell no log imutável. Não há lint Python/build backend configurados. Não há mudança de layout/fluxo a exigir novo E2E de navegador; verificação de componente/contratos é a categoria aplicável, com limitação explícita. Nenhum desses limites justifica ignorar V-ET3-001.

### Achado bloqueante V-ET3-001 — unicidade textual ainda impede eventos numéricos distintos

**Local:** `supabase/schema.sql:29-30,46-47` mantém `uq_produto_msg` e `uq_aparicao_canal_msg` por `(canal_origem,telegram_msg_id)`; o bloco novo acrescenta índice numérico em235-236, mas continua escrevendo username em478/512. O índice numérico adicional não neutraliza as restrições textuais antigas.

**Reprodução local:** dois eventos com `canal_id` diferentes, mesmo `msg_id`, mesmo username textual congelado. Isso pode ocorrer sem múltiplos coletores quando o username de um canal muda/é reutilizado por outro, enquanto linhas/pendências antigas conservam o texto original.

1. Provisórios: canais-99101/-99102, mensagem500001, username sintético `alias_reciclado_cards_provisorios`; mesmo produto/link e identidade insuficiente obtida pelo `identificar(produto)` real. A segunda gravação deveria criar outro card, mas falha em `uq_produto_msg`.
2. Forte: canais-99201/-99202, mensagem500002, username sintético `alias_reciclado_aparicoes_mesmo_card`; identidade real completa Amazon fornecida por `contexto_completo()` da fixture. A segunda gravação deveria reutilizar o card e acrescentar aparição numérica distinta, mas falha em `uq_aparicao_canal_msg`.
3. Os dois casos usam a RPC real e PostgreSQL real, sem patch no código. O primeiro ensaio do provisório usava identidade insuficiente de outra URL sintética; antes de consolidar o achado, a fixture foi corrigida para derivar identidade do próprio produto/link e executada novamente. **Os dois erros permaneceram idênticos**; o caso forte já usava payload consistente. Não é repetição de watchdog nem busca por execução verde. Cada ensaio terminou com ROLLBACK; fixtures do runner e dados reais não foram apagados.

**Impacto:** promoção válida fica sem efeito remoto e em retry por colisão que não representa o mesmo evento. Não há prova de fusão incorreta nesse caso (a transação aborta), mas a publicação/aparição exigida não ocorre. Afeta RF-001/003/011, principalmente CA-001/008 e completude da migração CA-026. Testes existentes verificam renomeação do mesmo evento, não reutilização do texto entre eventos numéricos diferentes.

**Correção requerida em implementação:** compatibilizar índices e escritores com a identidade numérica para novos eventos, conservando reconciliação/hash/dados legados e apresentação dos canais. Acrescentar regressões permanentes dos dois casos, colisão com legado e reaplicação da migração; repetir isolamento entre sessões e verificações afetadas. Não basta remover índice indiscriminadamente ou alterar usernames/dados para o teste passar. Nenhuma nova regra de negócio foi proposta.

**Não corrigido pelo ciclo curto:** envolve migração/constraints, compatibilidade de escritores e novas verificações em vários blocos. `validar.md:62-65` exige retorno à implementação. Não foi aplicada alteração de schema/código para esconder o achado. Não há pergunta bloqueante de escopo; a versão1 permanece aprovada e o trabalho válido é preservado.

### Matriz de requisitos e regras

`atendido` abaixo significa comportamento verificado nos formatos/caminhos descritos, não aprovação global da entrega nem garantia de infraestrutura real.

| ID | Resultado | Implementação / procedimento / evidência |
|---|---|---|
| RF-001 | parcialmente atendido | `identidade.py` e chave numérica SQLite/`oferta_eventos`; V-BOT positivos/conflitos. V-PROBE demonstra interferência residual do username na unicidade remota. |
| RF-002 | atendido | `normalizar_url`, `_formato`, `identificar`; V-BOT testa tokens/ordem/repetidos/vazios/seller/fragmentos/formatos; V-MANUAL confirma duas uniões/separações. Suporte é restrito, não dedup universal. |
| RF-003 | parcialmente atendido | `oferta_registrar`, lock transacional/mapa; V-SQL grupos4/19/20 provam retry/duas sessões. V-ET3-001 impede registrar outros eventos válidos. |
| RF-004 | atendido | `_oferta_resumir`/numeric e metadados; V-SQL grupos5/6/8, V-UI e V-BOT distinguem zero/nulo/cupom/condições. |
| RF-005 | atendido | UTC/tupla/`expira_em`/janela congelada em RPCs; V-SQL grupos5/6/9–12/23, histórico/expiração/relógio adiantado. |
| RF-006 | atendido | `PipelineIdentidade`, cache/fila/checkpoints SQLite; V-BOT barreira/cache/restart/resposta perdida/teto de tentativas e V-SIM2. Ressalva de DNS/encerramento abaixo. |
| RF-007 | atendido | `resolvedor.py` valida cada URL/DNS/IP, fixa socket/TLS/SNI e aborta após headers; V-BOT rede falsa cobre SSRF/proxy/redirect/fallback/bytes/DNS/fechamento. Nenhuma loja consultada em teste. |
| RF-008 | atendido | `oferta_enriquecer`, `_oferta_canonico`, `oferta_foto` e mídia coordenada; V-SQL grupos13–15/21/22/24, V-BOT checkpoint e V-API limpeza. |
| RF-009 | atendido | Models/services canônicos com whitelist e erros técnicos; V-API/V-UI, SQL buscar/remover/foto, sem redesign. O bloqueio de criação/aparição está em RF-001/003. |
| RF-010 | atendido | Pins/ack, gate legado, `oferta_limpar`, reserva/ack mídia; V-SQL grupos14/16–18/22/24 e V-BOT retenção real SQLite; sem TTL de trabalho recuperável. |
| RF-011 | parcialmente atendido | Migração v6 e preflight/hash congelado passam V-BOT/V-SQL grupos1–4/18. Falta compatibilizar unicidade legada com eventos numéricos novos: V-ET3-001. |
| RF-012 | atendido | README/CLAUDE/exemplos e logs por códigos/IDs, este PRD com comandos/limites/achado/continuidade; V-DIFF/V-MANUAL. Nenhuma conclusão fictícia por testes verdes. |
| RN-001 | atendido | Mesmo par numérico encontra vínculo antes da janela; V-SQL grupos4/10/19 e V-BOT resposta perdida. V-ET3-001 é colisão entre pares diferentes, não replay aceito do mesmo par. |
| RN-002 | atendido | Preço fora da chave, comparação comercial completa além do hash; V-BOT identidade e V-SQL grupos7/8. |
| RN-003 | atendido | Estados desconhecido/conhecido/não aplicável; V-BOT omissões/conflitos/cupons/zero; V-UI nulo/zero. |
| RN-004 | atendido | `vincular` antes de agendar resolução/mídia; V-BOT barreira e V-SIM2 frio/lento. |
| RN-005 | atendido | Tempo original/instâncias/tupla, mapa antes da janela; V-SQL grupos5/6/9–12/23. |
| RN-006 | atendido | Transferência explícita/menor ID, foto adotada, aliases e estados terminais; V-SQL grupos13–15/21/22. |
| RN-007 | atendido | Pin sem TTL/retentiva após ack, purga de finalizados; V-SQL grupos16/17/24 e V-BOT retenção, sem garantia de replay após purga total. |
| RN-008 | atendido | Algoritmo/hash/decisão legados preservados em preflight/migração/restart; V-BOT migrações/checkpoints e V-SQL grupo18; sem backfill. |
| RNF-001 | atendido | Workers/pool DNS/lotes/bytes/hops/tentativas validados; V-BOT/V-SIM2/V-API limites. A syscall DNS não é interrompível; não há garantia de saída física rígida do interpretador isolado, ver limitação. |
| RNF-002 | atendido |14 funções invoker com EXECUTE restrito, tabelas internas RLS sem políticas públicas; V-SQL grupo3 nega anon/authenticated e permite service_role, sem desabilitar RLS. |
| RNF-003 | atendido | Stack/MVC/rotas/tipos compatíveis, whitelist API e raw_text limitado; V-API/V-UI/V-QUAL/V-DIFF. |
| RNF-004 | atendido | WAL/FULL/executor/claims e recuperação preservados; V-BOT354 testes incluindo sinais/checkpoints/justiça. Caudas ambientais anteriores mantidas no registro, não relaxadas. |
| RNF-005 | atendido | Postgres com sessões independentes/rede falsa/dataset conferido; V-SQL/V-SIM/V-SIM2 e D01–D03, limites/saídas negativas explícitos. |

### Matriz individual de critérios de aceitação

| CA | Resultado | Procedimento / evidência |
|---|---|---|
| CA-001 | parcialmente atendido | V-BOT formatos fortes Amazon/ML + V-SQL grupo8 passam entre usernames distintos; V-PROBE forte falha na segunda aparição quando username é reutilizado. |
| CA-002 | atendido | V-BOT identidade insuficiente/IDs distintos e V-SQL grupo7, sem chave por título/foto/preço. |
| CA-003 | atendido | V-BOT todas as dimensões conflitantes/seller e V-SQL grupo8, V-MANUAL separações. |
| CA-004 | atendido | V-BOT cupom omitido/case/conflito e elegibilidade/pagamento/restrições, V-SQL grupo8. |
| CA-005 | atendido | V-BOT testes `NormalizacaoEtapa3Tests` e queries desconhecidas; representação original preservada. |
| CA-006 | atendido | V-BOT `tag` restrito, `linkCode` exato conservado, distinções de esquema/host/barra/porta. |
| CA-007 | atendido | V-SQL grupos4/10, V-BOT resposta perdida/congelamento/restart e legado; renomeação do mesmo evento não regrava. Não cobre a reutilização entre pares diferentes de V-ET3-001. |
| CA-008 | parcialmente atendido | V-SQL grupo19 duas conexões/PIDs/barreira reais passa nos casos existentes; V-PROBE revela que a garantia não vale para eventos numéricos distintos com o mesmo texto de username/mensagem. |
| CA-009 | atendido | V-SQL grupo5 sequências300→250→300 e preço anunciado separado; V-UI queda/subida. |
| CA-010 | atendido | V-SQL grupo5, V-UI e V-BOT distinguem zero/nulo sem preço ocultamente vigente/queda fictícia. |
| CA-011 | atendido | V-SQL grupos5/6/9/20, histórico e desempate numérico em ordem inversa. |
| CA-012 | atendido | V-SQL grupos10–12/16, vínculo antigo/validade/instância nova e limpeza; V-API elegibilidade. |
| CA-013 | atendido | V-BOT barreira com duas URLs/duas origens + V-SIM2 frio; V-SQL grupos13/15 garante fusão remota separadamente. Fake não substitui SQL. |
| CA-014 | atendido | V-BOT barreira/timeout/teto de workers e V-SIM2 lento; ofertas já salvas antes de liberar rede. |
| CA-015 | atendido | V-BOT cache positivo/negativo/restart/versão/TTL/tentativas; V-SIM2 quente20 hits/zero rede. |
| CA-016 | atendido | V-BOT resolvedor: URL/DNS/redirect/rebinding/IP/SNI com transporte falso, destino proibido não conectado. |
| CA-017 | atendido | V-BOT resolvedor: hops/tempo/HEAD405/501/Range/compressão/bytes/DNS/fechamento/proxy; sem leitura de corpo. |
| CA-018 | atendido | V-BOT respostas perdidas/congelamento/restart e V-SQL grupos4/10; evidência/mapa retidos, sem redecisão. |
| CA-019 | atendido | V-SQL grupos13/15 injeta rollback e convergência de aliases/menor ID; V-BOT resultado de reconciliação persistido/reaplicado. |
| CA-020 | atendido | V-SQL grupos13–15/22, referência de foto adotada e remoção protegida; V-BOT/V-API compensação/limpeza. |
| CA-021 | atendido | V-SQL grupos21/22 disputas com sessões independentes e estados terminais; V-API falha/retomada Storage falso. |
| CA-022 | atendido | V-API consulta SDK real com HTTP falso, whitelist e erro técnico; V-SQL busca/remover canônicos. Sem servidor PostgREST real, limite declarado. |
| CA-023 | atendido | V-UI13 testes, V-QUAL e inspeção de tipos/renderização legado/queda/subida/nulo/foto/canais. |
| CA-024 | atendido | V-BOT retenção/cache/checkpoints e V-SQL grupos16/17/24: resumo/pins conservados, purga após ack. |
| CA-025 | atendido | V-BOT migrações0–5→6 e reabertura/falha de DDL, decisão/hash byte a byte/claims/mídia/fronteiras; sem nova aprovação no retry. |
| CA-026 | parcialmente atendido | V-SQL grupos1/2/18 prova aplicação dupla/legado e falha atômica; V-BOT schema ausente preserva jobs. Migração ainda mantém restrições incompatíveis com identidade numérica: V-PROBE. |
| CA-027 | atendido | V-BOT `test_serializacao_e_deadlock_retornam_a_fila_sem_redecidir` e schema ausente/retry; sem descartar pendência. V-SQL prova transações reais, não injeta deadlock real por lock global único. |
| CA-028 | atendido | V-SQL grupo3: invoker/grants das14 funções e RLS, negação real nos papéis não autorizados. |
| CA-029 | atendido | V-BOT/V-API/V-UI/V-QUAL aprovados sem skips/relaxamento; baseline/falhas antigos preservados. Suítes verdes não anulam o contraexemplo funcional V-ET3-001. |
| CA-030 | atendido | V-SIM/V-SIM2 + baseline/D01–D03, datasets iguais/custos separados/fases e limites medidos; sem SLA ou ganho produtivo alegado. |
| CA-031 | atendido | README/CLAUDE/exemplos/PRD revisados, escopo/limites/migração/rollback/continuidade e esta validação registrados; produção/etapa4 intocadas. |

**Resumo:** RF9 atendidos/3 parcialmente atendidos; RN8 atendidas; RNF5 atendidos; CA28 atendidos/3 parcialmente atendidos. Esse resumo não é aprovação parcial: V-ET3-001 impede conclusão integral. T03/T08 reabertas; demais tarefas/alterações válidas preservadas.

### Segurança, limitações, correções e próximo passo

- **Pontos positivos confirmados:** decisão/hash legado não reavaliados; oferta precede rede; comparação comercial além do hash; socket preso ao IP validado/TLS; fusão/limpeza/foto serializadas no banco; whitelist dupla no payload da API; referências de recuperação não usam TTL cego.
- **Importante, sem novo bloqueio além de V-ET3-001:** a cobertura permanente não exercita reutilização de username entre pares numéricos distintos. Os dois casos devem entrar na próxima implementação, não só permanecer como probe temporário. Não foram exigidas refatorações por preferência de estilo ou funcionalidade de etapa4.
- **Limitação DNS/encerramento:** o prazo limita a espera/ciclo e há uma única syscall pendente; getaddrinfo já iniciado não é interrompido e a thread não daemon pode atrasar saída do interpretador. `bot/dealbot.service` já define `TimeoutStopSec=60` para a fronteira externa. Isso não foi testado contra DNS/SO realmente travado nem constitui garantia de deadline físico em execução avulsa. Não se enfraqueceu o transporte para contornar a limitação.
- **Limites gerais:** fixtures sintéticas/sem corpus privado, formatos restritos, sem browser real/loja/Telegram/Supabase/PostgREST/Storage/VPS reais; RLS/grants testados com papéis sintéticos em Postgres local. Não foi realizado deploy, rollback de produção, downgrade de dados, migração de imagens, E2E real ou auditoria geral de dependências/autenticação fora do escopo. As caudas físicas do host continuam desconhecidas, com falhas históricas preservadas.
- **Operações locais:** cluster de teste exclusivo iniciado em127.0.0.1:55439; novos bancos vazios criados sem DROP, bases/artefatos preservados. Foi parado limpidamente; reaberto apenas para repetir o probe com a fixture provisória consistente e parado novamente por `pg_ctl -D .../dealbot-etapa03-pg-isolado -m fast -t 90 -w stop`, saída0. Nenhum serviço do usuário/WSL foi reiniciado/reconfigurado.
- **Correções nesta validação:** nenhuma de código/schema/contrato. Somente estado, checklist e resultado deste PRD; fixture do reprodutor temporário ajustada conforme registrado. Nada staged/commitado/publicado; sem credenciais reais/SQL remoto/etapa4.
- **Próximo passo:** `/sdd-implementar docs/sdd/incrementos/dealbot-etapa-03-identidade-deduplicacao.md`, corrigindo V-ET3-001, acrescentando as regressões e repetindo verificações afetadas. Depois invocar `sdd-validar` novamente. A autorização atual de validação não foi usada para redesenhar migração; não há requisito/versão novo nem necessidade de reaprovar a regra numérica já aprovada.

### Situação histórica após a retomada de implementação

**Estado então: `em_validacao` — correção V-ET3-001 implementada e verificada localmente, aguardando nova validação formal.** O veredito/matrizes anteriores permanecem históricos; a conclusão da revalidação aparece na subseção seguinte.

| Ponto reaberto | Evidência nova de implementação |
|---|---|
| RF-001/003/011; CA-001/008/026 |37 grupos em Postgres real: provisórios separados/fortes compartilhadas com mesmo username/mensagem, dois canais numéricos, legado nas duas ordens, hashes congelados/retry, checkpoint e posse estrangeira/alias, índices/prontidão/falha atômica e replay integral. Reavaliação formal pendente. |
| Compatibilidade pública e RPC |13 testes de contrato Python direcionados e63 testes API aprovados; campo interno `canal_id` não publica na API. Nenhum payload/requisito público alterado. |
| Regressão integral |356/356 bot em Python3.12/WSL,100,483s,zero skips,sem watchdog/debug/WAL/FULL relaxados. Fontes Linux e64 hashes iguais. |
| Revisão |Revisor independente apontou duas variantes de proteção de posse/alias; ambas corrigidas com regressões. Inspeção final sem achados restantes no delta, limitada a revisão estática. |

Comando de bot desta retomada: `wsl --distribution Ubuntu --cd /home/alexandre_hp/.cache/opencode/dealbot-etapa03-v01-hev88ypr/bot --exec /bin/sh -c 'exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python -B -m unittest discover -s tests -v > /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-v01-suite-final.log 2>&1'`.

Comando SQL final: em `backend/`, `npm run test:sql:etapa3` com `DEALBOT_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/dealbot_teste_etapa3_v01_green2`, `DEALBOT_TEST_POSTGRES_DISPOSABLE=SIM` e `DEALBOT_TEST_PSQL=C:/Program Files/PostgreSQL/17/bin/psql.exe`. A prova é de sessões reais, não PGlite/fake. Comandos/saídas parciais, negativos e limites estão na retomada da seção15.

**Próximo passo então indicado:** `/sdd-validar docs/sdd/incrementos/dealbot-etapa-03-identidade-deduplicacao.md`. Não iniciar etapa4, publicar ou aplicar migração remotamente. Nenhuma declaração `concluido` foi feita pela implementação.

### Revalidação formal — 2026-11-06 a 2026-11-09 (resultado corrente)

**Veredito: aprovado no escopo local da etapa3. Estado final: `concluido`.** Os12 RF,8 RN,5 RNF e31 CA estão atendidos nas condições verificadas abaixo; nenhuma pendência obrigatória ou bloqueante aberto. V-ET3-001 encerrado por verificação da correção, não por dispensa do requisito. Produção não foi validada nem alterada. Versão/aprovação1 mantidas; nenhuma nova regra/contrato/risco foi aprovado implicitamente.

#### Pré-condições, revisão e escopo

- Runtime global confirmado pela ausência de `.sdd-lite` na raiz. `_comum.md` e `validar.md` lidos integralmente; PRD integral, CLAUDE, README, critérios, fontes, testes e código revisados. Sem AGENTS.md encontrado. Entrada `em_validacao`, T01–T08 completas, sem pergunta bloqueante. Git permanece `main`, commit9a2e095203172437a66ebea062cb101cc5f524bb, único worktree; sem staging/commit/reset/fetch.
- Classificação reafirmada: **previstas** identidade/URL/resolução/cache/SQLite/RPCs, API/card mínimos, testes/simulações/configuração/documentação; **necessárias** preflight/gate/pins legados, reserva/ack de mídia, projeção pública e correção dos índices/escritores numéricos. **Desvios menores documentados**: lock transacional global conservador e expectativas v6/defaults/contagem de workers ajustadas. **Preexistente**: toda implementação recebida e cinco prompts do usuário. **Fora de escopo acrescido**: nenhum. Preservadas todas as alterações locais.
- Conferido o delta de índices e escritores: quatro índices parciais separando linhas numeradas e não numeradas; migração atômica substitui somente definições globais conhecidas, sem CASCADE/apagar duplicatas ou numerar histórico em massa. Reaplicação integral não recria restrição textual global. Reconciliação por texto não adota v2 nem posse estrangeira comprovada, inclusive através de alias/canônico. Checkpoint prova vínculo, sem inventar posse de uma origem ambígua. IDs/hash/grafia/datas/decisões permanecem preservados.
- Revisados entradas/erros/whitelists/estados de UI/tipos, parâmetros, grants/RLS, logs, allowlist/IP efetivamente conectado/TLS/redirect/fallback/limites, refs/retentiva e ordem de transição. Padrões positivos: oferta antes da rede, comparação comercial completa além do hash, negação de privilégios das15 funções e remoção física precedida de reserva durável. Nenhum novo bloqueante, achado importante obrigatório ou pergunta ao autor identificado. Não foram solicitadas refatorações estéticas ou funções da etapa4.
- **Correções nesta invocação:** nenhuma em código/schema/testes permanentes. Somente este PRD foi atualizado; scripts complementares e saídas sintéticas ficam no temporário aprovado, sem relatório paralelo do projeto. As correções de V-ET3-001 pertencem à implementação anterior, não foram feitas silenciosamente durante validar.

#### Comandos e evidências da revalidação

Prefixo dos artefatos: `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/`. Testes usam somente fixtures sintéticas, sem ler `.env`/sessões/estado privado reais.

| ID | Comando/procedimento | Resultado comprovado / limite |
|---|---|---|
| R-BOT | `wsl --distribution Ubuntu --cd /home/alexandre_hp/.cache/opencode/dealbot-etapa03-v01-hev88ypr/bot --exec /bin/sh -c 'exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python -B -m unittest discover -s tests -v > /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa03-revalidacao-suite.log 2>&1'` | **356/356,122,000s,OK,zero skips,saída0**. Execução única, sem sondas/watchdog/debug/WAL/FULL relaxados. Python3.12.3/WSL, fontes Linux;64 hashes contra checkout conferidos antes e novamente na continuidade de09/11, zero divergências. Venv existente em `/mnt/c`; não se promete ausência de caudas. |
| R-PIP | `wsl --distribution Ubuntu --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python -B -m pip check` | **No broken requirements found**,saída0; sem instalar/atualizar dependências. |
| R-API | Em `backend/`: `npm test` | **63/63,zero skips,saída0**. Rotas/models/serviços e SDK com HTTP/Auth/Storage falsos; não servidor PostgREST real. |
| R-UI | Em `frontend/`: `npm test` | **13/13,zero skips,saída0**. Componente real renderizado, fronteiras falsas; não browser E2E. |
| R-SQL | Em `backend/`: `npm run test:sql:etapa3`; `DEALBOT_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/dealbot_teste_etapa3_revalidacao_20261106`, `DEALBOT_TEST_POSTGRES_DISPOSABLE=SIM`, `DEALBOT_TEST_PSQL=C:/Program Files/PostgreSQL/17/bin/psql.exe` | **37 grupos,saída0**, PostgreSQL17.5 real, banco novo vazio. PIDs34604/34684 independentes e barreira `pg_locks`; terceira conexão confere resultados. Grupos21–32 incluem usernames reutilizados, colisão legada, v2 não adotada por texto, dono renomeado/canônico, preservação integral, aplicação dupla/bloco/schema completo e concorrência. Preflight/gate rejeitam definição/tipo/duplicatas incompatíveis atomicamente.15 funções invoker restritas e RLS testadas. Papéis/auth/storage são sintéticos. |
| R-FILTROS | Em `backend/`: `npm run test:sql`; URL local `postgresql://postgres@127.0.0.1:55439/dealbot_teste_etapa3_revalidacao_filtros`, `PGPASSFILE=NUL`, PostgreSQL17/bin no PATH | **Aprovado,saída0** em banco novo: aplicação dupla/defaults/constraints/legado/falha de preflight. Não substitui sessões independentes de R-SQL. |
| R-QUAL | Em `frontend/`: `npm run lint`; `npx --no-install tsc --noEmit --incremental false`; `npm run build` | **Três aprovados,saída0**; build6 páginas. Node24.11.1/Next14.2.5, não Node20 de produção. Confirmado somente `.env.example` no frontend; build com `NEXT_PUBLIC_SUPABASE_URL=https://teste.invalid`, `NEXT_PUBLIC_SUPABASE_ANON_KEY=chave-ficticia-validacao`, `NEXT_PUBLIC_API_URL=http://localhost:3333`, `NEXT_TELEMETRY_DISABLED=1`. |
| R-SIM | Em `bot/`: `python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1` | **Saída0**,130 ofertas/130 produtos,zero falhas,32,551079s,3,993723ofertas/s. Live p50/p95/máx11062,568/24333,207/24827,970ms; histórico30229,401/32292,159/32517,560ms. Heartbeat máx15,601ms,workers4/1,filas live/histórico finais0/0,mídia106 pendentes no instante da medição. Mesmos hashes de dataset da base. Arquivo `dealbot-etapa03-revalidacao-simulacao.json`; cinco esperas lógicas, modelo legado sem dedup real. |
| R-SIM2 | Em `bot/`: `python -B -m simulacao_identidade --seed 42 --pares 10 --cenario todos --db-ms 20 --resolucao-ms 200 --oferta-workers 4 --enriquecimento-workers 1` | **Saída0**,quatro cenários. Frio/lento:20 ofertas confirmadas com rede ainda bloqueada,20→10cards/20aparições/10aliases; convergência após liberação0,948353/4,974487s. Janela de ofertas frio23,708526s/lento0,300736s. Quente20hits,zero rede; fortes10cards/20aparições. Todos terminam sem pendências de oferta/mídia/enriquecimento/ack; máximos4/1/1,rede1. Arquivo `dealbot-etapa03-revalidacao-simulacao-identidade.json`. Modelo de uma espera/RPC, não comparável diretamente às cinco esperas de R-SIM. |
| R-PROBE | `python -B .../dealbot-etapa03-revalidacao-probes.py`; `psql -X -w -h 127.0.0.1 -p 55439 -U postgres -d dealbot_teste_etapa3_revalidacao_20261106 -v ON_ERROR_STOP=1 -P pager=off -f .../dealbot-etapa03-revalidacao-probes.sql`, `PGPASSFILE=NUL` | **Cinco provas aprovadas,saída0**,09/11. `identificar` real produz os payloads; `SET LOCAL ROLE service_role`, RPC real e asserts SQL que levantam exceção sobre erro (não capturam23505 como sucesso). Provisórios IDs68/69 separados; Amazon70/70 e ML72/72 reunidos; duas aparições e replay estável mesmo renomeando; preço300→250; seller diferente separado nas duas lojas. Tudo terminou em ROLLBACK. Complementa o runner, não substitui a regressão permanente. |
| R-REVIEW | `git diff --check`, inspeção de diff/código/testes, revisão de JSON/card/migração/rollback e de scripts/saídas | **Saída0** no diff, apenas avisos LF→CRLF conhecidos. Asserts antigos de watchdog/durabilidade preservados; mudanças em testes antigos só de versão/defaults/worker ativo descritas acima. Fontes não contêm novo código temporário produtivo; exemplos continuam fictícios. |

Os comandos de simulação tiveram stdout salvo por `Out-File -Encoding utf8` nos nomes acima, conferindo `$LASTEXITCODE`; números/hashes e asserts foram inspecionados depois. Python Windows3.14.4 usado apenas nos simuladores/probes puros, não como substituto da suíte POSIX3.12. Não há lint Python/build backend configurados. Não há redesign/novo fluxo para justificar E2E de navegador real como categoria obrigatória: contratos/renderização foram exercitados, com esse limite explícito. Backup/migração/falha de DDL SQLite e rollback transacional estão nos testes; rollback operacional documentado é pausa/preservação de schema e fila, não um downgrade destrutivo ensaiado em produção.

**Desempenho e causalidade:** os32,551079s de R-SIM são piores que17,307319s da baseline informada na implementação e6,420712s da primeira validação; não foram escondidos ou substituídos por uma repetição mais rápida. As duas simulações foram lançadas em paralelo no mesmo host, portanto essa execução não é controle isolado de desempenho. A fase fria também teve cauda alta. D01–D03 e as caudas de COMMIT/9p anteriores permanecem como evidência histórica; não se mediu aqui a causa física desta amostra nem se atribuiu a SQL/CPU uma regressão comprovada. Não há SLA numérico aceito; disponibilidade **antes da rede** está provada por barreiras, contagens, limites e convergência, não por latência pequena. CA-030 não é promessa de ganho de velocidade, e as simulações não provam latência de VPS/Supabase.

#### Matriz final corrente — requisitos e regras

`Atendido` significa verificado no escopo local/formatos e limites declarados. Não transforma fixtures em corpus real nem valida ambiente de produção. A numeração de grupos abaixo é a de R-SQL (37), não a do runner antigo de24 grupos.

| ID | Resultado | Implementação / verificação corrente |
|---|---|---|
| RF-001 | atendido | `identidade.py`,SQLite v6,par numérico/mapa e índices parciais nas RPCs; R-BOT,R-SQL21–29/31–32,R-PROBE confirmam incerteza,aparições distintas e ausência de colisão textual. |
| RF-002 | atendido | `normalizar_url`/`_formato`/`identificar`; R-BOT cobre tokens/query/formatos e conflitos; R-PROBE confirma Amazon/ML positivos e sellers separados. Suporte deliberadamente restrito. |
| RF-003 | atendido | `oferta_registrar`,mapa/lock transacional; R-SQL6/12/31–33 prova resposta perdida,idempotência e sessões independentes, inclusive mesmo username. |
| RF-004 | atendido | `_oferta_resumir`/numeric e observação por evento; R-SQL7–10,R-BOT,R-UI e R-PROBE verificam subidas/quedas/zero/nulo/cupom. |
| RF-005 | atendido | UTC/tupla numérica/instâncias/janela congelada; R-SQL7–14/33/36,R-BOT: recepção não governa preço/validade e replay não migra. |
| RF-006 | atendido | `PipelineIdentidade`,cache/fila/checkpoints SQLite; R-BOT e R-SIM2 provam oferta antes de resolução,cache/restart,retries,limites e encerramento. Ressalva DNS abaixo. |
| RF-007 | atendido | `resolvedor.py`; R-BOT verifica allowlist/DNS/IP efetivo/TLS/redirect/Range/headers/bytes/timeout/proxy com rede falsa, destino proibido não conectado. |
| RF-008 | atendido | `oferta_enriquecer`,aliases/foto e `MidiaCoordenada`; R-SQL15–17/34–35,R-BOT,R-API: fusão atômica,menor ID,foto adotada/compensação e exclusão terminal. |
| RF-009 | atendido | Models/services canônicos e whitelist dupla; R-API,R-UI,R-QUAL e R-SQL buscam/removem aliases sem vazar `canal_id`/identidade/diagnóstico nem disfarçar erro técnico como404. |
| RF-010 | atendido | Pins/ack/gate e reserva durável/limpeza em lotes; R-SQL16/18–20/35/37,R-BOT,R-API preservam trabalho recuperável e resumo vencedor; diagnóstico por contagens/estado/timestamps persistidos. |
| RF-011 | atendido | SQLite v6 e SQL/preflight/escritores corrigidos; R-BOT,R-SQL1–5/20/23–30,R-PROBE: hash/decisão congelados,claim pontual sem backfill e falha atômica/schema ausente sem fallback. |
| RF-012 | atendido | README/CLAUDE/exemplos,logs saneados e este PRD; R-REVIEW,R-SIM/R-SIM2 documentam suporte/incerteza,ordem/rollback,desempenho e limitações,sem etapa4. |
| RN-001 | atendido | Mapa numérico antes de janela; R-SQL6/12/31–32,R-BOT,R-PROBE: mesmo evento mantém efeito/vínculo mesmo com rename/retry tardio. |
| RN-002 | atendido | Preço fora da chave,comparação comercial além do hash; R-BOT,R-SQL9–10,R-PROBE: identidade e condições autorizam união,não título/preço. |
| RN-003 | atendido | Estados de evidência explícitos; R-BOT e R-SQL7/9–10,R-UI: desconhecido não vira zero/sem cupom/seller/variante padrão. |
| RN-004 | atendido | `vincular`/finalizar antes de mídia/resolução; R-BOT e R-SIM2 frio/lento com barreira,20 ofertas já salvas. |
| RN-005 | atendido | Tempo original/tupla e instância; R-SQL7–14/33/36,R-BOT não renovam por recepção/retry nem movem evento antigo. |
| RN-006 | atendido | Transferência explícita e aliases/terminalização; R-SQL15–17/34–35,R-BOT preservam origens,foto referenciada e exclusão. |
| RN-007 | atendido | Pin sem TTL e retenção após ack; R-SQL18–20/37,R-BOT,R-API: purga só de elegíveis,sem promessa de dedup eterna após purga total. |
| RN-008 | atendido | Algoritmo legado intacto/preflight/checkpoints; R-BOT migrações e R-SQL20/23–29 preservam conteúdo/hash/IDs,sem refiltro/backfill. |
| RNF-001 | atendido | Configuração validada/limites finitos; R-BOT,R-SIM2,R-API verificam workers,pool DNS,bytes/hops/retries/lotes; syscall DNS não interrompível limitada a uma pendente, ressalva abaixo. |
| RNF-002 | atendido |15 funções invoker com grants restritos e tabelas internas RLS; R-SQL5 nega PUBLIC/anon/authenticated e permite service_role sem relaxar policies. |
| RNF-003 | atendido | Stack/MVC/payloads públicos preservados; R-API,R-UI,R-QUAL,R-REVIEW:raw_text limitado e derivado interno não exposto. |
| RNF-004 | atendido | R-BOT356 incluindo coleta/decisão/contexto/checkpoints,sinais/encerramento/justiça e SQLite real; sem desabilitar debug/watchdog/WAL/FULL. |
| RNF-005 | atendido | R-SQL com sessões independentes,repro real e DNS/transporte falsos,R-SIM/R-SIM2 com hashes/custos explícitos; saídas negativas/históricas/limites preservados. |

#### Matriz final corrente — critérios de aceitação

| ID | Resultado | Procedimento / evidência corrente |
|---|---|---|
| CA-001 | atendido | R-PROBE Amazon com `tag` distinta e ML completos reais une cada par; R-SQL10/22/32 e R-BOT verificam duas aparições inclusive username reutilizado. |
| CA-002 | atendido | R-BOT identidade insuficiente/IDs distintos e R-SQL9/21:sem fusão por título/foto/preço/URL opaca,provisórios separados e motivo retido. |
| CA-003 | atendido | R-BOT dimensões comerciais e conflitos; R-SQL10/22,R-PROBE sellers diferentes separados,sem remover evidência conflitante. |
| CA-004 | atendido | R-BOT cupom/omissão/case,elegibilidade/pagamento/restrições e R-SQL10; desconhecido não limpa código nem comprova igualdade. |
| CA-005 | atendido | R-BOT `NormalizacaoEtapa3Tests` e queries não comprovadas:caixa,ordem,repetidos/vazios,assinatura/fragmentos/encoding e seller preservados. |
| CA-006 | atendido | R-BOT `tag` apenas no formato aceito,`linkCode` exato conservado,esquema/host/porta/barra distintos; original navegável preservado. |
| CA-007 | atendido | R-BOT,R-SQL6/12/26/31–32 e R-PROBE:mesmo par com rename/retry mantém vínculo e observação/aparição,sem deslocar instância. |
| CA-008 | atendido | R-SQL31–33 com PIDs34604/34684 e `pg_locks`:criação/mesmo evento/username reutilizado/recência em ordem inversa; leitura independente confirma contagens. |
| CA-009 | atendido | R-SQL7 sequência300→250→300 e R-UI:queda própria só na queda,preço anunciado separado; R-PROBE300→250 confirma caminho com extrator real. |
| CA-010 | atendido | R-SQL7,R-BOT,R-UI:zero/nulo distintos,vencedor desconhecido substitui sem fabricar zero/queda; histórico antigo não apaga preço novo. |
| CA-011 | atendido | R-SQL7–8/11/33/36:histórico,tupla numérica,invalidade/futuro/recepção adiantada sem renovação pelo relógio local. |
| CA-012 | atendido | R-SQL12–14/18 e R-API:instância nova após lacuna,retry vinculado à antiga,janela congelada e elegibilidade/limpeza não só por criado_em. |
| CA-013 | atendido | R-BOT e R-SIM2 frio:lógica ativa oferece20 provisórios antes da rede,converge para10cards/20origens; R-SQL15/17 verifica atomicidade real da fusão separadamente. |
| CA-014 | atendido | R-BOT barreiras/timeout/limites e R-SIM2 lento:ofertas independentes dos workers de resolução,falha preserva card/original. |
| CA-015 | atendido | R-BOT cache/restart/negativo/TTL/versão/ciclo; R-SIM2 quente20hits/zero rede; orçamento/checkpoint persistidos. |
| CA-016 | atendido | R-BOT resolvedor com DNS/transporte falsos:IPs proibidos,host/porta/protocolo e rebinding recusados antes de conectar; socket no IP validado. |
| CA-017 | atendido | R-BOT resolvedor:hops/loops/DNS/tempo/HEAD405/501/Range/compressão/bytes/fechamento/proxy; cabeçalhos somente,sem corpo/HTML/preço. |
| CA-018 | atendido | R-BOT resposta perdida/restart/decisão e R-SQL6/12/26/31–32/R-PROBE:replay não cria outro efeito nem redecide/hash novo. |
| CA-019 | atendido | R-SQL15/17 rollback injetado/menor ID/cadeias e R-BOT checkpoint de reconciliação/resposta perdida,reaplicação sem refazer rede confirmada. |
| CA-020 | atendido | R-SQL15–17/35,R-BOT,R-API preservam observações/aparições/foto adotada e compensação pelo ID antigo sem apagar referência viva. |
| CA-021 | atendido | R-SQL34–35 sessões reais:exclusão/fusão/enriquecimento/foto/limpeza; R-API Storage falso falha/retoma sem perder intenção ou reativar card. |
| CA-022 | atendido | R-API SDK real/HTTP falso,whitelist inclusive canal_id interno inesperado e erro técnico; R-SQL busca/remover canônicos/aliases,sem PostgREST real. |
| CA-023 | atendido | R-UI13 e R-QUAL:tipos/card legado,nulo/zero/foto/canais/cupom,queda/subida e percentual anunciado; ajuste mínimo,sem realtime/redesign. |
| CA-024 | atendido | R-BOT e R-SQL18–20/37:avanço de relógio/lotes conserva resumo,pins,aliases e mapas recuperáveis; purga após ack/retentiva. |
| CA-025 | atendido | R-BOT migra versões0–5→6/reabre6,falha DDL preserva versão/dados/hash/decisão/mídia/fronteiras; restart não reavalia aprovação. |
| CA-026 | atendido | R-SQL1–4/20/23–30 aplica bloco/schema completo duas vezes inclusive dados com usernames repetidos; falha atômica/gate e R-BOT schema ausente conservam trabalho sem fallback. |
| CA-027 | atendido | R-BOT `test_serializacao_e_deadlock_retornam_a_fila_sem_redecidir`,indisponibilidade/retry/backoff e checkpoint; R-SQL transações reais. Não foi injetado deadlock real: lock global único serializa as RPCs. |
| CA-028 | atendido | R-SQL5 nega execução das15 funções/auxiliares nos papéis não autorizados e permite service_role,sem relaxar RLS. |
| CA-029 | atendido | R-BOT356/R-API63/R-UI13/R-QUAL aprovados; baseline/skips/falhas e caudas anteriores preservados,sem remover testes/watchdogs/durabilidade. |
| CA-030 | atendido | R-SIM conserva comando/dataset/cinco esperas e registra latências/filas/limites; R-SIM2 barreiras/estado/convergência. Caudas e concorrência das medições declaradas,sem inferência de ganho/SLA. |
| CA-031 | atendido | README/CLAUDE/exemplos e PRD revisados:formatos/fontes/incerteza,ordem/schema/prontidão/rollback/retentiva/diagnóstico sem segredos,continuidade sem etapa4. |

**Resumo final:56/56 atendidos — RF12/12,RN8/8,RNF5/5,CA31/31.** Não há aceite parcial ou item dispensado. As qualificações acima delimitam a prova local, não convertem categoria não executada em execução real.

#### Achados, limitações e continuidade

- **V-ET3-001: encerrado.** R-SQL21–32 e R-PROBE confirmam os dois erros originais corrigidos,regressão permanente,colisões legadas,replay de migração e concorrência. As matrizes antigas50/56 e os23505 permanecem como histórico verdadeiro do código anterior.
- **Sem novo bloqueante/importante obrigatório.** A variação de latência é observação ambiental/inconclusiva quanto à causa nesta medição,sem requisito de SLA violado e sem alterar proteções para verde. Não é alegada eliminação dos timeouts históricos.
- **DNS:** mantida a limitação já documentada: uma syscall getaddrinfo pendente não é interrompível por asyncio; timeout limita a espera/ciclo, não a saída física do interpretador se o SO travar. Executor dedicado/sem fila crescente/aclose e `TimeoutStopSec=60` delimitam as fronteiras; não foi testado DNS/SO realmente travado nem removida essa ressalva.
- **Ambiente:** SQL/grants/RLS em PostgreSQL17.5 com papéis sintéticos; não Supabase/PostgREST/Storage real. SSRF usa rede falsa; sem lojas/Telegram/credenciais/corpus privado. UI renderizada não browser E2E. Node24/Next14,sem teste no Node20 da produção. Políticas/versão/extensões/dados/latência de produção dependem de preflight futuro autorizado,backup e ordem de atualização; não são impedimentos da entrega exclusivamente local aprovada.
- **Baseline/regressões:** reutilizada explicitamente a baseline anterior documentada nas seções15/16 (257 bot/40API/7UI,Windows com erros/skips,exit externo1 do log Linux e diagnósticos D01–D03),sem fingir recriá-la depois das mudanças. As suítes atuais completas foram executadas nesta revalidação e não tiveram skips/falhas ocultos.
- **Operações locais:** bancos novos com nomes protegidos criados sem DROP. Cluster exclusivo foi iniciado somente em127.0.0.1:55439; na continuidade de09/11 estava parado e foi aberto apenas para R-PROBE. Encerramento final limpo por `pg_ctl -D .../dealbot-etapa03-pg-isolado -m fast -t 90 -w stop`,saída0; bases/logs/SQL de teste preservados. Nenhum serviço do usuário/WSL/Windows reiniciado ou reconfigurado.
- **Fora do escopo e pendências:** nenhuma pendência obrigatória local. Permanecem fora da entrega:publicação,backup/aplicação remota,deploy/rollback produtivo,migração de imagens,scraping/redesign/realtime e etapa4. Nenhum commit/push/PR/merge/deploy/SQL remoto ou credencial real utilizado.
- **Próximo passo:** revisão humana da entrega local e decisão explícita sobre eventual publicação/atualização futura. Não executar outro comando de implementação para esta etapa concluída por padrão. Etapa4 requer novo planejamento/autorização; nenhuma continuação automática.
