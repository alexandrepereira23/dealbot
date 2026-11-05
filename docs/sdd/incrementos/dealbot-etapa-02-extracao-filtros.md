---
id: dealbot-etapa-02-extracao-filtros
titulo: "Dealbot — Etapa 2: extração correta e filtros previsíveis"
status: concluido
modo: rigoroso
risco: alto
versao: 1
aprovacao: usuario
versao_aprovada: 1
aprovado_em: 2026-10-23
criado_em: 2026-10-23
atualizado_em: 2026-11-05
implementacao_iniciada_em: 2026-10-23
base_branch: main
base_commit: 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a
---

# PRD de Entrega — Dealbot: extração correta e filtros previsíveis

## 1. Resumo

Entregar somente a etapa 2: extrair ofertas do Telegram com título, preços, link e cupom fundamentados no conteúdo; avaliar regras previsíveis sobre a descrição completa; permitir configurar interesse, bloqueio global e modos de palavras pela API e tela existentes. Explicar decisões localmente e disponibilizar prévia offline que reutiliza a lógica Python de produção.

Preservar a coleta durável da etapa 1, oferta antes da imagem, decisões congeladas e deduplicação atual. Extração e filtragem são locais, sem IA ou consultas externas adicionais por mensagem. A implementação futura deve verificar todas as camadas e parar antes das etapas seguintes.

Entrada: `PROMPT_DEALBOT_ETAPA_02.md`, lido integralmente. Este PRD autossuficiente foi criado inicialmente somente como planejamento; a invocação posterior de `sdd-implementar` aprovou a versão1 e autorizou a implementação local. **Etapa2 concluída na validação de05/11:**241/241 testes Python em90,349s,40/40 API,7/7 UI,lint/tipos/build eSQL local aprovados.21/21 requisitos e26/26 critérios atendidos no escopo local/offline. Nenhum teste/prazo/debug/garantia SQLite foi relaxado. A distribuição Ubuntu já estava parada e foi iniciada explicitamente; nenhum encerramento forçado ou mudança de configuração foi necessário. Histórico negativo e causa não comprovada de cada timeout permanecem como observação de ambiente, não como prova de correção definitiva. Aprovação/requisitos v1 preservados; sem commit/deploy/migração remota ou início automático da etapa3.

## 2. Classificação

- **Modo:** `rigoroso`. Altera semântica de decisões, contratos de filtros em três serviços e persistência SQLite/Supabase, com compatibilidade histórica obrigatória.
- **Risco:** `alto`. Uma interpretação incorreta pode aceitar ofertas vetadas, perder ofertas, repetir efeitos remotos após reinício ou expor opções que o bot não entende.
- **Proteções adicionais:** migração aditiva testada, preservação de decisões/hash históricos, validação de contratos entre camadas, testes de falhas/reinício e plano de reversão sem apagar dados. Evidências e decisões ficam neste PRD, sem TechSpec/ADR/relatórios separados obrigatórios.

## 3. Contexto e comportamento atual

Fotografia da base no planejamento; implementação e verificações posteriores estão na seção 15. Constatações antigas abaixo não descrevem o código modificado como se ainda estivesse na base.

### Comportamento confirmado e evidências relevantes

| Evidência no checkout base | Comportamento confirmado e consequência |
|---|---|
| `git rev-parse --show-toplevel`, `git status --short --branch`, `git rev-parse HEAD`, `git worktree list --porcelain` | Raiz `C:/Users/Alexandre_HP/Documents/DellBot/dealbot`; único worktree listado; `main` no commit do cabeçalho, acompanhando `origin/main`. Três prompts não rastreados preexistentes; nenhum arquivo rastreado modificado. |
| `CLAUDE.md`, `README.md`, `bot/requirements.txt` | Entrada ativa `cd bot` / `python -m src.main`; Python 3.12 recomendado; Telethon 1.36.0, Supabase 2.9.1, dotenv 1.0.1 fixados. Legado `bot/bot.py` usa Gemini e não deve ser reativado. Identificadores/comentários em português; backend segue routes → controllers → services → models. |
| `bot/src/extractor.py:4-17,75-107` | Usa menor/maior valor monetário como atual/anterior; título é primeira linha, cortado em separador e em 100 caracteres; exige texto com 20 caracteres e preço truthy ou link. Frete/desconto e zero podem ser interpretados incorretamente. |
| `bot/src/extractor.py:20-72` | Cupom pode ser qualquer código em backticks e é convertido para maiúsculas; primeiro HTTP(S) é escolhido; categorias usam substring sobre todo o texto. |
| `bot/src/filters.py` | Avalia somente título, por substring normalizada; regras alternativas com bloqueio local; palavras sempre alternativas; preço ausente vira zero e teto zero não é aplicado. |
| `bot/src/modelos.py:12-23`, `bot/src/telegram.py:54-63,99-112` | Envelope guarda texto, identidade, horários, origem e presença de foto, sem candidatos estruturados de links/entidades/botões. Live privilegia `.text`; histórico raw reconstrói markup com `parse_mode.unparse`. Essa diferença precisa ser tratada sem usar offsets do texto formatado. |
| `bot/src/estado.py:78-145,309-322` | SQLite suporta versões 0 a 4, evolui aditivamente e grava decisão como JSON de produto com hash separado; inserções usam chave canal/mensagem e não sobrescrevem eventos existentes. |
| `bot/src/pipeline.py:149-183`, `bot/src/repository.py:162-230` | Decisão existente evita nova extração/filtro; descarte é `sem_produto`/`filtro`. Pipeline expande `produto` no registro remoto e repositório também expande o registro; campos internos novos vazariam sem projeção explícita. |
| `bot/src/cache.py`, `bot/src/repository.py:77-80` | `None` é configuração desconhecida; `[]` válido aceita tudo. Refresh preserva último snapshot válido, mas validação atual é limitada e preço passa por float. Consulta apenas regras ativas com `select("*")`. |
| `bot/src/dedup.py`, `bot/src/repository.py:17,194-198` | Hash existente normaliza link/título e preço; janela de 48h. A normalização do hash hoje reduz a caixa da URL inteira; isso não autoriza reduzir a caixa do link público nem corrigir identidade nesta etapa. |
| `backend/src/services/filtro.service.js`, `backend/src/models/filtro.model.js` | Zod valida nome/listas/preço positivo, sem enums de categoria/tipo/modo ou limites de termos. PUT usa schema parcial; erros de model na atualização são convertidos indiscriminadamente em não encontrado. Defaults/validação da atualização precisam de testes, não de suposição. |
| `backend/src/controllers/filtro.controller.js`, `backend/src/routes/filtro.routes.js`, `backend/src/routes/index.js` | CRUD em GET/POST/PUT/DELETE `/api/filtros`; autenticação central existente. Não é necessário criar PATCH nem alterar autenticação. |
| `frontend/app/filtros/page.tsx:8-22,59-91,143-158` | Cadastro/edição não têm tipo/modo, ajuda fala em título, e salvar envia `ativo: true`, inclusive para regra pausada. Lista não distingue bloqueio local/global. |
| `frontend/lib/types.ts`, `frontend/components/ProdutoCard.tsx` | Preços públicos são `number | null`; card exibe zero com formatação, mas desconto usa teste truthy. Categorias: `eletronicos`, `casa`, `moda`, `alimentos`, `beleza`, `games`, `outros`; `todos` é apenas opção de navegação. |
| `supabase/schema.sql:7-61` e árvore `supabase/` | Preços são `numeric(10,2)`. Filtros não possuem tipo/modo. Fluxo existente é script SQL com blocos aditivos/idempotentes; não há diretório/runner de migrações separado. |
| `backend/package.json`, `frontend/package.json`, `frontend/.eslintrc.json`, `frontend/tsconfig.json` | Backend não tem script/suíte de teste, lint ou build. Frontend possui `npm run lint`, `npm run build`, ESLint configurado e TypeScript strict; não possui script de testes. |
| `bot/tests/`, contagem AST somente leitura | 118 métodos `test_*` em 11 arquivos. Não equivale a executar/aprovar os testes. Há cobertura de SQLite, SDKs com transporte falso, checkpoints, recuperação, sinais e retenção. |
| `bot/tests/test_sdk.py:182-202` | Regressão atual exige preservação de formatação de código no histórico e aceita cupom isolado. A nova exigência de evidência de cupom exige atualizar a expectativa específica, preservando a verificação de equivalência/formatação e acrescentando caso negativo explícito. |
| `bot/simulacao.py`, `README.md:219-266` | Simulação usa SQLite real, cinco esperas lógicas de banco, produtores falsos e medição até confirmação da oferta antes de aparição/foto; histórico do benchmark não percorre RPC Telegram. Não comprova desempenho real nem semântica de extração em corpus variado. |

PRD relacionado: `docs/sdd/incrementos/dealbot-etapa-01-coleta-confiavel.md`, estado `concluido`, lido integralmente. Suas restrições de não alterar extração/filtros eram específicas da etapa 1; esta entrega autoriza evoluir essas duas regras, preservando suas proteções de durabilidade e idempotência. O usuário informa validação posterior da referência com 118 testes sem skips; esse resultado não foi reexecutado aqui.

### Pontos não confirmados

- Não foram acessados Telegram, Supabase, VPS, sessão ou `.env` privados. Schema remoto, dados legados reais, instalação e desempenho de produção permanecem desconhecidos.
- Nas fontes/testes/documentação relacionados inspecionados, não foi identificada coleção de mensagens reais com fonte e volume suficientes para justificar adaptador de um canal específico. Fixtures existentes e novos exemplos não devem ser apresentados como mensagens reais.
- Dependências instaladas, disponibilidade atual do ambiente WSL/Python 3.12 usado anteriormente e toolchain Node não foram revalidadas. Executabilidade não se deduz de manifests ou de evidência histórica.
- Não foi encontrado `AGENTS.md` no workspace. `.sdd-lite` não existe na raiz; runtime escolhido: `C:/Users/Alexandre_HP/.config/opencode/.sdd-lite`, com leitura integral de `prompts/_comum.md`, `prompts/planejar.md` e `templates/prd-entrega.md`.

## 4. Problema e objetivo

**Problema:** heurísticas descontextualizadas transformam chamadas genéricas em títulos, frete/parcela em preço e links de divulgação em oferta. Regras com substring, preço ausente como zero e escopo de bloqueio implícito produzem decisões difíceis de prever. A interface não permite os novos comportamentos e a atualização pode reativar regra pausada.

**Objetivo observável:** os exemplos e critérios deste PRD produzem dados e decisões coerentes em extração, CLI, live, histórico e retomada; todas as opções ficam disponíveis por CRUD/UI; valores desconhecidos/ambíguos não são inventados; cada decisão nova tem diagnóstico enxuto. Medir custo local sem acrescentar rede/esperas no caminho crítico ou prometer SLA da VPS.

## 5. Escopo

### Incluído

- Extrator genérico contextual: título descritivo, conteúdo de avaliação, evidência de oferta, preços semânticos, links HTTP(S), cupons e categorias.
- Captura local dos metadados disponíveis na própria mensagem e persistência mínima compatível com envelopes/SQLite antigos.
- Interesse alternativo entre regras; modo qualquer/todas dentro de uma regra; bloqueios locais e globais explicitamente diferentes.
- Contratos, validação, CRUD, tipos e tela de filtros existentes, inclusive manutenção de `ativo` em edição e atualização parcial.
- SQL aditivo local para tipo/modo/defaults/constraints; evolução local SQLite se necessária; documentação de aplicação futura e rollback.
- Diagnósticos, projeção remota por lista permitida, prévia CLI offline, testes de todas as camadas e medições antes/depois.

### Fora do escopo

- Etapa 3: resolver redirects, identidade canônica de produto, similaridade, alteração do algoritmo/janela de dedup ou recálculo de hashes históricos.
- Nova arquitetura para várias ofertas por mensagem, álbuns/edições, ou reprocessamento em massa de eventos finalizados.
- Migrar imagens, mudar Storage, criar comparador/histórico de preços/favoritos/alertas.
- Alterar autenticação/RLS, redesenhar dashboard, atualizar a stack inteira ou adicionar serviço Python separado/plataforma de sinônimos.
- IA/Gemini e reativação de `bot/bot.py`; extração via lojas ou serviços externos por evento.
- Commit, push, PR, merge, deploy, SQL remoto, acesso à conta Telegram ou testes com credenciais reais. Migrações só serão executadas em bancos locais descartáveis de teste na implementação autorizada.

## 6. Requisitos

### Requisitos funcionais

#### RF-001 — Título, descrição e evidência de oferta

- Separar título de apresentação e conteúdo descritivo usado por filtros/categorias. Procurar linha de produto ignorando chamadas genéricas, decoração, URLs isoladas e linhas exclusivamente monetárias/de cupom.
- Preservar marca, modelo, capacidade, variante e partes relevantes após hífens/separadores; não cortar indiscriminadamente na primeira ocorrência ou perder a informação exigida pelos exemplos.
- Normalizar caixa, acentos, espaços (inclusive não separáveis) e formatação para matching; excluir URLs, rodapés identificados de divulgação e códigos de cupom da descrição de produto. Não excluir automaticamente toda linha final sem evidência de rodapé.
- Manter texto original uma única vez na inbox; derivados devem ser pequenos ou reconstruíveis e não duplicar integralmente a mensagem em cada diagnóstico/decisão. Preservar `raw_text` remoto limitado a 2000 caracteres.
- Aceitar mensagem curta quando houver descrição e evidência de oferta; comprimento mínimo de 20 deixa de ser autorização/rejeição. Divulgação genérica com link de grupo não é produto. Preço pode ser desconhecido se houver descrição e evidência suficiente de oferta.

#### RF-002 — Preços com contexto e precisão

- Distinguir preço atual, anterior, parcela, frete, desconto e compra mínima. Precedência: valor explicitamente final/à vista sobre preço genérico inequívoco associado ao produto; preço anterior somente com marcador próprio. Conflitos entre preços finais independentes não se resolvem por min/max.
- Reconhecer BRL com vírgula decimal, agrupamento brasileiro válido, espaços não separáveis e inteiros em contexto monetário. Não interpretar modelos/capacidades/percentuais como dinheiro.
- Política inicial de separadores: `R$ 1.234,56` → 1234,56; `R$ 299,90` → 299,90; `R$ 299` → 299,00; `R$ 1.234` → 1234,00 por agrupamento brasileiro válido. Formas conflitantes como `R$ 1,234`, `R$ 12.34` ou agrupamento inválido ficam desconhecidas com diagnóstico de formato ambíguo, sem tentativa de adivinhar outro locale.
- Usar centavos inteiros ou Decimal internamente. Serializar somente números JSON finitos/null nos campos públicos e JSON compatível nas decisões; `numeric(10,2)` suporta até 99.999.999,99. Rejeitar dados monetários fora da capacidade sem enviar valor inválido; não arredondar silenciosamente uma entrada ambígua para criar precisão.
- Zero explícito/gratuidade identificada é conhecido e distinto de `None`. Anterior menor/igual ao atual não gera desconto positivo: registrar inconsistência e não apresentar promoção percentual fictícia.
- Nesta versão, **não derivar total de parcelamento**: sem preço total/à vista explícito, preço atual permanece nulo. Isso evita cálculo especulativo; derivação futura, se proposta nesta entrega, exigirá condições inequívocas, ausência de juros, indicação de cálculo e novos testes antes de alterar essa decisão do PRD.
- Detectar evidências claras de vários produtos/preços independentes e terminar como ambiguidade própria, sem escolher o menor nem emitir múltiplos cards. Não prometer detector completo para todo formato de post.

#### RF-003 — Contexto Telegram e links reproduzíveis

- Capturar URLs visíveis em texto/legenda, entidades URL/TextUrl relevantes e URLs de botões presentes em `reply_markup`, sem RPC adicional para completar metadados. Não executar callbacks nem seguir redirects.
- Converter no limite Telethon os dados do SDK em estrutura JSON mínima: candidatos com origem/rótulo/contexto necessário e, quando útil, spans de código/link. Não persistir objetos SDK, clientes, callbacks ou markup bruto desnecessário.
- Interpretar offsets sobre texto bruto segundo UTF-16 do Telegram, nunca sobre `.text` já formatado nem por fatiamento Python ingênuo. Preferir helpers públicos do SDK fixado, com teste executável para live e resposta raw histórica, inclusive emoji astral antes da entidade.
- Aplicar prioridade determinística contextual: link de produto/compra associado à descrição ou botão de oferta acima de link de divulgação; evitar grupo/canal/rede social quando existir candidato comercial claro; desempate estável pela ordem da mensagem. Link isolado de divulgação não serve como evidência de produto. Link curto HTTP(S) plausível pode vencer divulgação sem ser aberto.
- Aceitar somente HTTP/HTTPS com host válido para link público; não converter scheme arbitrário em URL de oferta. Remover só delimitadores externos comprovados; preservar parênteses legítimos, query, fragmento, parâmetros, caminho e caixa. Normalizar host para comparação não modifica todo o link público.
- Serializar contexto no SQLite junto da mensagem antes da confirmação de aceitação; live, histórico e retomada da mesma mensagem nova devem produzir resultados equivalentes. Envelopes/pendências antigos sem campos novos têm contexto vazio e continuam processáveis, sem busca remota de enriquecimento.

#### RF-004 — Cupons, categorias e extensão por canal

- Reconhecer `cupom`, `use o cupom` e formatação de código com evidência contextual de cupom. Backticks isolados, marcador sem código e palavra genérica `DESCONTO` não fabricam cupom. Código só formatado, sem evidência adicional, permanece nulo com diagnóstico quando pertinente.
- Preservar a grafia do código capturado, sem uppercase automático; ambiguidades como múltiplos códigos sem precedência clara ficam nulas e explicadas, sem impedir uma oferta válida independente do cupom.
- Classificar por palavras completas/frases e objeto principal no conteúdo descritivo. `cadeira gamer` → casa; `headset gamer` → eletronicos; `jogo de PS5` → games. `PC`, `RAM`, `HD`, `TV` e `game` não casam dentro de palavras não equivalentes. Incerteza → outros.
- Manter exatamente as sete categorias existentes em bot/API/frontend; `todos` não é categoria persistível.
- Entregar um ponto de extensão pequeno e documentado por ID estável/username normalizado; fallback genérico. Sem corpus real suficiente com fonte, não criar adaptador específico nem inventar formato dos canais do usuário. Fixtures devem indicar natureza sintética.

#### RF-005 — Avaliação detalhada de regras de interesse

- Usar conteúdo descritivo, não apenas título. Dentro de cada regra combinar categoria, teto de preço e condição de palavras; entre interesses ativos, usar OR.
- `modo_palavras=qualquer` exige ao menos uma entrada; `todas` exige todas as entradas. Entrada pode ser uma frase contígua normalizada, não palavras dispersas. Lista vazia não impõe condição.
- Matching normaliza caixa/acentos/espaços e respeita limites de tokens; não usar fuzzy amplo. Sinônimos são opcionais e somente por tabela pequena explícita com testes.
- `preco_max` é aplicado quando não nulo, inclusive zero. Preço desconhecido falha somente nas regras com teto (`preco_desconhecido`); outra regra sem teto pode aceitar. Comparação exata em centavos/Decimal, com igualdade aceita.
- Produzir decisão interna com regra responsável e motivos de cada regra avaliada. Se nenhuma aceitar, preservar rejeições por regra, sem atribuir ao produto um único motivo enganoso. Não confundir falha de extração/configuração com rejeição legítima.

#### RF-006 — Bloqueios e configuração válida

- Introduzir `tipo_regra: interesse | bloqueio_global`, default legado `interesse`; `modo_palavras: qualquer | todas`, default legado `qualquer`. Nomes são compartilhados por SQL/API/Python/TypeScript.
- Em interesse, `palavras_bloqueio` continuam veto **local por qualquer termo**, independentemente do modo de inclusão; outra regra de interesse pode aceitar. A UI deve explicar essa diferença.
- Em bloqueio global, usar exclusivamente `palavras_bloqueio` não vazia; `modo_palavras` define qualquer/todas sobre esses termos. Avaliar globais antes de interesses; correspondência veta sem que regra permissiva possa autorizar.
- Bloqueio global exige `palavras_chave=[]`, `categoria=null` e `preco_max=null`; combinações incompatíveis são rejeitadas pela API, inclusive após mesclar atualização parcial. UI deve desabilitar/limpar inclusões explicitamente ao trocar tipo, sem esconder dados enviados.
- Somente regras ativas participam. Sem interesses ativos, aceitar ofertas válidas não vetadas globalmente. Sem regras ativas, aceitar ofertas válidas. Globais nunca funcionam como autorização.
- Validar snapshot completo antes da substituição, incluindo enums, categorias, valores finitos e consistência por tipo. Resposta inválida/schema indisponível não vira `[]`: sem snapshot válido aguardar; depois preservar último válido e registrar idade/erro. Mensagem ruim não invalida configuração nem é reprocessada infinitamente.

#### RF-007 — CRUD, validação e interface existentes

- Expor tipo/modo no cadastro, edição, listagem e tipos. Manter rotas/métodos/status de sucesso existentes, sem redesenho. Ajuda deve explicar descrição completa, OR entre regras, AND dentro da regra, preço desconhecido e escopos de bloqueio.
- Edição preserva `ativo=false`; preferir não enviar `ativo` na edição de conteúdo. Toggle de ativo não altera outros campos. Criação mantém default ativo. Mostrar preço máximo zero e tipo/modo corretamente na listagem.
- API valida enums/categorias, nome com trim (1–100 caracteres), até 50 entradas por lista e 1–100 caracteres por termo/frase após trim. Rejeitar termos vazios e duplicatas pela mesma normalização de matching, sem quebrar uma frase em termos independentes. UI pode limpar separadores vazios antes do envio, sem transformar entrada inválida do cliente API em aceitação.
- `preco_max` aceita null ou número finito não negativo até 99.999.999,99, representável em centavos sem arredondamento silencioso. Zero é teto legítimo para gratuidade; negativos, strings monetárias arbitrárias, NaN, infinito e precisão excessiva são inválidos. Transporte JSON/JavaScript deve ser testado nos limites, sem comparação binária ingênua.
- PUT continua aceitando atualização parcial: validar o resultado combinado com o registro atual quando houver invariantes entre campos; persistir apenas campos informados e mudanças explicitamente solicitadas, sem defaults de criação apagarem listas/tetos/estado. Preservar distinção entre campo omitido, null e lista vazia; atualização vazia/inválida retorna erro claro.
- Distinguir filtro realmente inexistente de falha de banco/schema. Remover conversão indiscriminada de erro de atualização em 404; propagar indisponibilidade pelo padrão HTTP existente, sem falso sucesso ou detalhes sensíveis.
- Adicionar testes de serviço/model/rotas com dependências falsas, sem Supabase real. Preservar autenticação existente; não inicializar conexão/servidor de produção para executar testes.

#### RF-008 — Persistência, decisões e payload remoto seguro

- Evoluir SQLite aditivamente a partir da versão 4 e versões anteriores suportadas caso novos campos sejam necessários. Contexto/diagnóstico têm defaults seguros; preservar texto, IDs, estados, decisões, hashes, mídia, aliases, fronteiras e retries. Versão nova só é confirmada após migração bem-sucedida; falha não recria banco vazio.
- Decisão persistida continua soberana: não reextrair, reavaliar, enriquecer por rede nem recalcular hash de decisão histórica para mudar sua identidade. Reutilizar hash congelado quando existente; fallback apenas para registro legado sem hash, com o mesmo algoritmo e dados congelados, nunca reextração do texto.
- Gravar aprovação nova e diagnóstico antes do primeiro efeito remoto. Rejeição/ambiguidade grava diagnóstico e terminaliza sem rede/retry infinito. Manter reconciliação pelo evento após timeout/commit remoto ambíguo e retomar aparição/mídia no mesmo card.
- Manter campos internos separados do produto público e projetar explicitamente os campos persistíveis no limite remoto: `titulo`, `preco`, `preco_original`, `cupom`, `link`, `categoria`, `canal_origem`, `telegram_msg_id`, `raw_text`, `data_oferta`, `foto_url` e `dedup_hash` calculado pelo contrato existente. Não enviar descrição normalizada, motivos, candidatos, fontes de preço ou versão de extrator como colunas de produtos.
- JSON de decisões antigas, que contém somente produto, deve continuar legível. Se novo envelope de decisão for adotado, versionar e suportar ambos sem regravar decisões antigas por rotina. Diagnóstico pode ficar em campo local separado para minimizar risco.

#### RF-009 — Diagnóstico local e CLI offline

- Resultados internos de extração/avaliação incluem status, códigos de motivo, regra responsável/ID quando disponível, motivos por regra e fonte do preço/link quando útil. Conjunto mínimo: `aceita_por_regra`, `bloqueio_global`, `bloqueio_da_regra`, `palavra_ausente`, `categoria_divergente`, `preco_acima_do_limite`, `preco_desconhecido`, `preco_ambiguo`, `sem_evidencia_de_oferta`. Acrescentar códigos inequívocos para várias ofertas, formato/cupom ambíguos, configuração inválida e aceite sem interesses.
- Guardar diagnóstico pequeno no estado local e emitir logs correlacionáveis por canal/mensagem/regra. Não logar texto integral, termos privados, códigos, URLs completas, sessão/tokens ou objetos SDK. IDs sintéticos/índice de regra servem para filtros offline sem ID persistido.
- Disponibilizar CLI Python proposta `python -m previa --mensagem mensagem.txt --filtros filtros.json` a partir de `bot/`, com mensagem UTF-8 e filtros JSON; aceitar contexto opcional em arquivo JSON para entidades/botões/canal normalizados. Documentar formato e exemplos sintéticos.
- CLI retorna JSON com dados extraídos, decisão e motivos usando os mesmos módulos de produção; funciona sem `.env`, tokens, Telethon conectado ou Supabase. Código de saída proposto: 0 para avaliação válida (aceita ou rejeitada), 2 para entrada/configuração inválida e 1 para falha técnica. Não duplicar lógica em JS nem criar serviço persistente.

#### RF-010 — Documentação e evidências da entrega

- Documentar semântica, exemplos, defaults legados, atualização parcial, CLI, política monetária, precedência de links, limitação de uma oferta por mensagem, ausência de corpus real/adaptadores e migrações pendentes.
- Entrega futura apresenta: resumo/arquivos principais, antes/depois com origem sintética/real explícita, testes/build/lint/tipos e impedimentos reais, métricas reproduzíveis, migrações/ordem/rollback, decisões e limites para etapa 3 e continuidade curta. Atualizar este PRD com comandos/resultados reais.

### Regras de negócio e preservação

- **RN-001:** oferta válida exige evidência descritiva/promocional; link de grupo, percentual, código ou montante de desconto isolados não provam preço/produto. Desconhecido permanece nulo; ambiguidade não é resolvida pelo menor número.
- **RN-002:** globais vetam antes; interesses são alternativas; categoria/preço/palavras se combinam dentro de cada interesse. Bloqueio local não vira global. Ausência de interesses é permissiva somente com configuração comprovadamente válida e oferta válida.
- **RN-003:** mudanças de extração/filtros afetam somente decisões ainda não congeladas. Não reabrir finalizados, recalcular hashes históricos ou reavaliar retry com decisão. Novas extrações podem gerar hashes diferentes pelos dados corrigidos, sem modificar o algoritmo de dedup.
- **RN-004:** preservar entrada ativa, inbox durável, migrações existentes, ID estável canal/mensagem, paginação e gerações, atualização de canais/cache, workers limitados, prioridade live, Supabase async, oferta antes da foto, reconciliação/idempotência, sinais e retenção em lotes.
- **RN-005:** manter algoritmo/normalização de `bot/src/dedup.py`, janela de 48h e aparições. Preservar caixa do link público não implica corrigir a normalização interna de identidade, cuja limitação fica para etapa 3.
- **RN-006:** dados remotos/contas reais nunca são laboratório desta entrega; nenhuma migração ou publicação remota é executada. Preservar os três prompts não rastreados e todo trabalho posterior que existir na implementação.

### Requisitos não funcionais

- **RNF-001 — Caminho crítico local:** nenhuma chamada IA, HTTP de loja, resolução de redirect ou RPC Telegram adicional por evento para extração/metadados; nenhum `sleep` artificial ou serviço extra. I/O remoto existente de persistência/mídia continua separado e assíncrono.
- **RNF-002 — Custo limitado:** regex e processamento devem ser limitados ao tamanho da entrada, sem busca de complexidade explosiva ou repetição desnecessária de normalização/compilação de regras por mensagem. Preparar o snapshot no refresh e reutilizar. Medir corpus longo/adversarial e variado, respeitando os limites de listas/termos.
- **RNF-003 — Compatibilidade:** números públicos continuam number/null; SQLite antigo/decisões JSON antigas e IDs de filtros legados são preservados; categorias sincronizadas. Sem upgrade geral de pins, mudança de auth ou alteração oportunista da stack.
- **RNF-004 — Privacidade:** reutilizar proteção do diretório local, logs saneados e retenção da etapa 1; diagnóstico não replica mensagens grandes nem vai ao Supabase. Fixtures públicas somente sintéticas ou fonte fornecida e saneada.
- **RNF-005 — Evidência honesta:** registrar comandos, ambiente, códigos de saída, skips e limitações. Não prometer latência de VPS/Telegram/frontend a partir de mocks. Preservar assertions de regressão; mudança esperada de semântica exige explicação e cobertura substituta equivalente, não exclusão de falhas para obter verde.

## 7. Experiência e comportamento esperado

1. Usuário cria interesse, escolhe palavras/frases e modo qualquer/todas, categoria/teto opcionais; lista explica que uma das regras de interesse basta.
2. Usuário cria bloqueio global com termos e modo de veto. Campos de inclusão deixam de ser aplicáveis e a tela explica que nenhuma regra de interesse o sobrepõe.
3. Editar regra pausada muda conteúdo, não ativação; pausar/ativar mantém os demais campos.
4. Mensagem live/histórica é persistida com contexto local; worker usa snapshot válido e extrator genérico/adaptador autorizado. Veto ou falta de evidência termina com motivos; aprovação congela produto/diagnóstico/hash antes da rede.
5. Oferta aparece com preço conhecido ou ausente, link/cupom fiel e foto possivelmente nula; mídia continua posterior. Retry com decisão existente não muda o resultado, mesmo após alteração de regras ou versão de extrator.

Estados relevantes: tela carregando, lista vazia com ajuda correta, erro de validação junto ao formulário, falha de schema/serviço visível sem limpar formulário nem fingir salvamento, regras pausadas distinguíveis. Configuração inicial desconhecida aguarda; lista válida vazia aceita ofertas válidas; erro posterior mantém snapshot válido. Mensagem não promocional/ambígua termina localmente, sem afetar outras mensagens/configuração.

## 8. Impacto técnico e contratos

| Área | Mudança planejada |
|---|---|
| Bot/extrator | Resultado interno contextual e normalização compartilhada, mantendo consumidor Python existente; adaptadores pequenos com fallback genérico. |
| Telegram/SQLite | Contexto serializável comum live/raw, UTF-16 validado, persistência aditiva e diagnóstico enxuto. Sem refetch para enriquecer. |
| Cache/filtros | Snapshot validado/preparado; tipos/modos/defaults, bloqueios em dois escopos e comparações monetárias exatas. |
| Pipeline/repositório | Congelamento compatível, hash persistido respeitado, projeção explícita de payload; sem mudar dedup/reconciliação/mídia. |
| Backend | Zod nos services; models concentram acesso a dados/consulta de filtro atual para invariantes de update. Rotas/controladores mantêm contrato e tratamento de erros. |
| Frontend | Tipos, formulário, ajuda/listagem e edição de pausados em `app/filtros`; eventual ajuste localizado do badge/preço no card para zero/inconsistência, sem redesign. |
| Supabase | Tipo/modo e constraints em bloco aditivo/idempotente de `supabase/schema.sql`, preservando fluxo atual. Sem runner novo de migrações por conveniência. |
| Testes/documentação | Suíte Python ampliada, testes offline API/UI, runner de prévia e medição local; README e registros neste PRD. |

### Migração, ordem de atualização e reversão

1. **Preparação futura autorizada:** conferir schema/dados existentes e backup consistente do SQLite; não copiar só arquivo principal em WAL ativo. Neste incremento isso é simulado em bancos temporários, sem tocar dados remotos reais. Detectar dados legados incompatíveis com constraints sem apagar/reinterpretar regras silenciosamente.
2. **Schema Supabase primeiro:** preparar bloco aditivo identificável da etapa 2 com `tipo_regra` e `modo_palavras` não nulos/defaults `interesse`/`qualquer`, constraints de enums e consistência de bloqueio global. Preservar IDs, listas, teto, ativo e timestamps legados. `CREATE TABLE IF NOT EXISTS` sozinho não atualiza banco existente; alterações devem ser explícitas e repetíveis. Constraints que esbarrem em dados legados inválidos exigem diagnóstico/preflight e correção autorizada, não limpeza automática.
3. **Bot e backend novos antes da UI habilitar globais:** parar versão antiga do coletor durante a transição; aplicar SQLite aditivo no startup local e verificar prontidão. Não permitir que bot antigo interprete bloqueio global como interesse permissivo. Atualização remota destes componentes está fora desta execução; apenas instruções/testes locais serão entregues.
4. **Frontend depois:** expor criação dos novos tipos quando schema/backend/bot compatíveis estiverem atualizados. Verificar CRUD/defaults e edição pausada em ambiente local falso.
5. **Schema não pronto:** consultas de filtros do serviço novo devem exigir as novas colunas na fronteira do repositório ou verificar prontidão equivalente, não deduzir capacidade de `select("*")` sem campos. Ausência de coluna/schema é erro visível, sem fallback de gravação que descarte tipo/modo. Cache inicial fica desconhecido; cache já válido preserva snapshot e reporta problema. Decisões já congeladas podem continuar a reconciliação existente, sem nova avaliação. Defaults legados aplicam-se a registros/envelopes suportados, não ocultam falta de migração do serviço real.
6. **Rollback:** parar coletor, preservar banco/backup, não apagar colunas/dados nem reabrir finalizados. Schema Supabase aditivo pode permanecer; retornar todo o stack antigo só é seguro sem regras globais/novos modos que ele ignore. Com globais ou `todas`, interromper processamento e decidir plano compatível; não desativar vetos automaticamente. SQLite novo pode ser recusado pelo código antigo por versão; usar versão de código compatível ou restauração consistente aprovada, registrando que restaurar backup perde eventos posteriores. Não prometer downgrade transparente nem iniciar dois coletores.

Nenhum SQL será aplicado remotamente. Teste SQL executável deve usar Postgres local descartável, se disponível; isoladamente verificar texto do script não comprova execução. Na ausência de ambiente local, registrar impedimento e não declarar migração validada só com mocks.

## 9. Estratégia de implementação

### Sequência proposta para após aprovação

1. Reconfirmar branch/worktree/base/instruções e alterações preexistentes. Executar baseline: 118 testes e simulação solicitada, sem modificar produção. Registrar ambiente/versões/skips; usar Python 3.12 + SDKs e Linux local/WSL para sinais POSIX. Fazer exemplos antes/depois pela lógica antiga em memória/fixtures, sem copiar serviço inteiro nem deixar lógica duplicada em produção.
2. Fixar contratos de resultado interno, normalização, dinheiro e regra; adicionar fixtures sintéticas e testes parametrizados. Implementar extrator genérico e ponto de extensão sem formatos de canal inventados.
3. Capturar contexto Telegram comum, validar UTF-16/SDK raw e migrar persistência aditivamente; provar restart e leitura de pendências/decisões antigas antes de integrar decisões novas.
4. Implementar avaliação detalhada/cache preparado e integrar pipeline com diagnóstico separado, hash congelado e lista remota explícita; exercitar falhas nas fronteiras de commit.
5. Preparar SQL aditivo e contratos/validação API, incluindo update parcial contra estado combinado. Atualizar tipos/UI/ajudas e cobrir CRUD e regra pausada com fakes.
6. Disponibilizar CLI de prévia e medição por corpus com os módulos de produção; atualizar documentação e instruções de migração. Rodar testes/build/lint/tipos e simulação depois, revisar diff e registrar limitações/continuidade. Parar na etapa 2.

### Arquivos confirmados e áreas propostas

- `bot/src/extractor.py`, `bot/src/filters.py`, `bot/src/cache.py`: lógica central, resultados/matching e preparação de snapshot.
- `bot/src/modelos.py`, `bot/src/telegram.py`, `bot/src/estado.py`: envelope/contexto serializável, extração de entidades e migração.
- `bot/src/pipeline.py`, `bot/src/repository.py`, `bot/src/observabilidade.py`: decisões compatíveis, projeção remota e motivos/logs saneados.
- `bot/src/dedup.py`, `bot/src/main.py`, `bot/src/recuperacao.py`, `bot/src/sinais.py`: contratos a preservar; mudanças só se indispensáveis à integração, sem alterar algoritmo ou proteções.
- `bot/tests/test_pipeline.py`, `test_sdk.py`, `test_coleta_retoma.py`, `test_checkpoints.py`, `test_repository.py`, `test_retencao.py`, `test_sinais.py` e demais testes existentes: regressões a preservar/ampliar.
- `bot/simulacao.py`: mesma simulação antes/depois, sem mudar dataset para esconder regressão. **Novo proposto:** `bot/previa.py`; novos testes/fixtures e utilitários de normalização/extração/adaptadores sob `bot/`, nomes finais a registrar sem plataforma extra.
- `backend/src/services/filtro.service.js`, `backend/src/models/filtro.model.js`, `backend/src/controllers/filtro.controller.js`, `backend/src/routes/filtro.routes.js`: contrato e validação; `backend/package.json`: script de teste. **Área nova proposta:** testes em `backend/tests/` com runner Node nativo e dependências injetadas/falsas, evitando nova biblioteca se desnecessária.
- `frontend/app/filtros/page.tsx`, `frontend/lib/types.ts`, eventualmente `frontend/components/ProdutoCard.tsx` e testes novos próximos/num diretório de testes: funcionalidade de filtros e regressões sem duplicar avaliação Python em JS.
- `supabase/schema.sql`: bloco SQL aditivo seguindo convenção atual; `README.md` e, se necessário, descrição contratual em `CLAUDE.md`: documentação, não alteração de proteções.
- Não há nome confirmado para benchmark de corpus ou testes UI; definir na implementação e documentar comando reproduzível. Não presumir framework E2E já instalado.

### Decisões e restrições

Os nomes tipo/modo, semântica de bloqueios, política de separadores, não derivação de parcelamento, faixas de validação e ordem de atualização estão explicitados neste PRD para evitar perguntas rotineiras durante implementação. São decisões propostas, não comportamento já entregue. Mudança material posterior exige revisão/aprovação; ajuste interno equivalente deve ser registrado. Não anexar diagnóstico ao dicionário expandido remotamente, não migrar identidade e não trocar versões de dependências para acomodar ambiente sem investigar.

## 10. Critérios de aceitação

Todos os exemplos abaixo são **fixtures sintéticas**, não amostras reais. Montantes em reais são apresentados com vírgula; números JSON continuam numéricos.

| ID | Relacionado a | Dado / quando / então verificável |
|---|---|---|
| **CA-001** | RF-001 | Dada mensagem `OFERTA IMPERDÍVEL\nSSD Kingston NV2 1 TB\nPor R$ 299,90\nhttps://loja.example/produto/123`, extrair título contendo `SSD Kingston NV2 1 TB`; SSD/Kingston são encontráveis na descrição. Caso com `SSD Kingston - NV2 1 TB - NVMe` preserva informação após hífens. |
| **CA-002** | RF-001, RN-001 | `SSD R$ 99` não é descartado só por ser curto; divulgação genérica com link de grupo é `sem_evidencia_de_oferta`; palavras presentes apenas em URL, cupom ou rodapé promocional não satisfazem interesse nem veto descritivo. |
| **CA-003** | RF-002 | `De R$ 399,90 por R$ 299,90` → atual 299,90/anterior 399,90. `Por R$ 299,90 / Frete R$ 15,00` → atual 299,90/anterior nulo; frete não vira preço do produto. |
| **CA-004** | RF-002 | `10x de R$ 99,90 / à vista R$ 899,00` → atual 899,00. Apenas parcelas, mesmo sem juros, não derivam total nesta versão; parcela com juros também mantém total desconhecido. |
| **CA-005** | RF-002 | `R$ 50 de desconto acima de R$ 300` e `20% OFF` não fornecem atual/anterior; `RTX 4060 1 TB` sem dinheiro não vira preço. Anterior menor/igual ao atual não produz desconto positivo no card/diagnóstico. |
| **CA-006** | RF-002, RF-005, RF-007 | Formatos BRL/inteiro/NBSP seguem política; formatos ambíguos ficam nulos/explicados. Zero explícito/gratuidade é conhecido, preço ausente não é zero. Teto 299,90 aceita 299,90 e rejeita 299,91; teto zero só aceita conhecido zero. Limites SQL/JSON/centavos são cobertos sem Decimal não serializável. |
| **CA-007** | RF-002, RF-009 | Post com `SSD ... R$ 299,90` e `Headset ... R$ 149,90` independentes resulta em motivo específico de múltiplas ofertas/preço ambíguo, nenhum card e nenhum retry infinito; relação de/por do mesmo produto não é falso múltiplo. |
| **CA-008** | RF-003 | Mensagem com link de grupo antes do produto escolhe o produto. URL curta válida é preservada sem abrir redirect; query/caminho com maiúsculas, parâmetros e parênteses legítimos permanecem; delimitadores externos saem; schemes não HTTP(S) não chegam ao link público. |
| **CA-009** | RF-003 | Mesmo texto/entidades/botões pelo live e resposta histórica raw, incluindo emoji astral antes de entidade URL/TextUrl, produz mesmo contexto e extração. Transporte falso comprova ausência de RPC de enriquecimento e uso correto de UTF-16. |
| **CA-010** | RF-003, RF-008 | Persistir contexto novo, reiniciar e processar produz mesmo título/preço/link/cupom/decisão. Migrar bancos antigos suportados, especialmente v4, preserva pendências, decisões JSON/hash, fronteiras, mídia e IDs; campos novos ausentes têm defaults seguros. Falha de migração não perde registros nem confirma versão pronta. |
| **CA-011** | RF-004 | `Use o cupom: \`AbC123\`` preserva `AbC123`; código isolado em backticks, `DESCONTO` e `cupom:` incompleto não fabricam código. Ambiguidade é explicada; oferta independente pode continuar válida sem cupom. |
| **CA-012** | RF-004 | Categorias de cadeira gamer/headset gamer/jogo PS5 seguem objeto principal; termos curtos e `game` dentro de `gamer` não geram substring acidental. Incerto → outros. Categorias bot/API/UI coincidem; `todos` é rejeitado como categoria de regra. |
| **CA-013** | RF-005 | Interesse com SSD e Kingston, modo todas, teto 350: oferta Kingston NV2 descrita como SSD por 299,90 aceita; só Kingston falha por palavra ausente. Modo qualquer aceita um termo. Regras distintas continuam alternativas e lista de palavras vazia não restringe. |
| **CA-014** | RF-005 | Frase `memória ram` casa após normalizar acentos/caixa/espaços, mas não com `memória ... oferta ... ram` dispersa. Palavras inteiras não casam dentro de outras palavras; sem fuzzy amplo. |
| **CA-015** | RF-005/006 | Sem preço conhecido, regra com teto rejeita por `preco_desconhecido`; regra sem teto pode aceitar. Com todas rejeitadas por razões distintas, diagnóstico preserva ID/motivos de cada regra em vez de um motivo enganoso único. |
| **CA-016** | RF-006 | Global com `usado, recondicionado`, modo qualquer, veta SSD Kingston recondicionado apesar de interesse permissivo; versão nova é aceita. Global em modo todas exige os dois termos. Bloqueio local só impede sua regra; outra pode aceitar. |
| **CA-017** | RF-006 | Somente globais sem match não exigem interesse; com match vetam. Nenhum ativo aceita oferta válida. Global sem termos ou com inclusões é inválido, nunca autorização; desconhecido/inválido não vira lista vazia e não substitui snapshot válido. |
| **CA-018** | RF-007 | CRUD offline persiste/lista tipo/modo; defaults legados são interesse/qualquer. Enums/categoria inválidos, termos vazios/duplicados/excessivos e moeda não finita/negativa/fora da precisão/faixa retornam validação sem gravar. |
| **CA-019** | RF-007 | Editar conteúdo de regra pausada preserva `ativo=false`; PUT apenas `{ativo: true}` conserva listas/categoria/teto/tipo/modo; omitido difere de null/[]; mudança parcial para global com inclusões remanescentes falha claramente. Regra inexistente é distinta de erro de coluna/model. |
| **CA-020** | RF-007 | Tela local com API/Auth falsos cobre criar/editar/listar/pausar ambos os tipos/modos, ajuda de escopo, teto zero e erro do servidor sem falso sucesso. Nenhuma opção depende de edição manual no banco; não se altera autenticação real. |
| **CA-021** | RF-007/008 | Script SQL aplicado duas vezes em Postgres local preserva IDs/dados/ativo legados, cria defaults/constraints e rejeita global inconsistente. Schema ausente retorna erro explícito na API/cache, nunca sucesso com campos descartados. Sem ambiente SQL, resultado é impedido, não aprovado. |
| **CA-022** | RF-008, RN-003/005 | Congelar decisão, simular commit remoto seguido de timeout, trocar filtros/extrator e reiniciar: extrator/avaliador não são chamados novamente; decisão/hash/vínculo persistidos são usados, sem outro card/aparição indevida, inclusive retry além da janela quando registro remoto existe no fake. Nenhum finalizado é reaberto em massa. |
| **CA-023** | RF-008/009 | Cliente Supabase falso rejeita chaves não permitidas: aprovação nova/antiga envia só colunas públicas. Diagnóstico, descrição normalizada e contexto ficam locais; logs não contêm texto/termos privados/cupom/URLs/tokens. Rejeição legítima não gera persistência remota. |
| **CA-024** | RF-009 | CLI executa com credenciais ausentes e rede proibida; mesma entrada/contexto/snapshot produz dados e motivos equivalentes ao pipeline. Saída JSON e códigos de saída distinguem avaliação válida, configuração inválida e falha técnica. |
| **CA-025** | RN-004, RNF-005 | Suíte base e novos testes passam em ambiente compatível, sem remover assertions de durabilidade/idempotência/sinais/retenção. Mudança de semântica de cupom/filtro tem justificativa/casos positivos e negativos; skips/falhas não são omitidos. |
| **CA-026** | RF-010, RNF-001/002/005 | Mesma simulação antes/depois e corpus variado medidos com comandos/ambiente/dataset; nenhuma consulta externa/espera nova na extração e limites/progresso preservados. Relato separa custo CPU/local de rede fake e não promete tempos de VPS/frontend. Documentação inclui migração/rollback/continuidade e limitações da etapa 3. |

## 11. Plano de validação

### Automatizada — na implementação futura

- [x] **Baseline e suíte Python:** Python3.12/pins, baseline118 e fechamento241/241 sem skips emLinux/WSL; `pip check` aprovado. Comandos/resultados na seção16, sem`-S` ou relaxamento de assertions.
- [x] **Extração/filtros:** fixtures sintéticas/negativos/adversariais/BRL/NBSP/zero/centavos e regressões históricas passaram com rede proibida nos controles.
- [x] **SQLite/Telegram/pipeline:** bancos temporários reais/migrações/rollback,SDKfixado/live/raw/UTF-16,spies de decisões/hash e commits ambíguos/restart aprovados.
- [x] **API:** script `npm test` entregue/40testes,model/service/rotas/merge/schema comfakes,23JS/MJS sintaticamente aprovados; sem scriptslint/build/typecheck inexistentes declarados executados.
- [x] **Frontend:** lint/tsc/buildNext comenvfictício aprovados; comandos exatos na seção16.
- [x] **UI:**7testes do componente real comAPI/Auth/hooks falsos,formulário/modos/pausado/zero/erros/escape aprovados; não browserE2E.
- [x] **SQL:** bloco aplicado2× emPostgreSQLlocal/PGlite,fixtureslegadas/defaults/constraints/preflight/atomicidade aprovados,semSupabasereal.
- [x] **CLI:** módulo`previa` entregue; JSON/equivalência/códigos0/2/1/semcredenciais/socketproibido aprovados,exemplo executado.

### Simulação antes/depois e custo local

Executar **exatamente a mesma carga**, sequencialmente, a partir de `bot/`, antes de alterar a lógica e ao final:

```text
python -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1
```

- Registrar versão Python/SDKs, sistema/filesystem e carga concorrente relevante, hashes/quantidade dos datasets, parâmetros, duração/janela, contagens por decisão, latência p50/p95/máximo por origem, vazão, filas inicial/pico/final, máximos de workers e heartbeat. Mídia atrasada não entra na latência de confirmação da oferta; não esperar drenar fotos para melhorar artificialmente o número.
- Não trocar dataset/delays/instrumentação entre antes/depois para atribuir ganho. Se precisar corrigir o runner, registrar e repetir baseline comparável sem descartar trabalho do usuário. Histórico do benchmark entra direto na inbox: equivalência raw/RPC é provada por testes próprios.
- Medir separadamente extração + avaliação de corpus sintético com mensagens curtas/longas, genéricas, preço/frete/parcela, entidade/botão, múltiplas ofertas, frases, bloqueios e limite de regras/termos. Fixar corpus/seed/iterações, aquecer antes, usar relógio monotônico de alta resolução, relatar amostras/p50/p95/máximo e taxa em ambiente descrito. Preparação do snapshot deve ser medida separada do custo por mensagem.
- Comparar mesmos textos/filtros possíveis no baseline, explicando novos campos não suportados antes. Para modos novos medir depois sem fabricar comparação funcional inexistente. Sem espera artificial ou acesso externo na medição da lógica pura.
- Aceite de recursos: workers limitados, progresso live/histórico, oferta sem esperar mídia, ausência de novos acessos de enriquecimento por mensagem e ausência de processamento explosivo nos casos adversariais. Não há SLA numérico de VPS aprovado; regressão local expressiva precisa de investigação/registro, não promessa ou omissão.

### Manual/documental e regressões prioritárias

- [x] Revisar semântica da tela com API falsa, incluindo estado pausado e falha de schema, sem login real.
- [x] Conferir que fixtures são sintéticas; se houver fonte real fornecida posteriormente, sanear/identificar origem sem expor dados privados.
- [x] Conferir ordem schema → bot/backend → UI, rollback limitado, pendências de operação e comandos de CLI/exemplos no README.
- [x] Revisar diff/status, SQL aditivo e projeção remota; nada em legado/Gemini, autenticação, identidade, janela de dedup, migração de imagens ou deploy.
- [x] Reexecutar regressões de coleta/geração/paginação, sinais, retenção, cache desconhecido/vazio, retry idempotente, aparição/foto e commit ambíguo; não modificar suas garantias para acomodar o extrator novo.

### Evidências deste planejamento

| Procedimento executado | Resultado e limite |
|---|---|
| Git raiz/status/log/HEAD/worktrees | Base e preservação descritas na seção 3; nenhum comando de alteração Git. |
| Leituras do runtime, template, instruções, entrada, README, PRD anterior e fontes/manifests/testes relacionados | Fundamentam estado atual e áreas confirmadas; não executam aplicação nem provam contrato remoto real. |
| Contagem por AST com `python -B -c` | 11 arquivos `test_*.py`, 118 métodos `test_*`. Primeira tentativa do comando de contagem teve erro de parêntese no script efêmero; comando corrigido concluiu sem escrever arquivos. Não é falha/teste da aplicação. |
| Conferência estrutural somente leitura do PRD | 16 seções, 10 RF e 26 CA únicos/ordenados; metadados de rascunho/versão 1/aprovação pendente/base corretos; sem whitespace final. Não é teste da aplicação. |
| `git status --short --branch` e `git diff --exit-code` após criação | Somente este PRD novo e os três prompts preexistentes não rastreados; diff rastreado vazio. Nenhum código ou arquivo preexistente alterado. |
| Testes/build/lint/simulação/migrações | Não executados neste comando de planejamento; resultados futuros pendentes. |

## 12. Riscos, premissas e perguntas

### Riscos

| ID | Risco | Probabilidade / impacto | Mitigação e sinal de parada |
|---|---|---|---|
| R-001 | Heurística confundir valor, produto ou múltiplas ofertas | alta / alto | Evidência contextual, nulos/diagnóstico, corpus sintético e casos negativos. Parar se solução depender de IA/rede ou nova arquitetura multioferta. |
| R-002 | Entidades cortadas por UTF-16 ou divergência raw/live | media / alto | Converter texto bruto no limite SDK e testar emoji, botões, persistência e raw sem `_finish_init` privado. Não aceitar índices Python ingênuos como equivalência. |
| R-003 | Reavaliação/hash novo em retry causar duplicata ou vetar efeito já confirmado | media / alto | Decisão/hash soberanos, leitores antigos compatíveis e spies/falhas entre commits. Parar se exigir reprocessamento histórico/identidade nova. |
| R-004 | Global ser interpretado como interesse por serviço antigo | media / alto | Ordem de atualização, capacidade de schema e coleta suspensa durante transição; rollback condicionado. Não habilitar UI global com bot antigo. |
| R-005 | SQL/validação nova invalidar legado silenciosamente | media / alto | Defaults compatíveis, preflight/testes locais, sem apagar/normalizar regras arbitrariamente. Dados reais incompatíveis exigem decisão autorizada, não fallback permissivo. |
| R-006 | Diagnóstico vazar para colunas remotas/logs ou crescer sem controle | media / alto | Campos internos separados, whitelist remota, limites de listas e logs por códigos/IDs; teste de payload e privacidade. |
| R-007 | Custo de regex/normalização/regra prejudicar caminho crítico | media / medio | Preparação por snapshot, custo linear controlado, corpus adversarial e benchmark. Não mascarar piora com sleeps/dataset menor. |
| R-008 | Ambiente local impedir cobertura SDK/POSIX/SQL/UI | media / medio | Confirmar toolchains, usar WSL local/fakes/Postgres descartável quando disponível e registrar resultados impedidos. Sem acesso remoto como atalho. |

### Premissas

- **PRM-001:** sistema continua pessoal, com um coletor e as proteções de estado da etapa 1; confirmar na composição/testes, sem consultar VPS.
- **PRM-002:** categorias/contratos do checkout representam o alvo; schema remoto só será conferido numa futura operação autorizada. SQL desta entrega é preparado e testado localmente, não aplicado remotamente.
- **PRM-003:** não há corpus real suficiente nas áreas inspecionadas para adaptador específico. Entregar genérico/ponto de extensão; se aparecer corpus fornecido com fonte, avaliar suficiência sem inventar formatos.
- **PRM-004:** preço desconhecido não invalida por si só uma oferta descritiva com evidência comercial; impede regras com teto. Post só de cupom/desconto/divulgação não vira produto por essa permissão.
- **PRM-005:** limites de nome/termos/moeda e política monetária da seção 6 são defaults da entrega, não dados já observados em produção. Testar limites e compatibilidade sem alterações silenciosas de valores legados.
- **PRM-006:** ausência de derivação de parcelamento e código formatado isolado não ser cupom são escolhas conservadoras compatíveis com a entrada, que devem ficar documentadas nos exemplos/limitações.

### Perguntas abertas

- **PA-001 — não bloqueante:** haverá amostras reais saneadas de canais com fonte para calibrar adaptadores? Não condiciona esta entrega: fallback genérico é obrigatório e suficiente no escopo definido.
- **PA-002 — não bloqueante:** Postgres local e o ambiente Python 3.12/WSL previamente usado ainda estão disponíveis? Confirmar no início da implementação; limitações devem ser registradas, sem execução remota.
- **Perguntas bloqueantes:** nenhuma para especificar/aprovar esta versão. Nenhuma aprovação de implementação está implícita neste planejamento.

## 13. Proteções adicionais

- [x] Compatibilidade SQLite/JSON/hash congelado conferida com falhas, reinício e banco v4 real, incluindo rollback de migração.
- [x] SQL aditivo aplicado duas vezes em PostgreSQL local embarcado; defaults/constraints/preflight, erro de schema e rollback documentados/testados.
- [x] Payload remoto por lista permitida, logs saneados, schemes e fixtures sintéticas revisados/testados.
- [x] Bot/API/tela: veto após serviço/preço,teto zero e associação contextual cobertos;40API/7UI atuais aprovados. Rejeições não chamam remoto e decisões antigas continuam soberanas.
- [x] Fechamento integral aprovado:241/241 em90,349s,zero falhas/erros/skips,watchdogs2s/3s/debug/WAL/FULL/asserts intactos. Erros históricos e custo de armazenamento preservados como observação,sem declarar causa única/resolução universal.

## 14. Checklist de implementação

- [x] **T01 — Baseline e contratos:** baseline WSL/Python 3.12.3 executado antes das mudanças funcionais: 118 testes passaram sem skips; simulação de 130 ofertas concluída. Interfaces de contexto, extração detalhada e avaliação foram fixadas entre as frentes; somente fixtures sintéticas, sem alteração remota.
- [x] **T02 — Extração genérica contextual:** corrigidos condição após serviço não monetário, campos rotulados com preço próprio distinguido semanticamente e múltiplos inline; derivados por cláusula compartilhados, incluindo limpeza de serviços/parênteses vazios sem apagar marca/modelo residual. Todas as regressões de validação foram mantidas e passaram.
- [x] **T03 — Contexto Telegram e migração local:** UTF-16/SDK, botões, equivalência live/raw/restart e migração aditiva v5 com banco v4 real/rollback aprovados nos testes locais.
- [x] **T04 — Regras e decisão segura:** dados de veto/múltiplos/campo revalidados no avaliador e inbox/pipeline real local com remoto falso; frases não são coladas entre cláusulas. Whitelist/hash/decisões congeladas passam na suíte completa, sem reavaliar histórico.
- [x] **T05 — Schema/API/UI:** SQL aditivo, 40 testes API e 7 testes UI locais aprovados; edição pausada/teto zero/NULL legado e erro de schema cobertos, sem banco remoto.
- [x] **T06 — Prévia e documentação:** CLI executada sem tokens, exemplos sintéticos, semântica, migração/rollback, comandos e limites documentados.
- [x] **T07 — Verificações finais e medições:** fechamento normal241/241/90,349s,sem skips;40API/7UI/lint/tipos/build/SQLlocal/pipcheck/CLI aprovados. Medições de pipeline/corpus anteriores preservadas sem código/dataset novo; novo controle de armazenamento400operações íntegro. CA-025 atendido nesta rodada,sem reescrever falhas anteriores.
- [x] **T08 — Revisão e continuidade:** preservação/contratos/diff/risco e evidências reavaliados; nenhum patch especulativo. Estado`concluido`,v1aprovada,21/21requisitos/26/26critérios,observação temporal documentada;sem publicação/etapa3 automática.

## 15. Registro da implementação

### Retomada de VAL-ET2-005 — 2026-11-05 — pronta para nova validação

Invocação explícita de `sdd-implementar`; raiz/runtime global e `_comum.md`/`implementar.md`/PRD integral/`CLAUDE.md` reconfirmados, base `main / 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a`, único worktree. Sem `.sdd-lite` local ou AGENTS.md. Estado `em_implementacao`, aprovação v1 preservada. O diff existente e todos os234 métodos/assertions são trabalho preexistente, inclusive os controles da última validação; não descartar ou enfraquecer.

Roteiro: **D01 — reprodução instrumentada e hipóteses; D02 — diagnóstico/controles determinísticos; D03 — verificações afetadas, revisão e encaminhamento: concluídos na implementação**. Escopo restrito ao timeout de fechamento após refresh de filtros. Instrumentação de teste permaneceu fora de produção, sem ler dados reais; nenhum watchdog/espera, debug, WAL/FULL ou requisito foi alterado. Sequência finita: uma suíte instrumentada inicial, amostra previamente fixada de20 casos com perfil, comparação complementar de fontes idênticas, quatro controles e **uma suíte final normal**. Não houve repetição completa cega até verde; todas essas execuções passaram. A causa histórica continua inconclusiva, sem autorização inferida para redesign/permissões/dependências ou nova regra.

Investigação inicial: análise estática independente não encontrou perda permanente de progresso no interleaving de notificação/snapshot/claims; `_esperar` relê configuração e consulta elegibilidade antes de esperar. Diagnóstico transitório externo instrumentou submissão/fila/execução CPU e wall/retorno ao loop, estados de cache, logs por códigos e heartbeat no caso original. SQLite temporário confirmado em `/tmp`/**ext4**, não `/mnt/c`; fontes/venv em `/mnt/c`/**9p**. Não presumir que uma escritaSQLite é lenta pelo caminho das fontes.

Uma execução completa instrumentada sem editar fontes/tests passou234/234 em88,165s, zero skips; alvo0,880441s incluindo setup/teardown,51 operações. Máximos alvo: fila0,317ms, thread12,526ms/CPU2,936ms, retorno ao loop66,488ms, total66,798ms; heartbeat43,543ms. Claim→decidir→reserva→vínculo→finalização ocorreu; aprovado e depois rejeição da mensagem2 com snapshot preservado. Não reproduziu timeout, não é prova da causa histórica.

Amostra **fixa de20 casos originais**, com perfil sem alterar debug/watchdog/asserts, passou20/20 em19,161s. `cProfile`: total20,145s, `posix.stat`16,318s cumulativos (~75,8mil chamadas), `linecache.checkcache`17,087s e extração de stacks17,983s; maiores operações SQLite esperaram retorno ao loop182,869ms após thread0,342ms. Medição controlada `os.stat` sem mocks, mesma cópia byte a byte de `pipeline.py`,100 aquecimentos/1000 amostras por caminho/ordem seed42: fonte9p p50/p95/máx886,949/1194,250/6742,729µs versus cópiaext4 7,098/16,094/79,968µs. **Custo de metadados/tracebackdebug demonstrado nestas medições; a causa do timeout histórico ainda não foi diretamente observada.** Não desabilitar debug nem usar esta correlação como justificativa para relaxar a suíte.

Helpers/evidências somente no diretório aprovado `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/`: `dealbot-etapa02-timeout-diagnostico.py`, `dealbot-etapa02-timeout-completo-01.json`, `dealbot-etapa02-timeout-isolado-20.json`/`.prof` e `dealbot-etapa02-timeout-comparar-fs.py`. Não são dependência/serviço nem arquivos de produção. Sem strace/perf/pidstat instalados; não houve instalação como atalho. Os tempos88,165s/19,161s são do runner unittest; os JSONs medem90,337870s/19,418113s na janela maior da sonda. Os tempos cumulativos de stat/checkcache/traceback são aninhados, não devem ser somados. Arquivos intactos não tornam a sonda equivalente ao runner normal: ela substitui métodos em memória e acrescenta heartbeat; por isso a execução final foi sem essas sondas.

#### Comparação complementar e alcance do diagnóstico

`dealbot-etapa02-timeout-comparar-fs.py --modo isolado`: mesmo caso **original**, bytes selecionados de fontes/testes conferidos por hash antes da execução, mesmo Python/venv/pins/env controlado/debug/asserts/watchdog; somente cópias sintéticas em diretório ext4 temporário, sem `.env`, estado operacional ou alteração no worktree. Um ensaio9p seguido de umext4, com cProfile e sem as sondas de métodos/heartbeat:

| Fonte dos módulos | Teste original | Perfil total | `stat` cumulativo | `linecache.checkcache` cumulativo |
|---|---|---|---|---|
| Checkout `/mnt/c`/9p |1/1 em0,479s |0,751065s |0,422354s |0,346286s |
| Cópia com mesmos bytes/ext4 |1/1 em0,187s |0,360909s |0,064360s |0,047204s |

Confirma sensibilidade observada ao caminho dos metadados/debug, **não isolamento completo nem causa do timeout histórico**: ordem fixa favorece possíveis caches, interpretador/venv continuam em9p e o host não é laboratório isolado. A comparação não foi usada como troca de ambiente para conseguir o aceite: a suíte final normal rodou no checkout original em`/mnt/c`. Sem desativar debug ou alterar a durabilidade. Não há evidência para uma correção funcional de produção; aplicar um patch em cache/worker/SQLite sem defeito confirmado seria especulativo.

Falha **da ferramenta de diagnóstico**, não do teste/aplicação: após ambos os testes/perfis concluírem, o exportadorJSON inicial tentou serializar o dicionário de callers do pstats com chaves tupla e saiu1. Corrigida somente a serialização no helper externo; métricas recuperadas dos perfis **sem reexecutar os ensaios**. Evidências `dealbot-etapa02-timeout-fontes-par-01-{9p,ext4}.prof` e `dealbot-etapa02-timeout-fontes-par-01-recuperado.json`. Uma tentativa de patch documental com contexto incorreto também não foi aplicada; corrigido o contexto, sem alteração de produção.

#### Alterações e controles de prevenção

- **Produção, dependências e234 testes anteriores: nenhuma alteração nesta retomada.** Acrescentado somente `bot/tests/test_progresso_configuracao.py` com quatro métodos; `README.md` documenta separação de custos/debug/filesystems e comando dos controles. Este PRD registra resultados/estado, sem mudar requisitos ou matriz de validação anterior.
- Novos testes mantêm SQLite real/executor/commit/FULL, dois workers, fakes remotos e `aguardar` original de3s. Não usam sleeps temporais para ordenar execução, não substituem `Event.wait/clear` nem fabricam resultado SQL; barreiras seguram retornos de operações reais. O terceiro observa `_waiters` do Event, sem alterar a coleção, no alvo Python3.12 documentado.
- Caso1: refresh após ambos os SELECTs sem configuração e antes de devolverNone. Caso2: refresh após consultas reais de próxima tentativaNone e antes da espera. Caso3: worker1 limpa naturalmente o evento enquanto worker0 ainda não começou a esperar; o SELECT válido do primeiro garante progresso. Caso4: adiamento durável já confirmado, retorno do worker proprietário retido; outro aprova, e a liberação do primeiro não regride a decisão.
- Asserts conferem ausência de escrita remota antes do snapshot válido, estadoaprovada/tentativas2, decisão/hash/diagnóstico/snapshot/vínculo, exatamente umproduto/umaaparição/umupsert por tabela e `fatal` pendente. Barreiras liberadas emfinally, workers encerrados dentro dos patches e SQLite/diretório fechados depois. Esses controles **não reproduzem o timeout nem provam ausência universal de race/restart**; complementam as regressões existentes.
- Revisão independente somente leitura aprovou os quatro interleavings, assertions e cleanup, sem ajuste obrigatório/crítico/maior. Não executou testes/benchmarks nesta revisão e não substitui validação SDD. Revisão crítica das evidências também confirmou que pronto para validação não significa achado causalmente resolvido/CA-025 aprovado.

#### Comandos e verificações desta retomada

Python3.12.3, Telethon1.36.0, Supabase2.9.1, HTTPX0.27.2, Storage3 0.8.2, dotenv1.0.1, WSL2/Linux6.6.87.2/glibc2.39; nenhum pacote instalado/atualizado. Comandos em`bot/` com prefixo **`wsl --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`**. Helpers usam caminhoWSL `/mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/`; fora do worktree. Benchmarks finais sequenciais após a suíte, sem testes/build concorrentes iniciados pelo agente. Host não isolado.

| Comando/procedimento | Resultado real/limite |
|---|---|
| `python -B …/dealbot-etapa02-timeout-diagnostico.py --modo completo --saida …/dealbot-etapa02-timeout-completo-01.json` |234/234, runner88,165s/sonda90,337870s, zero skips, arquivos fontes/testes antes/depois idênticos; execução instrumentada, não fechamento normal. |
| `python -B -m cProfile -o …/dealbot-etapa02-timeout-isolado-20.prof …/dealbot-etapa02-timeout-diagnostico.py --modo isolado --repeticoes 20 --saida …/dealbot-etapa02-timeout-isolado-20.json` |Amostra fixa20/20, runner19,161s/sonda19,418113s, zero skips; perfil aninhado exposto acima. |
| `python -B …/dealbot-etapa02-timeout-comparar-fs.py --modo isolado --prefixo …/dealbot-etapa02-timeout-fontes-par-01` |Dois casos aprovados,0,479s/0,187s; exportação final do helper saiu1 porTypeError após concluir testes/perfis. Recuperado dos artefatos sem repetir; não é uma comparação de suítes completas/produção. |
| Sonda de`os.stat` por stdin, mesmo conteúdo9p/ext4 |100 aquecimentos+1000amostras por caminho, ordemseed42; p50/p95/máx e limites documentados acima. Sem mocks. |
| `python -B -m unittest tests.test_progresso_configuracao -v` |4/4 em1,297s, saída0, sem skips. Execução direcionada única feita na frente de testes. |
| **`python -B -m unittest discover -s tests -q` — fechamento sem sondas** |**238/238 em82,897s, saída0, zero falhas/erros/skips**, no checkout original9p. Watchdogs/debug/commits/asserts originais, SDKs/POSIX/SQLite/fakes. Warnings GoTrue e tasks lentas4,620/4,721/0,865s não suprimidos; não provam a causa do episódio anterior. |
| `python -m pip check` |No broken requirements found, saída0. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` |Saída0, títuloSSDKingston NV2 -1TB-NVMe,299,90/399,90,`AbC123`,URL/query/caixa preservadas, aceita/regra1. CLI semenv/rede e códigos0/2/1 também cobertos na suíte normal. |
| Revisão independente estática e de controles |Sem defeito produtivo demonstrado/interleaving que explique perda permanente neste caso; quatro controles aprovados no recorte. Sem prova universal nem fechamento do achado. |
| AST e conferência estrutural por stdin, sem escrever bytecode |46 arquivos Python parseados/238 métodos; PRD`em_validacao`/v1/aprovação preservados. README/PRD/teste novo sem whitespace final. |
| `git diff --check`/diff/status/arquivos protegidos |Saída0 nos checks, avisosLF/CRLF; arquivos desta retomada restritos a teste novo/README/PRD. Sem staging/commit/publicação/segredos/sonda em produção. |
| API/UI/lint/tipos/build/SQL local |**Não reexecutados nesta retomada**, sem mudança em fontes/contratos dessas camadas ou produçãoPython. Validação anterior de05/11 registrou40API/7UI/lint/tipos/build/SQL aprovados; não apresentar como execuções novas, Node20/browser/Supabase reais. |

Comando de preservação executado com saída0/vazia: `git diff --exit-code -- bot/src/dedup.py bot/src/main.py bot/src/recuperacao.py bot/src/sinais.py bot/src/midia.py bot/bot.py bot/requirements.txt bot/dealbot.service bot/simulacao.py backend/package-lock.json frontend/package-lock.json backend/src/middlewares/auth.js frontend/hooks/useAuth.ts frontend/lib/api.ts`. O restante do diff de implementação é preexistente; nenhuma alteração funcional da etapa foi descartada. Não há lint/mypy Python configurado ou cobertura percentual declarada.

#### Medições finais sem mudar produção ou datasets

`python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1`:

- 130 recebidas/produtos/aprovadas, zero falhas/descartes/duplicatas; **4,606213s/28,222750 ofertas/s**. Live p50/p95/máx **296,504/360,792/363,644ms**; histórico **3004,208/4447,568/4579,923ms**; heartbeat máximo **1,353743ms**. Janela243,251313796–247,857526881, inícioUTC`2026-11-05T17:03:44.057225+00:00`, termina nas ofertas finalizadas, sem setup/shutdown/drenar fotos.
- Workersmáx4/1; filas inicial/pico/final live0/8/0, histórico0/100/0, mídia0/114/114.16fotosprontas,113pendentes/umaprocessando,17tentativas/zero falhas. Ambas as origens avançaram; buffer/página100, zero task por mensagem,130amostras. Uma consulta de filtros,130de cada operação fake/oferta,17buscas de mídia/16vínculos.
- Hashes live`606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb` e histórico`27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805` preservados, cinco esperas20ms/oferta e mídia200ms. Comparação com4,879583s da validação anterior e34,241864s da segunda retomada é variação observada **sem patch produtivo**, não ganho causal/diagnóstico definitivo da cauda antiga.

Corpus por stdin, mesmo comando equivalente usado antes: `import asyncio,json,medir_extracao as m; r=asyncio.run(m.medir(100)); r['limites_regras']=m.medir_limites(); r.pop('exemplos'); r.pop('extracao_por_caso'); print(json.dumps(r,ensure_ascii=True,indent=2))`.

28casos sintéticos/seed42/três aquecimentos/2800amostras, SHA256`1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c` inalterado; janela2,945244s/950,69mensagens/s. p50/p95/máxµs: extração190,268/11093,557/18316,864; conjunto209,796/11132,139/18342,550; avaliação2500válidas19,891/36,285/317,306; preparo100amostras15,791/19,388/284,326. Limite10regras×50termos/lista×100caracteres,preparoúnico120053,435µs/20avaliações sem reextração: curta1555,606/1717,190/2293,551µs, longa2695,035/3148,597/3167,390µs, adversarial1531,266/1925,203/2622,815µs. Sem rede/espera na lógica pura; custoCPU e perfisdebug são dimensões distintas, não SLA deVPS/frontend.

#### Estado de saída e continuidade

**`em_validacao`**, aprovação v1 preservada. Pronta para nova avaliação após investigação delimitada, cobertura adicional e fechamento normal aprovado, **não entrega concluída ou aceite parcial**. VAL-ET2-005 permanece historicamente reprovado, **causalmente inconclusivo e pendente de reavaliação pelo validador**; suas matrizes na seção16 não foram alteradas para aprovar CA-025. Não se declara resolução definitiva da intermitência, causa ambiental comprovada ou ausência universal de races.

Próximo comando: **`/sdd-validar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`**. Avaliar o conjunto atual sem promover o verde instrumentado/perfil a prova causal, preservando os238 controles. Se o timeout reaparecer, capturar erro/estado/fatal/operação em curso, sem aumentar watchdog/silenciar falha. Sem nova correção especulativa ou repetições cegas. Limites anteriores de corpus/heurísticas, Node20/browserreal/produção/contas/Supabase/VPS não verificados; nenhuma migração de dados reais, stage3/identidade/imagens/auth/SQL remoto/publicação iniciada.

### Segunda retomada autorizada — 2026-11-03 — pronta para validação

Nova invocação de `sdd-implementar`, raiz/runtime global/instruções/PRD integral e base `main / 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a` reconfirmados. Versão1/aprovação preservadas; escopo: VAL-ET2-001 e003 residuais,004 e processamento descritivo redundante de RNF-002. Todo o diff anterior e os testes da revalidação são preexistentes. Não alterar requisitos nem enfraquecer suas assertions.

Roteiro: **SR01 — reprodução/baseline (concluído)**; **SR02 — correções e controles cruzados (concluído)**; **SR03 — suíte/medições/revisão/encaminhamento (concluído na implementação)**. Produção permanece local/pura; decisões/hash/dados reais, publicação e etapa3 fora do escopo. A conclusão da entrega exige nova validação SDD.

#### Alterações desta segunda retomada

- Única alteração funcional em `bot/src/extractor.py`. Novo `bot/tests/test_segunda_retomada_etapa2.py`: **13 métodos** (12 síncronos e um de inbox/pipeline), com subcasos sintéticos; `README.md` e este PRD atualizados. Os217 métodos e asserts preexistentes, inclusive os cinco da última revalidação, ficaram intactos.
- **VAL-ET2-001 residual:** cláusulas de serviço não monetário (`Frete incluso`, entrega/envio incluídos) têm somente seu intervalo reconhecido removido. Separadores de cláusula, inclusive vírgula fora de decimal, conservam a condição posterior: `Frete incluso, USADO` veta; cupom, URL, divulgação e destino de serviço não viram descrição de produto. O fallback desconhecido limita-se à cláusula, não ao restante da linha.
- **VAL-ET2-003 residual:** campos rotulados de componentes do computador sem preço próprio são continuidade; os valores são classificados e validados antes de decidir se há preço próprio. Frete/parcela/anterior não são preço atual do componente. Memória apenas quantitativa tem correspondência completa; marca/modelo residual, como Kingston Fury, abre grupo independente que recebe seu preço posterior, com ou sem dois-pontos. Retirar serviço/preço limpa delimitadores vazios, não marca/modelo restante.
- **VAL-ET2-004:** associação de valores usa grupos locais por trecho descritivo, não número da linha. Dois objetos com preços próprios em cláusulas da mesma linha são múltiplos, mesmo com montantes iguais. Relação de/por, frete e parcelas do mesmo produto permanecem no grupo corrente; kit com um único preço não vira múltiplo só por nomear objetos.
- **RNF-002/NV-OBS-001:** `_TrechoOferta` privado e transitório compartilha texto/descrição/normalizada entre classificação monetária, título, conteúdo e categoria. `_descricao_linha` é chamado uma vez por linha; não há cache global, compilação de regras por oferta, formato persistido ou campo remoto novo. Normalização descritiva só é refeita se a remoção altera o trecho. Título preserva os trechos da primeira linha; conteúdo mantém fronteiras de cláusulas para não transformar palavras dispersas numa frase nova após omitir chamada genérica.
- Classificador de preço usa limite de token antes dos marcadores também após parêntese; somente parcela explicitamente identificada é retirada por inteiro da descrição, sem cálculo de total. Nenhuma regra de produto/contrato mudou, não há IA/rede/enriquecimento, dependência/migração ou novo algoritmo de identidade. São refinamentos locais das heurísticas aprovadas, não promessa de entender qualquer formato.

Para comparar somente esta retomada (não confundir com todo o diff da etapa2), foi guardado snapshot local do extrator pré-edição em `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-segunda-retomada-qt0bbryo/extractor_antes.py`. Usado apenas para leitura/diff pelo implementador e revisor; não é dependência da aplicação ou cópia do serviço em produção. Branch/base e todo trabalho anterior preservados.

#### Verificações e revisão desta segunda retomada

Comandos em `bot/`, prefixo WSL existente `wsl --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`; Python3.12.3/SDKs fixados, Linux6.6.87.2 WSL2/glibc2.39 em `/mnt/c`. Sem instalação/upgrade ou credenciais; benchmarks finais sequenciais após a suíte, sem build/testes concorrentes iniciados pelo agente. Host/filesystem não isolados.

| Comando/procedimento | Resultado real e limite |
|---|---|
| `python -B -m unittest tests.test_revalidacao_etapa2 -v` antes de alterar | **5 métodos, quatro assertions falhas em três métodos, 0,019s**, código1; causas da última validação reproduzidas. |
| Mesmo comando após correções | **5/5 passaram, 0,014s**, código0; confirmado novamente dentro da suíte completa final. Asserts originais não alterados. |
| Conjunto dirigido final: `python -B -m unittest tests.test_segunda_retomada_etapa2 tests.test_revalidacao_etapa2 tests.test_validacao_etapa2 tests.test_correcao_etapa2 tests.test_extracao tests.test_decisoes_etapa2 tests.test_filtros_etapa2 -q` | **101/101 passaram, 22,287s**, zero erros/skips. Inclui três decisões pela inbox/pipeline, descarte sem acesso ao repositório, congelamento/whitelist e frases. Uma tarefa SQLite lenta foi observada; não houve timeout/assertion relaxada. |
| `python -B -m unittest discover -s tests -q` no fechamento | **230/230 passaram, 60,532s**, zero falhas/erros/skips, saída0. Inclui POSIX/SDK/SQLite/coleta/retenção/reconciliação e decisões históricas; warnings GoTrue/asyncio lento não suprimidos. |
| Execuções intermediárias completas |226/226 em83,886s;228/228 em88,510s;229/229 em87,720s, antes do controle adicional de frase. Não substituem o fechamento do código final. |
| Controles novos durante a correção | Primeira versão deixou um anterior parentetizado como preço próprio e, depois, dois subcasos de parcela deixaram `10x` na descrição quantitativa. Assertions mantidas; fronteira de marcador, intervalo completo de parcela e delimitadores vazios corrigidos. Os novos controles passaram depois, sem alterar expectativas para verde. |
| Revisão independente somente leitura | Primeiro ciclo identificou memória com marca/modelo absorvida e frete contado como preço próprio; segundo encontrou delimitadores vazios na memória quantitativa. Corrigidos e testados. Ciclo seguinte aprovou56 controles sintéticos. Após preservar fronteira de frase, último ciclo aprovou **42 controles**, sem impeditivo confirmado no recorte. Socket bloqueado, sem suíte completa/benchmark/edição pelo revisor; não é aprovação SDD integral nem cobertura universal. |
| `python -m pip check` | **No broken requirements found**, saída0; não alterou dependência. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` | Saída0, título SSD Kingston NV2 - 1 TB - NVMe, 299,90/399,90, `AbC123`, URL/query/caixa preservadas, `aceita_por_regra`/1. Equivalência CLI/produção sem env/rede e códigos0/2/1 novamente cobertos pela suíte final. |
| Diff local contra snapshot pré-retomada e arquivos novos | Alterações restritas a descrição/classificação/agrupamento/transientes e testes/documentação; sem mudanças remotas ou campos internos expandindo produto. Arquivos protegidos mantidos conforme comando abaixo. |
| `git diff --check` e AST/conferência dos arquivos novos | Saída0 (avisos LF/CRLF),46 arquivos Python parseados e230 métodos;13 testes novos. PRD em_validacao/v1/aprovação e ausência de whitespace final nos arquivos desta retomada confirmados. Não há lint/mypy Python configurado, nem se declara cobertura percentual ou essas ferramentas executadas. |
| `git diff --exit-code --` nos arquivos protegidos | Saída vazia/código0 para dedup/main/recuperação/sinais/mídia/legado/requirements/unit/locks npm/auth central/hooks e API frontend. Nenhum dado operacional real migrado/aberto. |
| API/UI/lint/tipos/build/SQL | **Não reexecutados nesta segunda retomada**, pois nenhuma dessas camadas foi alterada. Última validação registrada na seção16 aprovou40 API/7 UI/lint/tipos/build/SQL local. Não apresentar evidência anterior como execução nova ou como produção/Node20/browser real. |

#### Medições antes/depois desta segunda retomada

Antes das mudanças, comando exato de simulação da seção11: **130 recebidas/aprovadas/produtos**, zero falhas/descartes/duplicatas; **4,713740s / 27,578949 ofertas/s**. Live p50/p95/máx **208,433/284,998/296,567ms**, histórico **3076,328/4538,334/4683,628ms**, heartbeat máximo2,002ms. Filas inicial/pico/final live0/7/0, histórico0/100/0, mídia0/113/113;17 mídias prontas,112 pendentes/uma em processamento; workers máximos4/1 e progresso de ambas as origens.

Após todos os ajustes, inclusive fronteiras de frases, mesmo comando **`python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1`**:

- **130 recebidas/aprovadas/produtos**, zero descartes/duplicatas/falhas; **34,241864s / 3,796522 ofertas/s**. Live p50/p95/máx **2085,676/4061,785/4192,124ms**, histórico **32503,760/34078,962/34214,751ms**; heartbeat máximo **2,354ms**.
- Workers máximos4/1; filas inicial/pico/final live **0/13/0**, histórico **0/100/0**, mídia **0/103/103**;27 prontas,102 pendentes/uma em processamento. Página máxima100, zero task por mensagem; ambas as origens avançaram antes do fim da outra. Janela termina na última oferta terminal, sem setup/shutdown nem drenar fotos.
- Hashes live `606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb` e histórico `27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805` inalterados, com cinco operações20ms/oferta e mídia200ms. As execuções intermediárias pós-ajustes parciais foram4,663672s/27,875032 ofertas/s e5,090038s/25,540086 ofertas/s; preservadas como variação, não escolhidas para esconder o fechamento lento.

**Piora substancial de duração/latência local no fechamento**, sem perda funcional ou explosão de workers. Causa exata de host/filesystem/instrumentação não isolada; não atribuir automaticamente ao ambiente nem declarar ganho do pipeline. Investigação separada de lógica pura abaixo encontrou custos menores que o baseline desta retomada, inclusive num texto curto do formato da simulação. Isso não explica causalmente os34s; não há SLA numérico aprovado. Resultado de desempenho real continua não comprovado, e a próxima validação deve observar a variabilidade documentada.

Corpus imutável:28 casos sintéticos, seed42, três aquecimentos,100 iterações/**2800 amostras**, SHA256 `1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c`. Mesmo `medir_extracao.medir(100)`, relógio monotônico e preparação separada, sem rede/espera artificial. As contraprovas não foram inseridas no corpus comparativo para mudar seu hash.

| Custo em µs | Antes p50 / p95 / máximo | Fechamento p50 / p95 / máximo |
|---|---|---|
| Extração |217,369 /14705,565 /37970,918 |**185,197 /10812,816 /13782,966** |
| Extração+avaliação |238,568 /14729,083 /38020,112 |**205,247 /10849,022 /13811,465** |
| Só avaliação,2500 ofertas válidas |20,898 /37,095 /377,656 |19,899 /30,600 /98,998 |
| Preparo snapshot,100 amostras |15,297 /26,996 /259,661 |15,500 /31,500 /268,496 |

Janela/vazão do corpus **3,949493s/708,95 → 2,793231s/1002,42 mensagens/s**. Redução local observada de~26,3% no p95 conjunto, sem garantia causal de produção; ainda custa mais que o extrator simples da base e que a primeira implementação de~5,5ms p95. O teste específico confirma derivado de cada linha calculado uma vez; estrutura transitória proporcional à entrada, não persistida nem enviada remotamente.

Fechamento incluiu `medir_limites()`:10 regras,50 termos/lista,100 caracteres/termo,20 avaliações por entrada, sem reextração. Preparo único **116813,279µs**, curta **1512,923/1558,073/1600,973µs**, longa **2652,554/2743,453/2950,449µs**, adversarial **1509,223/1557,273/1644,272µs**. Custo de refresh não é custo por mensagem.

Comando equivalente completo executado:

```text
python -B -c "import asyncio,json,medir_extracao as m; r=asyncio.run(m.medir(100)); r['limites_regras']=m.medir_limites(); r.pop('exemplos'); r.pop('extracao_por_caso'); print(json.dumps(r,ensure_ascii=False,indent=2))"
```

Controle adicional separado, três aquecimentos: texto da forma `Notebook simulado live 00000000\nR$ 299,90\nhttps://oferta.invalid/live/0`,71 caracteres,1000 extrações: p50/p95/máx **161,319/288,835/568,868µs**. Não inclui SQLite/rede/mídia e não resolve a causa da simulação lenta. Controle de escala sintético idêntico ao descrito na primeira retomada (`Notebook Dell\n` + frase `Detalhes produto capacidade variante. ` repetida500/1000/2000 vezes + preço),100 extrações por tamanho:19028/38028/76028 caracteres, p50 **11187,836/21981,705/44237,514µs**, p95 **14436,737/23219,210/46230,247µs**, máximos **18006,241/24766,740/69000,521µs**. Crescimento aproximadamente proporcional nessa amostra, não prova universal nem orçamento garantido.

#### Estado de saída e continuidade

**`em_validacao`**, aprovação v1 mantida. Achados e resíduos concretos corrigidos/testados na implementação; as matrizes reprovadas da seção16 não foram reescritas como aceite pelo implementador. Sem desvio material ou pergunta bloqueante, nova dependência, migração de dados reais ou reprocessamento compensatório.

Próximo comando: `/sdd-validar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`. Pendentes: validação final da entrega e observação da variabilidade/custo local; heurísticas/corpus sintético sem cobertura universal, Node20/browser real/produção/Supabase/Telegram/VPS não comprovados. Preservar decisões/hash/inbox e ordem schema→bot/backend→UI/rollback já documentados. Sem staging/commit/push/deploy/SQL remoto, etapa3, identidade nova ou imagens.

### Retomada autorizada — 2026-11-03

Nova invocação explícita de `sdd-implementar` retoma **VAL-ET2-001 a 003**, na versão 1 já aprovada. Raiz, runtime global, leitura integral de `_comum.md`/`implementar.md`/PRD e instruções, branch `main` e base `7c327d203b053eb8325c7c2efb9f1dc9d5d7327a` reconfirmados. Todo o diff anterior e os testes negativos da validação são preexistentes e serão preservados; não há mudança material de requisito ou nova autorização remota.

Roteiro desta retomada: **R01 — reprodução e baseline (concluído)**; **R02 — correções e controles cruzados (concluído)**; **R03 — suíte/medições/revisão/encaminhamento (concluído na implementação)**. Nenhuma expectativa das contraprovas foi alterada para obter verde. O histórico de reprovação da seção 16 permanece preservado; conclusão SDD exige nova validação após as correções.

#### Correções e alcance desta retomada

Somente `bot/src/extractor.py` recebeu alteração funcional nesta retomada; acrescentado `bot/tests/test_correcao_etapa2.py` com **17 testes** (16 síncronos e um assíncrono de integração), além de documentação em `README.md` e neste PRD. O restante do diff preexistente, inclusive `test_validacao_etapa2.py`, foi preservado.

| Achado | Correção implementada e controles |
|---|---|
| VAL-ET2-001 | `_descricao_linha` remove trechos monetários/serviços reconhecidos sem cortar toda a cauda. Condição/modelo após preço ou frete e separadores `;`, hífen/travessão permanecem descritivos. Canonicalização do serviço gratuito antes do split evita perder `USADO` em `Frete – grátis USADO`. URLs/cupons/rodapés não passam a satisfazer filtros. |
| VAL-ET2-002 | Frete com `de`/`por`, pontuação e contexto invertido não é preço atual/anterior. Gratuidade de envio/entrega/frete com `:`, travessão ou `é` é excluída antes de inferir zero do produto. Jogo efetivamente grátis continua zero mesmo com frete pago. Parcela pontuada (`10x de:`) não vira anterior; continua sem derivar total. |
| VAL-ET2-003 | Grupo de preço muda com evidência de objeto independente, não qualquer linha alfabética. Rótulos de especificação e memória apenas quantificada são continuidade; marca/modelo adicional ou outro objeto, inclusive com marca antes (`Logitech Headset`), dão evidência de produto separado. Memória Kingston Fury com preço na linha seguinte é múltiplo, não preço do notebook. Finais conflitantes continuam ambíguos. |

São heurísticas locais para os formatos cobertos, **não novo algoritmo de identidade/dedup nem detector universal de ofertas**. Nenhum contrato público, migração, dependência, hash histórico, decisão antiga ou regra de negócio foi alterado. A correção adjacente de parcela pontuada é localizada no mesmo classificador semântico e preserva RF-002/CA-004; não amplia escopo para cálculo de parcelas.

#### Verificações da retomada — comandos e resultados

Python principal: **3.12.3 / WSL2 Linux 6.6.87.2, glibc 2.39**, ambiente fixado existente. Comandos a partir de `bot/`, prefixados por `wsl --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`. Suíte, simulação e benchmark executados sequencialmente no fechamento; host Windows e volume `/mnt/c` não isolados. Nenhuma instalação/atualização de dependência.

| Comando/procedimento | Resultado / limite |
|---|---|
| `python -B -m unittest tests.test_validacao_etapa2 -v` antes de editar | Cinco falhas e um controle aprovado reproduzidos; mesmas expectativas preservadas. |
| Mesmo comando no fechamento | **6/6 passaram, 0,052s**, sem skips. |
| `python -B -m unittest tests.test_correcao_etapa2 tests.test_validacao_etapa2 tests.test_decisoes_etapa2 tests.test_filtros_etapa2 tests.test_extracao -q` | **83/83 passaram, 1,242s**, incluindo três mensagens pela inbox/pipeline e controles de hash/whitelist/CLI. |
| Suíte completa via `unittest.defaultTestLoader.discover('tests')` / `TextTestRunner(verbosity=0)` com saída em memória, sem filtrar testes | **212 executados, 211 passaram e 1 falhou, 116,799s**, zero erros/skips. `test_reconexao_por_rpc_dispara_historico_com_logica_conectada`: mock aguardado zero vezes quando o teste esperava uma; não é falha de extração. Não foi ignorada nem convertida para skip. |
| `python -B -m unittest tests.test_recuperacao.TestRecuperacao.test_reconexao_por_rpc_dispara_historico_com_logica_conectada -v` sem modificar código/asserts | **1 passou, 0,139s**. Teste depende de uma espera de 25ms após um evento; sensibilidade temporal observada, causa exata não comprovada. |
| Repetição completa com o mesmo loader/runner, sem alterações entre execuções | **212/212 passaram, 89,851s, zero falhas/erros/skips**, saída 0. Warnings de tarefas asyncio lentas permaneceram visíveis. Não prova resolução causal da intermitência anterior. |
| `python -m pip check` | **No broken requirements found**, saída 0. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` | Saída 0, SSD Kingston NV2 - 1 TB - NVMe, 299,90/399,90, `AbC123`, URL/query/caixa preservadas, aceite regra 1. Os testes offline também cobrem rejeição/configuração/falha sem credenciais. |
| Revisão independente somente leitura, três ciclos após correções | Primeiros ciclos encontraram variações de separadores/frete/memória/marca; corrigidas com regressões. Último ciclo: **22 testes síncronos** (seis originais +16 novos) e **12 reproduções adicionais** passaram, Python 3.14.4/Windows, `-B`, socket bloqueado. Nenhum impeditivo confirmado no recorte; não é aprovação integral SDD. |
| `git diff --check`, leitura de fontes/testes novos e diff | Sem erro de whitespace; avisos LF/CRLF do checkout Windows. Sem segredos, temporários de produção ou nova chamada de rede no extrator. |
| `git diff --exit-code --` nos arquivos protegidos | Diff vazio para `dedup.py`, `main.py`, recuperação/sinais/mídia, legado, requirements, unit, locks npm e auth central/rotas gerais. Estado operacional e decisões reais não foram abertos nem migrados. |
| API/UI/lint/tipos/build/SQL | **Não reexecutados nesta retomada**, pois não houve alteração nessas camadas; os resultados anteriores (40 API, 7 UI, lint/tipos/build e SQL local aprovados) permanecem identificados na seção 16. Não alegar teste atual de produção/Node20/browser/Supabase. |

Houve execuções intermediárias da suíte e do teste de oferta-antes-da-foto registradas na sessão, mas os números finais verificáveis acima são a referência de fechamento. Nenhuma assertion ou watchdog foi aumentado. As intermitências de 3s anteriormente documentadas e a de reconexão continuam observações para a próxima validação, sem diagnóstico causal fabricado.

#### Medições afetadas da retomada

Baseline cronológico da retomada, antes das correções: mesma simulação da seção 11, **29,324987s / 4,433080 ofertas/s**, live p50/p95/máx **6276,014/15119,073/15482,770ms**, histórico **27661,869/29145,459/29291,042ms**, 130 ofertas salvas e workers 4/1. Corpus imutável 28 casos/2800 amostras: extração **156,397/5555,105/6818,584µs** e conjunto extração+avaliação **176,397/5588,105/6845,883µs**, preparo **16/24,3/283,995µs**, 1697,57 mensagens/s. Não confundir com a base antiga selada de 2026-10-23.

Fechamento, comando exato de simulação da seção 11 (`python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1`):

- **130 recebidas/aprovadas/produtos**, zero descartes/duplicatas/falhas; **4,929831s / 26,370071 ofertas/s**. Live p50/p95/máx **436,653/496,110/506,935ms**; histórico **3229,926/4748,367/4893,613ms**. Heartbeat máximo **2,246ms**.
- Workers máximos 4/1, filas inicial/pico/final live **0/11/0**, histórico **0/100/0**, mídia **0/113/113**; 17 mídias prontas, 113 pendentes. Dois produtores, página máxima100, zero task por mensagem; ambas as origens progrediram antes do fim da outra. Janela não inclui setup/shutdown nem espera a mídia drenar.
- Hashes live `606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb` e histórico `27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805` inalterados; cinco operações de 20ms/oferta e mídia 200ms. **Não atribuir a melhora observada ao extrator**: é CPU mais caro, host/filesystem variáveis, sem isolamento causal nem SLA.

Corpus imutável medido com `asyncio.run(medir_extracao.medir(100))` e `medir_limites()`, equivalente a `python -B -m medir_extracao --iteracoes 100 --limites` (omitindo só a impressão dos exemplos): seed42, três aquecimentos, **2800 amostras**, SHA256 `1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c`.

| Custo final (µs) | p50 / p95 / máximo |
|---|---|
| Extração | **216,349 / 14595,031 / 40089,688** |
| Extração + avaliação | **237,795 / 14616,426 / 40152,473** |
| Só avaliação (2500 ofertas consideradas válidas) | 20,995 / 39,190 / 91,178 |
| Preparo snapshot (100 amostras) | 15,501 / 20,101 / 353,610 |
| Texto longo, extração | 17983,523 / 21147,260 / 40089,688 |
| Adversarial, extração | 14561,646 / 16300,492 / 24543,665 |

Janela **3,968088s / 705,63 mensagens/s**. Há **piora CPU expressiva**, especialmente nas entradas longas, em relação ao baseline da retomada (~2,62 vezes no p95 conjunto). Investigação local via `cProfile` sobre100 extrações da fixture `longo`: total1,863s, `_descricao_linha`1,474s cumulativo, substituições regex0,871s e normalização0,434s. O helper é usado tanto para contexto de preço como para título/conteúdo, acrescentando scans/normalização; não se trata de ganho ou custo de rede. Possível reutilização local dos derivados é melhoria futura de desempenho, não aplicada sem novo ciclo de verificação.

Controle de escala separado, **sintético**, sem mudar o corpus: `Notebook Dell\n` + `Detalhes produto capacidade variante. ` repetido500/1000/2000 vezes + `\nPor R$ 299,90`, três aquecimentos e100 extrações por tamanho. 19028/38028/76028 caracteres: p50 **16744,105/32869,504/65408,535µs**, p95 **20494,128/36572,115/75981,496µs**, máximos **38661,245/51509,917/107028,052µs**. Crescimento aproximadamente proporcional nessa amostra, sem prova de limite universal ou SLA. Primeira tentativa do comando efêmero teve erro de quoting/SyntaxError do shell; execução por stdin corrigida, sem arquivo/código de produção alterado. O teste adversarial de espaços também permanece na suíte; o colapso de espaços antes dos padrões evita o backtracking observado durante a primeira implementação do helper.

Regras no limite (10 regras,50 termos/lista,100 caracteres/termo,20 avaliações por entrada, sem reextração): preparo único **117605,164µs**; curta **1605,839/2000,048/2038,250µs**, longa **2750,516/2797,169/2837,769µs**, adversarial **1547,086/1682,439/1747,240µs**. Não houve espera artificial/rede no trecho de lógica pura.

#### Encaminhamento e limitações atuais

Na implementação, as três causas e os resíduos concretos reproduzidos foram corrigidos e testados. As matrizes da seção16 são o **resultado histórico reprovado**, não foram reescritas como aceite pelo implementador. Estado de saída **`em_validacao`**, versão1/aprovação preservadas. Próximo comando: `/sdd-validar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`.

Pendentes: nova validação independente da entrega; observar intermitências temporais sem relaxar testes e considerar custo CPU adicional ao avaliar desempenho. Não há pergunta material bloqueante nem mudança de requisito. Persistem limitações de corpus sintético/heurísticas, Node20 não exercitado, sem browser real/produção/Supabase/Telegram/VPS. Nenhum staging/commit/push/deploy, SQL remoto, imagem/identidade nova ou etapa3; todo trabalho anterior preservado.

### Alterações realizadas

Implementação iniciada em 2026-10-23 pela invocação explícita de `sdd-implementar` para este PRD, aprovando a versão 1. Runtime global e prompts comuns/implementar relidos integralmente; base `main`/`7c327d203b053eb8325c7c2efb9f1dc9d5d7327a` e único worktree confirmados. Os três prompts e este PRD eram não rastreados preexistentes e serão preservados. Sem autorização para publicação Git, deploy, conta Telegram ou SQL remoto.

Registro histórico da implementação de 2026-10-23: baseline → extração/contexto → decisão/regras e CRUD/UI → verificações/medições/revisão. Na ocasião T01–T08 foram declarados verificados e encaminhados à validação. **A validação de 2026-11-03 reabriu T02/T04/T07/T08**, com contraprovas e resultado atual na seção 16; evidências históricas abaixo não substituem esse resultado.

Arquivos principais:

- `bot/src/extractor.py`, `normalizacao.py`, `dinheiro.py`, `adaptadores.py`: extração genérica conservadora, descrição separada, centavos, categorias e extensão vazia.
- `bot/src/filters.py`, `cache.py`, `avaliacao.py`: snapshot preparado, modos, dois escopos de veto, frases e resultados detalhados com códigos/IDs.
- `bot/src/telegram.py`, `modelos.py`, `estado.py`: contexto raw/UTF-16/botões, persistência aditiva v5 e diagnóstico separado; versões 0–4 continuam migráveis.
- `bot/src/pipeline.py`, `repository.py`: decisão/hash persistidos soberanos, diagnóstico antes da rede e projeção explícita; sem mudar dedup/janela/reconciliação/mídia.
- `bot/previa.py`, `medir_extracao.py`, `exemplos/etapa02/`, `tests/fixtures/extracao_sintetica.json` e quatro módulos novos de teste: CLI, exemplos/corpus sintéticos, comparações e regressões. As três suítes antigas alteradas mantêm as proteções de coleta/entidade com expectativas da nova semântica.
- `backend/src/{services,models,controllers,routes}/filtro.*.js`, `backend/tests/`, `backend/package.json`: validação, merge parcial e factories para testes injetados; camadas MVC/auth preservadas. Backend tem 40 testes novos.
- `frontend/app/filtros/page.tsx`, `lib/{types,filtro-form}.ts`, `components/ProdutoCard.tsx`, `tests/filtros.test.cjs`, `package.json`: tipo/modo/ajuda, edição pausada e zero; 7 testes de UI/renderização com dependências falsas, sem browser real.
- `supabase/schema.sql`: bloco marcado `ETAPA 2 FILTROS` aditivo/idempotente; `README.md`/`CLAUDE.md`: semântica, operação e contratos sincronizados.

### Decisões técnicas menores

- Produto congelado permanece no JSON antigo de `decisao`; contexto e diagnóstico ficam em colunas locais separadas, evitando novo formato incompatível de decisão. Pipeline passa o hash congelado pelo campo remoto já existente `dedup_hash`; repositório só calcula fallback quando ausente, sem alterar `dedup.py` ou a janela.
- Mensagens novas usam `.message` bruto e spans/contexto JSON; `.text` só atende entrada legada sem bruto. Asserções antigas de markup foram substituídas por preservação do bruto e entidades, equivalência live/raw e cupom contextual; código isolado não é mais cupom, mudança exigida pelo PRD.
- A fronteira Telethon usa `utils.get_inner_text` em lote e mapa de fronteiras UTF-16 válidas. URLs visíveis são excluídas da descrição; rótulo TextUrl pode ser o próprio nome do produto e não é apagado indiscriminadamente. Regressão específica acrescentada nessa revisão de integração.
- PostgreSQL embarcado **PGlite 0.5.11 / PostgreSQL 18.6 WASM** foi instalado somente em `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql` para testar SQL localmente, pois Docker engine/psql não estavam disponíveis. O mesmo runner SQL aceita psql local protegido ou módulo PGlite absoluto. Não é dependência da aplicação nem acesso remoto.
- Normalização usa Unicode `lower`/`toLowerCase`, NFD e remoção de marcas/colapso de espaços, preservando alfabetos não ASCII. Não se usou casefold Python exclusivo que faria API aceitar duplicatas depois rejeitadas pelo cache. Termo só de marcas é vazio/inválido nas camadas. Arrays NULL legados podem ser editados/pausados sem defaults de PUT regravarem omitidos.
- Revisão de extração corrigiu descrição TextUrl, produto/modelo/condição monoespaçados, preço no início com produto na cauda e delimitadores externos comprovados. Backticks sozinhos não autorizam cupom, mas também não apagam o nome de produto nem a condição `USADO`. Chamadas genéricas usam tokens, sem regex de repetições aninhadas.
- Resultado terminal escolhe o motivo principal (múltiplas ofertas/ambiguidade/falta de evidência), sem deixar aviso secundário de preço/cupom mascarar a causa. Todos os avisos continuam no diagnóstico de extração.
- Medição de listas no limite encontrou scans regex desnecessários. A avaliação agora reutiliza correspondências por termo e faz pré-teste literal em C sobre texto já normalizado antes de confirmar limites com regex. Não altera a semântica; preparação/compilação continua no snapshot, não por mensagem.

### Verificações direcionadas

Resultados iniciais desta implementação, sem substituir a verificação final:

| Comando/procedimento | Resultado real | Limite |
|---|---|---|
| Em `bot/`, Python 3.12.3/WSL existente: `python -B -m unittest discover -s tests -v` antes de alterar produção | **118 testes passaram, zero skips; 88,828s** | SDKs instalados com transportes falsos, SQLite e processos locais; warnings preexistentes GoTrue/asyncio lento não suprimidos. |
| No mesmo ambiente, `python -m pip check` | Sucesso | Nenhuma dependência Python instalada ou atualizada. |
| Simulação baseline, comando exato da seção 11 | 130 produtos/130 aprovações, zero descartes/duplicatas/falhas; 4,640s e 28,014 ofertas/s | p50/p95/máx live 295,992/365,432/390,484ms; histórico 2987,689/4411,811/4611,660ms. Workers máx 4/1, heartbeat máx 2,145ms; fila mídia final 114 (16 prontas). Progresso das duas origens antes do fim da outra. Não comprova produção. |
| Dataset baseline | Live SHA256 `606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb`; histórico `27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805` | Seed 42; cinco operações de banco de 20ms; mídia 200ms; workers 4/1; filas live/histórico pico 9/100, final 0/0; mídia pico/final 114. |
| `node --version` | v24.11.1 | Projeto documenta Node 20; diferenças de ambiente serão registradas. |
| Busca local WSL por `psql/initdb/pg_ctl`; `docker version --format "{{.Server.Version}}"` | PostgreSQL não encontrado no PATH; Docker CLI existe, mas engine Linux ausente (pipe indisponível) | Ainda não há validação SQL executável; não se usa banco remoto como atalho. |
| `python -B -m unittest tests.test_filtros_etapa2 -v` no WSL | 12 testes novos passaram, 0,016s | Validação de snapshot, modos, escopos, frases e centavos; integração completa ainda pendente. |
| `python -B -m unittest tests.test_decisoes_etapa2 -v` no WSL | 12 testes novos passaram, 0,895s | Diagnóstico antes da rede, projeção estrita, commit ambíguo/hash soberano, CLI offline e configuração inválida. |
| `python -B -m unittest tests.test_pipeline tests.test_repository tests.test_checkpoints tests.test_filtros_etapa2 tests.test_decisoes_etapa2 -q` no WSL | **70 testes passaram, 11,993s** | Conjunto dirigido, não substitui suíte final/SDK/POSIX. |
| Frente de contexto: `python -B -m unittest tests.test_contexto tests.test_sdk tests.test_coleta_retoma tests.test_recuperacao -v` no WSL | 42 testes passaram sem skips, 57,260s | Antes das duas melhorias adicionais de integração descritas acima. Houve timeout inicial e caso temporal de FloodWait que passou isolado e na repetição conjunta, sem relaxar assertion; suíte final ainda deve reconferir. |

### Verificações finais executadas

Comandos Python em `bot/`, com `/mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python` no WSL; scripts npm em seus diretórios. Ambiente: Python 3.12.3, Telethon 1.36.0, Supabase 2.9.1, HTTPX 0.27.2, Storage3 0.8.2, dotenv 1.0.1; Node 24.11.1/Windows. Nenhum pin/lock de produção atualizado.

| Comando/procedimento | Resultado real | Limite |
|---|---|---|
| `python -B -m unittest discover -s tests -v` após integração | 188 testes passaram, sem skips, 62,501s | Antes de um caso adicional de preço no início e da otimização literal. |
| `python -B -m unittest discover -s tests -q` com todos os casos novos | 189 passaram, sem skips, 97,554s | Execução intermediária; assertions não relaxadas. |
| Mesmo comando após otimização da avaliação | **189 passaram, zero skips, 59,484s** | SDKs/HTTP/Telegram/Storage falsos e SQLite/processos POSIX reais locais; inclui sinais e retenção. |
| Repetição após ajustes finais de título longo/camiseta | 189 executados; **1 erro de timeout**, 79,425s | `test_upload_permanente_compensa_antes_de_terminalizar_sem_loop`: watchdog de 3s excedido. Não foi ignorado nem teve timeout/assertion alterados. |
| Teste anterior isolado, mesmo código, logging INFO | Passou, 0,388s | Logs comprovaram oferta salva, uma tentativa de upload permanente, compensação e estado terminal correto; nenhum loop ou fatal observado nessa execução. Não determina a causa exata do timeout anterior. |
| **Suíte completa final**, sem verificações concorrentes | **189 passaram, zero skips, 89,942s** | Mantidas todas as assertions e o timeout original. Há intermitência temporal residual a observar na validação; não se declara causa ambiental comprovada só pela repetição aprovada. |
| `npm test` em `backend/` final | **40 passaram**, zero falhas/skips, 563,868ms | Serviço/model/controller/router com fakes; não comprova Supabase/Auth reais. |
| `npm test` em `frontend/` final | **7 passaram**, zero falhas/skips, 1177,734ms | TSX real transpilado/renderizado e eventos exercitados com hooks/API/Auth falsos; não é E2E em browser. |
| `npm run lint` em `frontend/` | Sucesso, sem warnings/erros ESLint | Configuração existente. |
| `npx --no-install tsc --noEmit --incremental false` | Sucesso | TypeScript existente, sem instalar ferramenta nova. |
| `npm run build` por CLI Next 14.2.5 com variáveis fictícias explícitas | Sucesso: compilação, lint/tipos e seis páginas geradas; `/filtros` 4,26kB, first load 160kB | Não leu `.env` privado (só existe `.env.example` em frontend); URL `https://supabase.invalid`, chave `fake-anon-key`, API localhost, telemetry desativada. Não iniciou serviço real. |
| Checagem `node --check` recursiva dos JS/MJS em `backend/src` e `backend/tests` | Sucesso | Não há script backend build/lint/typecheck configurado; não se inventou aprovação desses comandos. |
| `npm run test:sql` / mesmo runner com `DEALBOT_TEST_PGLITE_MODULE` absoluto | **Sucesso em PostgreSQL 18.6/PGlite 0.5.11** | Aplicação dupla, IDs/dados/pausado/teto/timestamp preservados, defaults, enums/consistência de global, NULLs e preflight atômico; instância em memória. Não é validação do Supabase/RLS/produção. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` | Saída 0: SSD Kingston NV2 - 1 TB - NVMe, 299,90/399,90, `AbC123`, link comercial com query/caixa preservada, `aceita_por_regra`/1 | Exemplo sintético. Testes também cobrem saídas 0-rejeição, 2-configuração e 1-falha técnica, com rede proibida. |
| Revisão de diff/contratos, `git diff --check` | Sem erro de whitespace; avisos LF/CRLF do checkout Windows | Nenhum staging/commit/push/deploy. Conferência de arquivos novos/ausência de segredos e preservação reconferida no fechamento. |
| Comparação Git dos arquivos protegidos | Diff vazio para legado, dedup, pins/locks, sinais/recuperação/mídia, unit e exemplos de ambiente | Nenhuma alteração de algoritmo/janela/imagens/auth ou dependência de produção por conveniência. |

Sintaxe Python e contrato público também são exercitados pelos imports da suíte. Não há lint/mypy Python configurado; não se declara cobertura percentual ou `mypy --strict` executado. Warnings GoTrue/asyncio lento observados, sem supressão. Limitação Node 24 em vez do Node 20 documentado: compatibilidade em Node 20/ambiente de produção não foi executada nesta sessão.

Comando SQL equivalente usado pela sessão principal, sem depender de variável privada:

```text
# Em backend/, definir somente esta variável e executar npm run test:sql:
DEALBOT_TEST_PGLITE_MODULE=C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql/node_modules/@electric-sql/pglite/dist/index.js
```

### Antes/depois dos casos concretos — somente fixtures sintéticas

Baseline de resultados e CPU do corpus foi reconstruído **em memória** com `git show 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a:bot/src/{extractor,filters}.py`, sem checkout/reset nem cópia de lógica antiga em produção. Runner/corpus novos são os mesmos nas duas avaliações. Helper temporário: `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-baseline.py`; foi executado no WSL depois das alterações, carregando exclusivamente as funções seladas do commit base. Isso não deve ser apresentado como uma medição cronologicamente anterior às edições; a simulação de pipeline, ao contrário, foi executada antes e depois.

| Fixture/caso | Base | Implementação atual |
|---|---|---|
| Chamada + SSD na linha seguinte | Título `OFERTA IMPERDÍVEL`; SSD não passa se só o título for avaliado | Título `SSD Kingston NV2 1 TB`; descrição satisfaz SSD + Kingston. |
| `SSD Kingston - NV2 1 TB - NVMe` | Título cortado em `SSD Kingston` | Mantém modelo, capacidade e NVMe após hífens. |
| `SSD R$ 99` | Descartado por comprimento | Oferta curta com preço 99,00. |
| De 399,90 por 299,90 | 299,90 / 399,90 | Mesmo resultado, com papéis explícitos. |
| Por 299,90 / frete 15,00 | Atual 15,00 / anterior 299,90 | Atual 299,90 / anterior nulo. |
| 10x 99,90 / à vista 899,00 | Atual 99,90 / anterior 899,00 | Atual 899,00 / anterior nulo; só parcelas não derivam total. |
| Desconto 50 acima de 300 | Produto/preço 50,00 e anterior 300,00 fictícios | Sem produto isolado; com descrição/link independente, preço continua desconhecido. |
| `R$ 1,234` | Valor 1,234 com precisão indevida | Preço nulo e `formato_preco_ambiguo`. |
| Dois produtos de 299,90 e 149,90 | Escolhe menor 149,90 | Nenhum card, `multiplas_ofertas`. |
| Grupo antes do link comercial | Título de divulgação e link t.me | Título descritivo e URL comercial com caminho/query preservados. |
| Divulgação genérica com grupo | Vira produto sem preço | `sem_evidencia_de_oferta`. |
| `Cupom: AbC123` / código isolado | Uppercase `ABC123` nos dois | Preserva `AbC123` contextual; isolado nulo e explicado. |
| Cadeira gamer / headset gamer / jogo PS5 | Cadeira erroneamente games; demais classificações variáveis pelo primeiro substring | Casa / eletronicos / games, com limites de palavras. |
| Link oculto/botão | Link ausente ou descarte | Candidato persistido e reutilizado sem RPC extra, inclusive depois de restart. |
| Anterior 199,90 / atual 299,90 | Inverte papéis e inventa desconto | Atual 299,90; anterior inconsistente omitido/explicado. |

### Medições locais — simulação de pipeline

Mesmo comando, seed/datasets e ambiente da seção 11; banco fake 20ms por cada uma de cinco operações, mídia total 200ms, 30 live a 50ms + 100 históricos, workers 4/1. As execuções medidas foram sequenciais, sem suíte/build concorrendo intencionalmente; host/filesystem WSL em `/mnt/c` não é laboratório isolado.

| Execução | Produtos / falhas | Duração / ofertas/s | Live p50 / p95 / máx (ms) | Histórico p50 / p95 / máx (ms) | Heartbeat máx (ms) |
|---|---|---|---|---|---|
| Antes, produção ainda intacta | 130 / 0 | 4,640s / 28,014 | 295,992 / 365,432 / 390,484 | 2987,689 / 4411,811 / 4611,660 | 2,145 |
| Depois, antes da otimização literal | 130 / 0 | 4,389s / 29,621 | 187,992 / 268,199 / 301,205 | 2806,977 / 4195,745 / 4360,513 | 4,619 |
| Depois da otimização literal, execução com cauda ruim | 130 / 0 | 9,142s / 14,220 | 229,506 / 308,724 / 316,931 | 3014,252 / 8268,387 / 9022,353 | 13,162 |
| **Depois final**, após a suíte final do código de fechamento | **130 / 0** | **4,749s / 27,377** | **179,534 / 284,815 / 289,220** | **3006,015 / 4570,910 / 4715,236** | **2,041** |

Todas tiveram 130 aprovações, zero descartes/duplicatas/falhas, workers máximos 4/1 e progresso de cada origem antes do fim da outra. Filas live/histórico inicial/final 0/0; picos antes 9/100 e depois 7/100. Mídia final antes/primeira intermediária 114 (16 prontas), execução com cauda ruim 108 (22 prontas, 107 pendentes e uma em processamento), fechamento 113 (17 prontas, 112 pendentes e uma em processamento); picos iguais aos finais. Medição termina antes de shutdown/drenagem de fotos. Hashes dos dois datasets coincidiram nas quatro execuções, registrados na tabela inicial acima.

**Não ocultar a piora/variabilidade:** uma repetição teve aproximadamente metade da vazão inicial e maior cauda histórica; o fechamento voltou próximo da referência (vazão ligeiramente menor e cauda histórica ligeiramente maior). A otimização literal não é exercitada nesse dataset com filtros vazios e a extração típica custa frações de milissegundo; não há evidência para atribuir causalidade ao código ou prometer ganho a partir desses números. Variação do host/filesystem e instrumentação não foram isoladas. Invariantes funcionais/limites passaram, mas desempenho real permanece não validado; p95 live local final de 285ms não é SLA de VPS/Telegram/frontend. Histórico do benchmark entra direto na inbox; cobertura raw/RPC é comprovada por testes próprios.

### Medições locais — extração/filtragem pura e regras no limite

`bot/medir_extracao.py` usa o corpus `tests/fixtures/extracao_sintetica.json`: **28 casos sintéticos**, seed 42, SHA256 `1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c`, três aquecimentos e 100 iterações (2800 amostras). Inclui textos curtos, links/contexto, preços e duas entradas longas/adversariais. Python 3.12.3, Linux 6.6.87.2 WSL2/glibc 2.39, mesmo checkout em `/mnt/c`, sem I/O/rede/espera artificial no trecho medido.

| Custo (µs) | Base selada p50 / p95 / máx | Implementação final p50 / p95 / máx |
|---|---|---|
| Extração | 16,897 / 485,710 / 778,856 | 153,494 / 5505,226 / 10282,168 |
| Extração + avaliação | 21,096 / 490,009 / 1623,800 | **172,495 / 5545,023 / 10313,767** |
| Só avaliação de ofertas consideradas válidas | 3,400 / 6,199 / 1596,305 | 19,800 / 30,199 / 90,997 |
| Preparação do snapshot | Não separada no legado | 15,699 / 22,999 / 269,287 |

Vazão do corpus: 17593,83 → 1700,19 mensagens/s; janela 0,159147 → 1,646876s. Não é uma alegação de otimização: a lógica contextual custa mais que min/max/primeira linha. As populações de ofertas válidas diferem (2600 antes/2500 depois) por correções esperadas; comparar essa submétrica com cautela. As entradas longas dominam a cauda: extração p95 de 5816,212µs no texto de 16912 caracteres descritivos e 6796,461µs no adversarial; exemplo comum da chamada p95 211,590µs. Código foi inspecionado para evitar regex aninhada, normalização duplicada do conteúdo e recompilação de regras por mensagem; não há rede ou espera nova. Não extrapolar a VPS nem esconder o custo adicional. Medições intermediárias variaram (conjunto p95 6,103–6,388ms e máximo até 17,565ms); não se inferem limites garantidos do fechamento menor.

Com `--limites`, carga adicional **sem comparativo legado**: 10 interesses, cada lista com 50 termos de 100 caracteres, termos distintos entre regras, 20 avaliações por entrada, sem reextração. Preparação uma vez: 115524,539µs. Avaliação p50/p95/máx: curta 1528,826/1598,875/1619,475µs; longa 2683,896/2936,603/3116,273µs; adversarial 1515,343/1582,032/1602,129µs. Uma medição intermediária sem o pré-teste literal expôs p95 de **467556,45µs** na longa; isso motivou a correção, não foi omitido nem tratado como aprovado. A otimização reduz scans repetidos, sem alterar match/limites/frases. Preparação grande pode custar ~116ms por refresh no cenário artificial; não é custo por oferta nem promessa de latência constante sob configuração arbitrária.

Comando de corpus equivalente executado na sessão principal: importar `medir_extracao`, executar `asyncio.run(medir(100))` e `medir_limites()`, omitindo apenas a impressão dos exemplos/linhas intermediárias do relatório. A CLI reproduzível é `python -m medir_extracao --iteracoes 100 --limites`.

### Desvios, bloqueios e limitações

- Nenhum desvio material de requisito/arquitetura identificado. SQL foi executado exclusivamente em instância local temporária; nenhuma migração do usuário/remota foi aplicada. SQLite v5 só foi exercitado em bancos de teste, não no estado operacional do usuário.
- Agentes de extração/API e tentativa de revisão final foram interrompidos por `subscription_sharing_usage_limit_exceeded`. Arquivos parciais foram preservados, inspecionados e completados pela sessão principal após o usuário solicitar continuação. Não se declara revisão independente final aprovada. A exploração independente inicial e a fatia Telegram/SQLite retornaram, mas não substituem o próximo `sdd-validar`.
- Não há corpus real suficiente: nenhum adaptador específico, sinônimo amplo ou identidade nova. Detector de múltiplas ofertas/heurísticas não cobre todo formato; um post independente ambíguo detectado é terminal, não desmembrado. Formatos monetários ambíguos e cupons sem evidência continuam nulos. Não se deriva parcelamento.
- Node 20, produção/Supabase/Telegram/VPS, browser real, migração remota e SLA continuam fora da evidência executada. A cauda/vazão da simulação variou e uma repetição piorou significativamente; resultados são locais, não aprovação de desempenho real. Timeout intermitente de 3s do teste de compensação não foi causalmente diagnosticado, apesar de logs isolados corretos e suíte final aprovada; observar na validação sem mascará-lo por mudança de assertion.
- Operações remotas/etapa 3, mudança de hash/janela/imagens/auth e publicação Git não foram iniciadas. Preservar diretório persistente na futura atualização, seguir schema → bot/backend → frontend e rollback limitado descrito neste PRD/README.

### Investigação dirigida do teste de rajada — 2026-11-05

O usuário autorizou investigar exclusivamente o teste de rajada, sem nova rodada da skill SDD, sem mexer em filtros ou aumentar timeouts. **Não é nova validação nem fechamento de VAL-ET2-005.** Estado continua `em_implementacao`; aprovação v1 e matrizes abaixo preservadas. Nenhuma alteração em produção/testes, dependências, SQLite `WAL`/`FULL` ou assertions. Nenhuma suíte completa, build, simulação, operação remota ou publicação nesta investigação.

**Resultado útil:** capturado timeout com progresso real, sem fatalidade dos workers, durante esperas do executor SQLite. Observada também espera de disco no kernel em outra amostra. Não foi demonstrado filtro travado, deadlock ou perda de notificação. Ainda não há causa raiz única comprovada para os episódios históricos ou patch funcional justificável.

#### Procedimento e evidências externas

Ambiente mantido: Python3.12.3/WSL2/venv existente em `/mnt/c`; inboxes descartáveis em `/tmp` ext4. Todas as execuções usaram o teste original `tests.test_pipeline.TestPipeline.test_rajada_concorrencia_justica_e_heartbeat`, seus dois workers de oferta/um de mídia,40 mensagens históricas/uma live, watchdogs originais de3s e modo debug. Capturas e JSONs ficaram exclusivamente em `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/`, prefixo `dealbot-rajada-`; sem dependência de produção.

1. **Uma execução original com cProfile**, comando em `bot/`: `python -B -m cProfile -o [temp]/dealbot-rajada-original-01.prof -m unittest tests.test_pipeline.TestPipeline.test_rajada_concorrencia_justica_e_heartbeat -v`. Passou em2,092s de runner. Serve como amostra, não prova de resolução.
2. **Contraste finito original/nativo/nativo/original**, subprocessos sequenciais com a mesma venv e cópias byte a byte de `src/*.py`, `tests/__init__.py`, `test_pipeline.py` e `test_repository.py` em diretório temporário ext4. SHA256s conferidos antes/depois; só as fontes copiadas mudam de local. Instrumentação externa em memória: hook síncrono de `executor.submit`, logs e fronteiras de `aguardar`; cProfile somente no thread principal. Não substitui o método original do teste nem o prazo. Fontes/venv do helper continuam em `/mnt/c`, host não isolado; **não é comparação completa de ambientes nem taxa estatística de flakiness**.
3. **Uma sonda original com perfil da thread SQLite** e amostragem de `/proc/self/task/[tid]/syscall`/`wchan`; passou em3,332s de runner, esperas live/histórico0,455931/2,144892s, sem amostra kernel acima do limiar20ms. Perfil não modifica a conexão SQLite.
4. Uma tentativa de combinar dois objetos cProfile concorrentes gerou `ValueError: Another profiling tool is already active` no preparo de cada um dos quatro subprocessos previstos. **Erro do helper, não regressão do produto:** nenhum corpo de teste/espera foi executado nessas quatro tentativas. Arquivos de evidência preservados, sem contá-las como aprovação/timeout ou skip. O helper passou a recusar a combinação; ensaio corrigido usa um único profiler por processo.
5. **Quatro amostras nativas pré-fixadas**, somente perfil da thread SQLite e monitor kernel, sem cProfile principal; todas passaram. Totais da sonda1,586900/1,564530/1,829888/1,542245s. Na terceira, capturou-se `fdatasync` do WAL aguardando o journal ext4 durante o preparo do teste.
6. **Último par previamente delimitado original/nativo**, somente cProfile principal e monitor kernel (sem perfil SQLite simultâneo): passou em ambos, totais3,318931/1,696970s, esperas live0,456689/0,252130s e histórico2,081512/1,051439s. Sem novas amostras kernel lentas. Encerradas as execuções: **12 corpos de teste executados,11 aprovações/um timeout,zero skips**, mais quatro tentativas inválidas de setup do helper. Nenhuma repetição completa até verde.

Comando-base das sondas, com prefixo WSL/venv registrado nas validações: `python -B [temp]/dealbot-rajada-sonda.py --bot [fontes] --saida [json-novo] [--perfil OU --perfil-sqlite] [--kernel]`. `dealbot-rajada-comparar.py` contém a ordem do primeiro contraste. Logs/JSONs/profiles persistem no diretório externo; cópias ext4 descartáveis foram removidas pelo próprio `TemporaryDirectory` após os subprocessos.

#### Captura do timeout: delimitação da espera

| Ordem / fontes | Resultado | Total da sonda(s) | Espera live(s) | Espera histórico10(s) | Máx fila / execução SQLite(ms) |
|---|---|---|---|---|---|
|1 / original9p |aprovado |6,411157 |0,626088 |2,830097 |159,421 /304,106 |
|2 / cópiaext4 |aprovado |4,068867 |0,383318 |1,786953 |128,242 /138,817 |
|3 / cópiaext4 |**timeout** |9,913905 |2,212796 |**3,096594** |747,764 /590,470 |
|4 / original9p |aprovado |5,639350 |0,440737 |2,070606 |2,472 /2362,058 |

Totais incluem preparo/teardown/sonda; os máximos são da execução inteira, **não necessariamente dentro do watchdog**. Portanto, não comparar diretamente total com3s nem concluir que uma operação isolada de2,362s causou o timeout. Perfis têm custo observacional e não substituem uma suíte normal.

No ensaio3 (`dealbot-rajada-par-3-nativo.json`), o erro ocorreu na **segunda** espera (`test_pipeline.py:303`, histórico10), não na primeira espera live100 (`:300`) da falha anterior. Reproduz a classe de atraso na rajada, **não a sequência histórica exata**. A live100 e a histórica1 estavam aprovadas. Inícios de trabalho registrados:100,1,2,3; a10 ainda não tinha sido selecionada na última leitura. Últimas leituras de2/3 eram não terminais, podendo estar desatualizadas no instante da captura — não são snapshot atômico do banco.

Durante a segunda espera, intervalo monotônico4,671716–7,768310s, operações do único executor SQLite ocuparam **3,029136s dos3,096594s**; soma de CPU da thread nessas operações **5,513ms** (inclui operações que cruzam as bordas da janela). Exemplos: `obter_oferta`452,067/0,351ms real/CPU; `decidir`312,487/0,277ms; `reservar_hash`590,470/0,257ms. **Baixa CPU não identifica sozinha disco, GIL ou desagendamento.** Essa separação mostra que o gargalo observado não foi cálculo de filtro e que a leitura de monitoramento `evento` também compete pelo executor serial.

Na exceção, `pipeline.fatal` não estava concluído; três tasks ainda ativas: oferta0 em `finalizar_oferta`→`_executar`/shield, oferta1 na espera fake de aparição e mídia0 esperando seu evento. Produtos fake já presentes:4. Não se inferiu perda de ofertas, deadlock ou worker morto; o deadline pode vencer enquanto o trabalho continua. Captura feita sem depender de nova consulta SQLite após o timeout.

O custo de stacks/debug também existe: cProfile do ensaio3 atribuiu3,120398s próprios a `posix.stat`; `linecache.checkcache`3,174251s cumulativos e extração de stacks3,548607s cumulativos. **São custos aninhados: não somar.** Mesmo copiando fontes do projeto para ext4, interpreter/venv/helper permanecem em9p; o contraste não elimina esse fator. Ter ocorrido timeout com fontes nativas impede explicar tudo apenas pelo local do checkout.

#### Evidência kernel: espera de confirmação do WAL

Em `dealbot-rajada-kernel-v2-nativo-03.json`, a terceira amostra nativa válida passou, mas uma operação `registrar` do **preparo**, anterior ao início dos workers/watchdogs, durou **130,526ms reais/2,282ms CPU**. Outra durou46,059/0,966ms. O monitor capturou13 amostras da thread SQLite com:

- syscall75 (`fdatasync`, Linuxx86_64);
- descritor apontando a `/tmp/tmpgvlo9ib8/estado/inbox.sqlite3-wal`;
- `wchan=jbd2_log_wait_commit`;
- frame em `EstadoLocal.registrar.<locals>.op`, linha176 (`with db`, saída transacional).

Na operação de130,526ms, amostras consecutivas observaram a espera entre30,010 e124,759ms de duração; as restantes corresponderam à operação de46,059ms. **Comprova espera de confirmação em disco/journal nessa amostra**, não aquisição de lock SQL nem cálculo do filtro. Não comprova saúde/causa do disco do host, e **não é captura do kernel do ensaio que falhou**: essa ligação causal continua ausente. Tempos internos de cProfile não substituem as observações kernel/monotônicas da operação inteira.

#### Encerramento desta investigação

- Diagnóstico avançou de “timeout sem estado” para progresso/worker/operação/fila/CPU e uma espera de WAL comprovada. Limitação restante: não capturado `fdatasync` no próprio episódio de timeout; os episódios antigos podem ter outras causas. **VAL-ET2-005 não está resolvido.**
- Não há patch de filtro/worker/cache/SQLite sustentado por estes dados. Não desativar debug, reduzir commits, trocar `FULL`, usar RAM no teste para fingir durabilidade ou aumentar3s só para aprovação.
- Próxima investigação, se autorizada, deve concentrar-se no armazenamento/ambiente WSL e capturar syscall/progresso no mesmo episódio lento; comparação de ambiente integralmente nativo precisa incluir interpreter/venv/helper, mantendo fontes e garantias iguais. A amostra kernel de preparo não basta para aprovar CA-025 ou responsabilizar exclusivamente o ambiente.
- Produção e todos os241 testes permaneceram intactos; revisão dos hashes da sonda confirmou os arquivos observados inalterados. Apenas este registro foi acrescentado ao PRD. Sem staging/commit/push, contas, dados reais, SQL remoto ou alteração de aprovação/escopo.

### Controle de armazenamento sem bot — 2026-11-05

Continuação explicitamente autorizada pelo usuário para distinguir armazenamento/WSL de lógica do pipeline. **Ensaio limitado concluído; não é nova validação SDD nem correção de VAL-ET2-005.** Nenhum filtro, worker, teste, prazo, configuração do host, dependência ou garantia SQLite alterado. Sem suíte completa, simulação, API/UI, rede ou recursos reais.

**Hipótese:** a confirmação durável pode apresentar caudas de latência no filesystem temporário mesmo sem código do bot. Ensaio pré-definido em ordem **SQLite/arquivo/arquivo/SQLite**,100 operações sequenciais por lote, payload8192bytes, um único escritor/conexão,400 confirmações no total. SQLite mínimo somente stdlib (`INSERT` e `commit` separados), sem imports do bot/asyncio/executor/cProfile; controle de arquivo somente `os.pwrite` e `os.fdatasync`. Arquivos/bancos novos e descartáveis em `/tmp`, não em RAM/9p; monitor da syscall da thread principal só amostra operações acima de20ms, a cada5ms. Não se compara equivalência exata de trabalho físico entre WAL e arquivo: o objetivo é constatar espera abaixo da aplicação em ambos.

Comando em `bot/`, com o prefixo WSL/venv existente: `python -B /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-disco-isolado.py`. Fonte e relatório completos exclusivamente no diretório externo aprovado, resultado `dealbot-disco-isolado-01.json`; não sobrescrevem ensaios anteriores. Limite diagnóstico90s verificado entre operações (não timeout de teste); todas as400 operações terminaram antes dele. Sem repetições adicionais. Tempo total14,297623s,saída0. Quatro controles de integridade aprovados: contagem/`quick_check`/reabertura SQLite e conteúdo integral do arquivo. Temporários removidos pelo `TemporaryDirectory` após o ensaio.

Ambiente: inícioUTC`2026-11-05T18:05:42.351195+00:00`,Python3.12.3/SQLite3.45.1/Linux6.6.87.2WSL2,filesystem confirmado **ext4 `/dev/sdd` montado em `/`**,temporário`/tmp/dealbot-disco-isolado-3prc9rx8`. Fontes do helper/venv continuam em `/mnt/c`, mas não há stacks de debug/consultas repetidas de metadados das fontes neste hot path. `journal_mode=wal`, `synchronous=2`(**FULL**), `busy_timeout=2000`,página4096,autocheckpoint1000 confirmados; sem lock concorrente criado pelo ensaio.

| Lote / operação de confirmação | Amostras | p50 / p95 / máx real(ms) | p50 / p95 / máx CPU(ms) | Quantidade acima de20ms /100ms |
|---|---|---|---|---|
|1 / SQLite commit |100 |2,096565 /53,372270 /104,888560 |0,1358 /0,2372 /0,4983 |9 /1 |
|2 / arquivo fdatasync |100 |38,930133 /74,524114 /91,861772 |0,1502 /0,2615 /0,7114 |100 /0 |
|3 / arquivo fdatasync |100 |29,243371 /41,433503 /85,205801 |0,1432 /0,2276 /0,5024 |83 /0 |
|4 / SQLite commit |100 |41,135364 /60,772236 /283,882666 |0,2785 /0,5217 /0,5986 |100 /3 |

Inserções SQL e `pwrite` tiveram máximos abaixo de0,310ms nos quatro lotes; a cauda está na confirmação, não na montagem/inserção do dado. A pior confirmação SQLite (lote4/iteração99) levou283,882666ms reais e0,293ms CPU. O monitor capturou, na própria operação de commit/fdatasync: syscall75 (`fdatasync`,x86_64), descritores dos respectivos WALs/arquivos temporários, **`jbd2_log_wait_commit` em522 amostras SQLite e579 amostras de arquivo**. Houve ainda amostras em `folio_wait_bit_common` e transições/running. Amostras são observações correlacionadas, não522/579 commits distintos.

Telemetria global somente leitura: no intervalo14,064061s entre snapshots, `/proc/pressure/io` avançou10,291078s em`some` e10,263556s em`full`; `/dev/sdd` acumulou13804ms deIO e29350ms ponderados. Esses contadores incluem outras atividades do sistema e **não são uso exclusivamente do ensaio nem prova de defeito físico**. Espaço livre reportado pelo filesystem virtual:1022679642112bytes; isso não mede espaço/saúde do volume Windows ou do VHDX. Não houve inspeção/modificação de conta, antivírus, energia, registro, distribuição ou configuração de disco do host.

**Conclusão:** confirmada **latência variável na confirmação durável do armazenamento WSL, independente do bot/filtros**, inclusive no controle sem SQLite. Portanto, atribuir necessariamente o deadline à lógica de filtro ou abrir patch especulativo é indevido. Este ensaio isola a existência do gargalo abaixo da aplicação; não determina se a origem final é journal/ext4, disco virtual/host ou contenção externa, nem prova que seja a causa única de cada episódio histórico. Os3,03s da fila no episódio anterior não são automaticamente decompostos pelos percentis desta outra janela/carga.

**Decisão:** não mudar filtros, diminuir commits, desabilitar debug, relaxar watchdogs ou trocarFULL. Não há correção funcional demonstrada nesta continuação. O problema de armazenamento é agora evidência concreta a considerar na reavaliação de ambiente/validação, não desculpa inferida apenas de uma execução verde. Estado **`em_implementacao`**,CA-025/VAL-ET2-005 ainda sem aceite; a matriz histórica abaixo não é reescrita. Qualquer intervenção no WSL/Windows exige autorização específica e uma comparação antes/depois, sem prometer que reiniciar ou mover fontes resolve o disco virtual. Hashes de todos os47 arquivos Python observados e os241 controles foram preservados; só este registro foi acrescentado ao projeto. Sem staging/commit/publicação.

## 16. Resultado da validação

### Validação após inicialização explícita da Ubuntu — 2026-11-05 — aprovada

Usuário autorizou a intervenção controlada descrita na conversa: identificar distribuição/processos, encerrar somente a distribuição dos testes se necessário, iniciar e medir, com uma única validação integral se justificada. `wsl --list --verbose` mostrou **Ubuntu(default) e docker-desktop já paradas**; portanto **nenhum `--terminate` ou `--shutdown` foi executado**. Iniciada explicitamente somente Ubuntu. Inventário `ps` sem argumentos de processos mostrou serviços padrão/systemd e o diagnóstico, sem trabalho de aplicação identificado; nenhum serviço foi interrompido/modificado. Docker e Windows não foram reiniciados. Não atribuir causalidade a um reinício que o agente não realizou.

Controle repetido uma única vez: mesmo `dealbot-disco-isolado.py`, bytes/carga/instrumentação idênticos, alterado somente o nome do JSON em memória por `dealbot-disco-pos-inicio.py`. Ubuntu/bootID`b8c52648-735f-4824-8f25-6ac40a3488cf`, uptime59,75s antes/61,24s depois.400 operações e quatro lotes íntegros, fontes/testes intactos, **1,388665s** versus14,297623s na amostra anterior; não comparação causal isolada. p50/p95/máx da confirmação emms: SQLite1 **2,381038/4,057557/83,338270**, arquivo2 **2,022329/2,313133/5,036471**, arquivo3 **2,001828/2,219632/2,445235**, SQLite4 **2,090329/2,467034/3,136044**. Um picoSQLite83,338ms permanece exposto; não declarar armazenamento universalmente estável. Monitor registrou seis amostras cada em`jbd2_log_wait_commit` e`folio_wait_bit_common`, syscall75 durante commit.

**Ajuste explícito do plano diagnóstico, não do aceite:** o launcher havia pré-fixado uma triagem conservadora de p95≤10ms/máx≤50ms em todos os lotes e registrou`gate_passou=false` pelo único pico83ms. Esse resultado/decisão inicial de parar são preservados no JSON, sem renomeá-los como aprovação. Reavaliada a utilidade dessa triagem: não existe máximo50ms aprovado no PRD, e400 operações íntegras com p95≤4,058ms/melhora global de cerca de10× justificam a única suíte real autorizada. Não se aumenta prazo de teste nem se omite pico; o critério continua CA-025 e watchdogs originais2s/3s. Não repetir controle ou suíte até verde, nem converter a triagem inventada em novo bloqueante de produto.

Raiz/runtime global/`_comum.md`/`validar.md`/instruções reconfirmados; PRD integral e seus registros já lidos nesta continuação, sem alteração material. Aprovação v1/base/worktree/diff preexistentes preservados. Impedimento de decisão de ambiente foi autorizado e controle mostrou melhora suficiente para tentar validação, não prova de resolução; estado passou por`em_validacao` antes dos testes. Roteiro **UI01 — inspeção/inicialização/controle; UI02 — uma suíte normal integral; UI03 — matrizes/verificações/decisão: concluídos**. Resultado da entrega **`concluido`** no escopo aprovado. Nenhuma produção/teste/pin/configuração alterada nesta rodada,sem conta/SQL remoto/publicação/etapa3.

Evidências externas no diretório aprovado: `dealbot-disco-pos-inicio-01.json` e `dealbot-disco-pos-inicio-decisao-01.json`, helperoriginal SHA256`c862628b181740703ef132a9740041e104a1ae19e7527039372355de0777c558`. Comando em`bot/`: `wsl --distribution Ubuntu --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python -B /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-disco-pos-inicio.py`. Saída0, temporários ext4 descartáveis; não é suite unitária/aceite.

#### Fechamento normal e reavaliação de VAL-ET2-005

**Uma única suíte integral normal nesta autorização:241/241 em90,349s,saída0,zero falhas/erros/skips.** Comando exato em`bot/`: `wsl --distribution Ubuntu --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python -B -m unittest discover -s tests -v`. Subprocesso sem monkeypatch/profiler/heartbeat/alteração de métodos; somente stdout/stderr redirecionados para log e telemetria global lida antes/depois. Os48 hashes de fontes/testes/pins coincidem com a rodada anterior que falhou e permaneceram iguais após esta. Watchdogs originais2s/3s,debug/SQLiteWAL/FULL e todas as assertions mantidos.

Passaram o caso original de refresh, os quatro controles determinísticos de progresso, a rajada/justiça/heartbeat e **o corpo completo de foto lenta/oferta antes da foto/shutdown/restart**, que anteriormente parara no início da foto. Também passaram migrações/rollback/POSIX/sinais/retenção/SDK/projeção/decisões antigas e todas as contraprovas históricas de extração. Não houve outra rodada normal/isolada para selecionar verde nesta autorização.

**Limite causal preservado:** a suíte começou com bootID`9064fb5b-2e56-4958-96e1-1a920729d5a6`/uptime5,62s e terminou em96,96s; diferente do boot do controle. A distribuição/VM encerrou e voltou a iniciar entre comandos **sem comando de encerramento do agente**. Não foram controle e suíte na mesma instância continuamente ativa. Portanto, não se atribui o sucesso a um reinício manual, não se promete persistência da melhora deIO e não se prova causa única de todos os timeouts anteriores.

InícioUTC`2026-11-05T18:46:20.217963+00:00`; janela externa91,337481s,distinta dos90,349s do runner. JSON/log íntegros em `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-pos-inicio-final-01.{json,log}`. WarningsGoTrue e avisos de tasks lentas permanecem: coleta3,598s,migração até11,673s/3,771s eSDK3,740s,entre outros. Pressão global deIO avançou16,494751s(`some`)/16,464649s(`full`),sem identificar responsável. **O ambiente não foi comprovado livre de caudas de latência** mesmo nesta suíte aprovada.

**Reavaliação proporcional:** VAL-ET2-005 era bloqueante por ausência de fechamento aprovado de regressões, não por defeito funcional de filtro já demonstrado nem por um SLA novo. Há agora fechamento normal do código final,controles determinísticos/restart/contraprovas aprovados e diagnóstico independente de espera de armazenamento. O requisito não exige identificar retrospectivamente a causa de todo episódio ou provar ausência universal de races. **CA-025 atendido e bloqueio005 encerrado como pendência de validação**, sem alegar patch/resolução causal. Falhas anteriores não são apagadas/convertidas para sucesso. Causa residual e variabilidade ficam como **observação não bloqueante O-ET2-001**, com evidências/limites/procedimento de diagnóstico preservados. Se houver nova falha futura, registrá-la/investigá-la sem relaxar testes ou usar este aceite para ignorá-la.

#### Verificações entre camadas e escopo

Suíte Python sem carga de build/testes concorrentes iniciada pelo agente; verificações Windows seguintes em paralelo onde independentes. Python3.12.3/WSL2Linux6.6.87.2/pins existentes;Node24.11.1/Windows eNext14.2.5. Não Node20/browserreal/produção. Nenhum pacote instalado/atualizado. Diff preexistente previsto/necessário: bot/API/UI/SQL/CLI/testes/docs. Factories ePGlite temporário são desvios menores documentados; três prompts/trabalho anterior preservados. Nesta rodada alterado somente este PRD; helpers/logs fora do worktree. Sem ciclo curto novo,dependência,migração de dados reais,auth/identidade/imagem ou etapa3.

| Comando/procedimento | Resultado/limite |
|---|---|
| `python -B -m unittest discover -s tests -v` com prefixo acima |241/241/90,349s,zero falhas/erros/skips,saída0. |
| `npm test` em`backend/` |40/40,zero skips,675,4393ms,saída0,fakes sem serviço real. |
| `npm test` em`frontend/` |7/7,zero skips,1223,3229ms,saída0,componente real eAPI/Auth/hooksfalsos,não browserE2E. |
| `npm run lint` em`frontend/` |Saída0,sem warnings/erros. |
| `npx --no-install tsc --noEmit --incremental false` em`frontend/` |Saída0,sem diagnósticos. |
| BuildNext eSQLlocal,comandos exatos abaixo |Build compilou/lint/tipos/6páginas;SQLPostgres18.6/PGlite0.5.11 aplicou2× eaprovou preservação/defaults/constraints/preflight/atomicidade;ambos saída0. |
| `python -m pip check` com distribuição/venv acima |No broken requirements found,saída0. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` |Saída0,SSDKingstonNV2-1TB-NVMe,299,90/399,90,`AbC123`,URL/query/caixa preservadas,aceita/regra1;sem credenciais/rede/equivalência/códigos0/2/1 também testados. |
| `node -e`/`spawnSync(process.execPath,['--check',file])` emJS/MJS de`backend/src`/`tests` |23 arquivos aprovados,Node24.11.1;backend sem scriptslint/build/typecheck próprios,não declarados executados. |
| Contratos/privacidade/segurança aplicável |Semântica/preço/snapshot/PUTpausado eparcial/JSON/UTF-16/DDL/whitelist/logs/rollback e limites revisados nesta continuação,regressões atuais aprovadas. Não pentest/auditoria universal. |
| AST/hash/diff/status/arquivos protegidos/staging |47Python/241métodos e fontes/pins48hashes intactos;protectedfiles incluindo middleware real`auth.middleware.js`,dedup/sinais/recuperação/mídia/locks/legado sem alteração contraHEAD. Só registro deste PRD alterado;sem staging/publicação. |
| Simulação/corpus/listasnolímite |Não reexecutados nesta rodada sem mudança de produção/dataset/runner. Medições antes/depois históricas mantidas ehashcorpus conferido;testes`test_simulacao`/adversariais/derivadosreutilizados aprovados no241. Não apresentar números antigos como novos ou usar o verde para apagar variação de34s. |

Build executado em`frontend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['node_modules/next/dist/bin/next','build'],{stdio:'inherit',env:{...process.env,NEXT_PUBLIC_SUPABASE_URL:'https://supabase.invalid',NEXT_PUBLIC_SUPABASE_ANON_KEY:'fake-anon-key',NEXT_PUBLIC_API_URL:'http://127.0.0.1:3333/api',NEXT_TELEMETRY_DISABLED:'1'}});process.exit(r.status??1)"
```
SQL executado em`backend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['tests/sql-etapa2.local.mjs'],{stdio:'inherit',env:{...process.env,DEALBOT_TEST_POSTGRES_URL:'',DEALBOT_TEST_PGLITE_MODULE:'C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql/node_modules/@electric-sql/pglite/dist/index.js'}});process.exit(r.status??1)"
```

#### Matriz final desta validação — requisitos

| ID | Resultado | Evidência |
|---|---|---|
| RF-001 | atendido |Título/modelo/capacidade/conteúdodescritivo/caudas/rodapés/URLs,regressões atuais. |
| RF-002 | atendido |BRL/centavos/papéis/zero/desconhecido/parcelas/múltiplos,contraprovas preservadas e atuais. |
| RF-003 | atendido |SDKfixado/live/raw/UTF-16/emoji/botões/contextodurável e links,semRPCextra,testes atuais. |
| RF-004 | atendido |Cupomcontextual/grafia/ambiguidade/categorias/sete enums/extensão vazia,Python/API/UI. |
| RF-005 | atendido |OR/AND/frases/centavos/teto0/desconhecido/razõesporregra,snapshotpreparado,testes atuais. |
| RF-006 | atendido |Globais/locais/modos/configdesconhecida/vazia/últimoválido e progresso após refresh,quatrointerleavings atuais. |
| RF-007 | atendido |40API/7UI/lint/tipos/build,CRUD/limites/PUTparcial/pausado/erros,contratos preservados. |
| RF-008 | atendido |Migrações/rollback/JSONlegado/hashsoberano/whitelist/spies/congelamentoantesrede/restart,testes atuais. |
| RF-009 | atendido |CLI/JSON/códigos0/2/1/diagnósticolocal/semcredenciais e rede/testes de logs. |
| RF-010 | atendido |README/PRD/semântica/métricas históricas/exemplos/ordem/rollback/limites/continuidade,sem evidência inventada. |
| RN-001 | atendido |Evidênciadeproduto/nulos/ambiguidade/múltiplos/semminmaxarbitrário,testes atuais. |
| RN-002 | atendido |Globalantesinteresse,veto local/OR/AND/snapshotválido,Python/API/UI. |
| RN-003 | atendido |Decisão/hashcongelados/spies/retry/semreabrirfinalizados,testes atuais. |
| RN-004 | atendido |241incluemcoleta/gerações/páginas/canais/cache/workers/justiça/async/fotoantesmídia/restart/sinais/retenção,todospassaram. |
| RN-005 | atendido |Dedup/janela48h eaparições preservados,reconciliação/checkpoints atuais. |
| RN-006 | atendido |Semconta/SQLremoto/publicação,prompts e trabalho anterior preservados. |
| RNF-001 | atendido |Extração/avaliaçãopuras,semIA/loja/redirect/RPC/sleepnovo,regressões/revisão. |
| RNF-002 | atendido |Snapshot/derivadosreutilizados,testeslongos/adversariais/medições de limite preservados,sem novo SLA. |
| RNF-003 | atendido |Number/null/centavos/JSON/SQLitelegado/IDs/categorias/pins/auth preservados e testados. |
| RNF-004 | atendido |Whitelists/logs/retencão/permissões/contextolocal,fixtures sintéticas,testes atuais. |
| RNF-005 | atendido |Falhas históricas/gate conservador negativo/bootdistinto/limitescausais expostos,sem skips/relaxamentos/repetição cega. |

#### Matriz final desta validação — aceitação

| ID | Resultado | Evidência |
|---|---|---|
| CA-001 | atendido |Chamada+SSD/hífens/modelo/capacidade/títulodescritivo,Python. |
| CA-002 | atendido |SSDcurta/divulgação/URL/cupom/rodapé e conteúdos,Python. |
| CA-003 | atendido |De/por/frete e pontuação,corrigidossem criarpreço fictício,regressões. |
| CA-004 | atendido |Parcela/vista/semderivartotal/especificações e marcadorcomposto,regressões. |
| CA-005 | atendido |Desconto/mínimo/percentual/modelos/anteriorinconsistente/cardsem%fictício,Python/UI. |
| CA-006 | atendido |BRL/NBSP/localeambíguo/faixa/JSON/centavos/zero/teto,Python/API/UI. |
| CA-007 | atendido |Multilinha/inline/preçosiguais eúnicocomespecificação,terminalsemremoto,Python. |
| CA-008 | atendido |Prioridadecomercial/curto/query/caixa/fragmento/delimitadores/schemes,Python/CLI. |
| CA-009 | atendido |Live/rawSDK/emoji/UTF-16/entidades/botões/semRPCextra,Python. |
| CA-010 | atendido |Bancos0–4→5/restart/rollback/IDs/jobs/hash/fronteiras/mídia,Python. |
| CA-011 | atendido |AbC123 contextual/isolado/incompleto/ambíguo,Python/CLI. |
| CA-012 | atendido |Categoriasporobjeto/tokens/seteenums/`todos`inválido,Python/API. |
| CA-013 | atendido |Qualquer/todas/OR/listavazia/categoria/teto,Python. |
| CA-014 | atendido |Frasecontígua/normalização versusdispersa/limites,Python. |
| CA-015 | atendido |Preçodesconhecido sófalhateto/alternativa/razõesporregra,Python. |
| CA-016 | atendido |Globalqualquer/todas/local/condiçãopósserviço/preço,regressões ePython. |
| CA-017 | atendido |Seminteresse/semativos/configinválida/desconhecida/últimoválido/refresh,Python. |
| CA-018 | atendido |40API:CRUD/defaults/enums/categoria/listas/frases/duplicatas/moeda/limites. |
| CA-019 | atendido |PUTparcial/pausado/ativo-only/omitido/null/[]/schema versus404,API/UI. |
| CA-020 | atendido |7UIcomponenterealfakes:criar/editar/listar/toggle/modos/ajuda/zero/erro/escape,sem browserE2E. |
| CA-021 | atendido |SQLPostgreslocal2×/dados/defaults/constraints/preflight/atomicidade/schemaexplícito,SQL/API/cache. |
| CA-022 | atendido |Hash/decisãosoberanos/spies/restart/commitambíguo/>48h/card/aparições,Python. |
| CA-023 | atendido |Clienteestrito/whitelist/logssemprivados/diagnósticolocal/rejeiçãosemremoto,Python. |
| CA-024 | atendido |CLIexemplo/equivalência/JSON/códigos0/2/1/semcredenciais/socketproibido,Python. |
| CA-025 | atendido |Fechamento normal241/241/90,349s,zero falhas/erros/skips,assertions/watchdogs2s/3s/debug/WAL/FULL intactos. |
| CA-026 | atendido |Simulação/corpus/limites históricos ehashes preservados,sem código novo exigindo novo antes/depois;testes de simulação eadversariais atuais,documentação/rollback/limitações. |

#### Decisão final e continuidade

**21/21 requisitos e26/26 critérios atendidos;T01–T08 e proteções obrigatórias concluídos;nenhum bloqueante aberto nesta validação.** Estado **`concluido`**,aprovação v1 mantida,sem alteração de escopo/aceite ou aceite parcial. Encerrar a etapa2 é decisão de conformidade com o PRD e evidência acumulada, **não declaração de que um verde isolado prova causa histórica ou ausência de bugs**. O-ET2-001 preserva a incerteza temporal e os controles foram mantidos para futuras regressões. Não criar SLA/critério50ms extra,refatoração ou patch especulativo para acomodar o ambiente.

Limites/pendências operacionais fora do aceite local: Node20/browserreal/produção/Telegram/Supabase/VPS não exercitados,Postgreslocal não provaRLS/extensõesreais,corpus sintético/heurísticas não sãouniversais e a latênciaWSL continua variável. Aplicar schema/rollout/deploy requer autorização própria,backup consistente e ordem já documentada. **Parar aqui:** sem commit/push/merge/deploy/SQLremoto ou início automático da etapa3. Próximo passo depende de nova solicitação do usuário, não de mais repetição da suíte desta etapa.

**Histórico preservado:** as decisões negativas abaixo descrevem suas respectivas rodadas e permanecem intactas. Não representam o estado de aceite atual acima.

### Revalidação após controle isolado de armazenamento — 2026-11-05 — conclusão bloqueada

Autorização explícita do usuário para reavaliar a pendência e executar a validação necessária ao encerramento. Runtime global `_comum.md`/`validar.md`, PRD integral, instruções/base/único worktree reconfirmados. Triagem do estado `em_implementacao`: T01–T06/T08 implementados, T07 reaberto somente para evidência de regressão; diagnóstico dirigido e controle sem bot concluídos, sem defeito produtivo confirmado exigindo correção. Implementação apta a nova validação, portanto estado `em_validacao`, aprovação v1 preservada. Não se alteram requisitos ou matrizes anteriores.

Roteiro **RV01 — revisão de evidências e uma suíte normal; RV02 — contratos/verificações aplicáveis; RV03 — matriz e decisão: concluídos nesta revalidação**, não entrega aprovada. Intenção: comprovar extração/filtros e preservação de coleta, decisões/hash e dados. Todo o diff de implementação e os241 controles são preexistentes. Plano finito cumprido: **uma** execução normal integral no checkout original, sem sonda/profiler/método substituído, conservando modo debug/watchdogs/WAL/FULL; nenhuma repetição completa ou isolada para obter verde. Lentidão independente do bot é evidência de ambiente, não aprovação automática de CA-025 ou prova causal universal. Nenhuma intervenção no WSL/Windows, conta, SQL remoto, publicação ou etapa3 autorizada.

#### Resultado e reavaliação da pendência

**241 executados/240 aprovados/um erro/zero falhas de assertion/zero skips,87,219s,saída1.** O teste de rajada, o de refresh inicial e os quatro controles de progresso passaram. O erro atual foi `test_pipeline.TestPipeline.test_foto_lenta_oferta_salva_primeiro_e_shutdown_retomavel`, em `bot/tests/test_pipeline.py:122`: `await asyncio.wait_for(self.telegram.iniciou.wait(), 2)` excedeu os **2s originais**, com cancelamento de `Event.wait` seguido de `TimeoutError`. O corpo ainda não havia chegado às assertions de produto/foto/restart; não afirmar que a retomada desse caso foi comprovada nesta execução. Outros controles de mídia/checkpoints passaram.

É uma ocorrência de timeout em outro ponto do pipeline, **não reprodução exata do refresh/rajada**, e não demonstra por si só inversão da ordem oferta/foto, defeito no filtro, deadlock ou perda de dados. Esta execução normal não capturou o estado/fatal/syscall dos workers no instante da falha; não promover capturas de episódios diferentes a prova da causa deste. **VAL-ET2-005 continua como pendência de fechamento da regressão**, sem inventar patch comum ou esconder a nova ocorrência.

As evidências externas `dealbot-disco-isolado-01.json` e relatórios de rajada foram reavaliados com hashes do código ainda coincidentes: confirmações lentas e espera de journal existem sem bot, inclusive com arquivo simples. Isso distingue uma limitação concreta do ambiente de uma falha funcional demonstrada nos filtros. Não autoriza dispensar a suíte obrigatória. Durante a nova execução, pressão global deIO avançou20,171902s em`some` e20,138653s em`full` na janela externa88,100497s; contadores globais não identificam o responsável nem provam a causa dos2s. Avisos de tarefas lentas de coleta2,916s, migrações0,666/1,286/1,326s eSDK3,445/0,792s preservados, sem supressão ou atribuição causal automática.

**Decisão: `bloqueado` para a conclusão da validação.** A funcionalidade está implementada e não há defeito localizado demonstrado que justifique outra alteração de filtro ou um retorno automático a uma correção especulativa. Entretanto, a verificação obrigatória continua negativa no ambiente com limitação de armazenamento comprovada. Antes de outra tentativa, é necessária decisão sobre o ambiente de validação/intervenção autorizada; não continuar o ciclo de implementação/validação cega. Essa classificação **não declara que toda falha seja ambiental**, não transforma CA-025 em atendido e não é aceite parcial. Aprovação v1 preservada; nenhuma mudança material.

#### Escopo, verificações e limites

Previstos/necessários e preexistentes: extração/regras/contexto/SQLite/CLI/whitelist, CRUD/API/UI, SQL aditivo e testes. Factories e PGlite temporário permanecem desvios menores documentados, sem nova stack. Três prompts do usuário preservados. Nesta revalidação, alterado **somente este PRD**; nenhuma linha de produção/teste/configuração/dependência alterada. Captura externa limita-se a redirecionar stdout/stderr do subprocesso normal para log e ler telemetria antes/depois; não injeta código no processo da suíte. Não houve ciclo curto de correção ou teste novo.

Python em `bot/` com prefixo `wsl --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`,3.12.3 e pins existentes, WSL2/Linux6.6.87.2. Fontes/venv9p, SQLite temporário ext4. API/UI Windows/Node24.11.1, Next14.2.5; não Node20. Suíte Python executada sozinha, antes das outras verificações; API/UI depois em paralelo entre si. Host não isolado. Nenhuma instalação, upgrade, reinício ou modificação de configuração.

| Comando/procedimento | Resultado real |
|---|---|
| `python -B -m unittest discover -s tests -v` |241/240+um erro/87,219s,saída1,sem skips; detalhes acima. Apenas uma rodada normal. |
| `npm test` em`backend/` |40/40,zero skips,568,5778ms,saída0, fakes offline. |
| `npm test` em`frontend/` |7/7,zero skips,1010,088ms,saída0; componente real/API/Auth/hooks falsos, não browserE2E. |
| `npm run lint` em`frontend/` |Saída0,sem warnings/erros ESLint. |
| `npx --no-install tsc --noEmit --incremental false` em`frontend/` |Saída0,sem diagnósticos. |
| BuildNext com comando abaixo |Compilação/lint/tipos e6páginas aprovados,saída0,envfictício; sem servidor/login/API real. |
| SQL com comando abaixo |PostgreSQL18.6/PGlite0.5.11: bloco aplicado2×,preservação/defaults/constraints/preflight/atomicidade aprovados,saída0. |
| `python -m pip check` |No broken requirements found,saída0. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` |Saída0,SSDKingstonNV2-1TB-NVMe,299,90/399,90,cupom`AbC123`,URL com query/caixa preservadas,aceita/regra1. Equivalência semenv/rede e códigos0/2/1 passaram na suíte. |
| `node -e`/`spawnSync(process.execPath,['--check',file])` emJS/MJS de`backend/src`/`tests` |23arquivos aprovados,Node24.11.1; não há scriptsbackendlint/build/typecheck, não declarados executados. |
| AST/hash/evidências por stdin |47arquivos Python parseados/241métodos; hashes de todos os arquivos observados na sonda de disco e48 arquivos da suíte normal conferidos/intactos. Sem bytecode novo. |
| Simulação/corpus/limites |Não reexecutados nesta rodada: sem mudança de código/runner/dataset desde as medições já registradas. Hashcorpus e resultados anteriores preservados; três testes de`test_simulacao` passaram nesta suíte. Não são métricas novas, nem substituem CA-025. |
| Revisão de contratos/erros/privacidade e documentação |Modos/escopos/centavos/PUTparcial/pausados,JSONlegado/hash,contextoUTF-16,whitelist/logs/DDL/ordem de rollout conferidos. Sem achado funcional novo no recorte; não auditoria universal de produção. |
| Arquivos protegidos/status/diff/`git diff --check`/staging |Sem alteração em dedup/main/recuperação/sinais/mídia/legado/pins/locks/auth protegidos contraHEAD; trabalho preexistente preservado. Sem staging/commit/publicação. |

Log completo e relatório somente no diretório aprovado `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-revalidacao-final-01.{log,json}`. InícioUTC`2026-11-05T18:12:06.612394+00:00`; tempo externo88,100497s inclui lançamento/fechamento do subprocesso e snapshots de telemetria, mas não exportação posterior doJSON; não confundir com87,219s do unittest. Subprocesso executou exatamente o comando da tabela no checkout original; fontes/testes48hashes antes/depois idênticos. Warnings e trace integral preservados.

Conferência de preservação de auth corrigiu o caminho usado anteriormente: middleware real é `backend/src/middlewares/auth.middleware.js`, não `auth.js`. Diff explícito do arquivo real, `backend/src/routes/index.js`/`config/supabase.js` e hooks/API/Supabasefrontend saiu0/vazio. A primeira conferência estrutural por stdin contou237 cabeçalhos unittest porque exigia `...` na mesma linha: quatro testes têm docstring e impressão em duas linhas. Regex de identificação independente da segunda linha contou241, coerente com runner/AST; erro do verificador efêmero, não regressão/skip da aplicação. Nenhum teste/expectativa foi alterado para acomodá-lo.

Build executado em`frontend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['node_modules/next/dist/bin/next','build'],{stdio:'inherit',env:{...process.env,NEXT_PUBLIC_SUPABASE_URL:'https://supabase.invalid',NEXT_PUBLIC_SUPABASE_ANON_KEY:'fake-anon-key',NEXT_PUBLIC_API_URL:'http://127.0.0.1:3333/api',NEXT_TELEMETRY_DISABLED:'1'}});process.exit(r.status??1)"
```
SQL executado em`backend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['tests/sql-etapa2.local.mjs'],{stdio:'inherit',env:{...process.env,DEALBOT_TEST_POSTGRES_URL:'',DEALBOT_TEST_PGLITE_MODULE:'C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql/node_modules/@electric-sql/pglite/dist/index.js'}});process.exit(r.status??1)"
```

#### Matriz de requisitos desta revalidação

| ID | Resultado | Evidência |
|---|---|---|
| RF-001 | atendido |Regressões de título/conteúdo/condições/URLs/rodapés/inline passaram; nenhum corte novo demonstrado. |
| RF-002 | atendido |Papéis monetários,centavos/BRL/zero/nulo,parcelas sem total e múltiplos; regressões históricas e marcador composto passaram. |
| RF-003 | atendido |SDKfixado/live/raw/contextoUTF-16/emoji/botões/semRPC/restart e migrações passaram. |
| RF-004 | atendido |Cuponscontextuais/grafia/categorias/tokens,fallback/adaptadores sem formato inventado,Python/API/UI passaram. |
| RF-005 | atendido |Snapshotpreparado,OR/AND/frases/centavos/zero/desconhecido e razões por regra passaram. |
| RF-006 | atendido |Globais/locais/modos/schema/configdesconhecida/vazia,refresh e quatrointerleavings passaram. |
| RF-007 | atendido |40API/7UI/lint/tipos/build,merge/pausado/omitido/null/[]/erros e limites. |
| RF-008 | atendido |Migrações/restart/DDLrollback,decisãoJSON/hashsoberano/whitelist e rejeição sem rede passaram. |
| RF-009 | atendido |CLIexemplo/JSON/códigos0/2/1/equivalência semtokens/socketproibido,logs/diagnósticolocal testados. |
| RF-010 | atendido |README/PRD/ordem/rollback/limites e histórico negativo preservados; sem métricas ou aceite inventados. |
| RN-001 | atendido |Evidência de produto,descontos/divulgação/ambiguidade e ausência de min/max arbitrário,testes atuais. |
| RN-002 | atendido |Globalantesinteresse,veto local/OR/AND/snapshotválido,controles atuais. |
| RN-003 | atendido |Spies/retry/hash e decisão congelados/sem reabrir finalizados,testes atuais. |
| RN-004 | parcialmente atendido |Coleta/páginas/gerações/limites/async/justiça/refresh/sinais/retenção passaram; uma regressão de início de mídia excedeu2s e não completou seu corpo. |
| RN-005 | atendido |Dedup/janela48h inalterados,aparições/reconciliação/checkpoints atuais aprovados. |
| RN-006 | atendido |Prompts/trabalho anterior preservados,sem contas/SQLremoto/publicação. |
| RNF-001 | atendido |Lógica local semIA/HTTPloja/redirect/RPCextra/sleepnovo,regressões e fontes conferidas. |
| RNF-002 | atendido |Snapshot/derivados preparados/reutilizados e testes adversariais passaram; medições históricas preservadas sem novo SLA. |
| RNF-003 | atendido |Number/null/centavos/categorias/IDs/JSON/SQLitelegado/pins/auth preservados,testes atuais. |
| RNF-004 | atendido |Whitelist/logs/retencão/permissões/contextolocal,fixtures sintéticas e testes atuais. |
| RNF-005 | atendido |Erro/limitação e causa não comprovada distinguidos,zero skips/relaxamentos,sem repetições atéverde. |

#### Matriz de aceitação desta revalidação

| ID | Resultado | Evidência |
|---|---|---|
| CA-001 | atendido |Chamada/SSD/modelo/capacidade/hífens e título descritivo,Python atual. |
| CA-002 | atendido |CurtaSSD99,divulgação/URL/cupom/rodapé fora do matching,Python atual. |
| CA-003 | atendido |De/por e frete isolado/pontuado,regressões atuais. |
| CA-004 | atendido |Parcelas/vista/sem derivação/especificação quantitativa e marcadorcomposto,regressões atuais. |
| CA-005 | atendido |Desconto/mínimo/percentual/modelos/anteriorinconsistente ecard semdesconto fictício,Python/UI. |
| CA-006 | atendido |BRL/NBSP/ambiguidades/faixa/JSON/zero/centavos/teto,Python/API/UI. |
| CA-007 | atendido |Múltiplos inline/multilinha/preçosiguais,únicoproduto com especificação e terminal semremoto,Python. |
| CA-008 | atendido |Prioridadecomercial/curto/schemes/delimitadores/query/caixa,Python/CLI. |
| CA-009 | atendido |Live/rawSDK/emoji/UTF-16/entidades/botões e transporte semRPCextra,Python. |
| CA-010 | atendido |Migrações0–4→5/rollback/contexto/restart/IDs/jobs/hash e fronteiras,Python. |
| CA-011 | atendido |CupomAbC123/isolado/incompleto/ambíguo,Python/CLI. |
| CA-012 | atendido |Categorias porobjeto/tokens/sete categorias/`todos`inválido,Python/API. |
| CA-013 | atendido |Qualquer/todas/OR/listavazia/categoria/teto,Python. |
| CA-014 | atendido |Frasecontígua/normalização/negativo disperso/limites de tokens,Python. |
| CA-015 | atendido |Desconhecido falha só teto,alternativa sem teto e razões porregra,Python. |
| CA-016 | atendido |Globais qualquer/todas/local/condição após serviço e preço,Python. |
| CA-017 | atendido |Seminteresse/semativos/globais,desconhecido/inválido preservam snapshot,refresh e interleavings,Python. |
| CA-018 | atendido |40API/defaults/enums/categoria/listas/frases/precisão/faixa eCRUD,fakes. |
| CA-019 | atendido |PUTparcial/pausado/ativo-only/omitido/null/[]/schema versus404,API/UI. |
| CA-020 | atendido |7UIreais comAPI/Authfalsos:criar/editar/listar/toggle/modos/ajuda/zero/erro/escape,sem browserreal. |
| CA-021 | atendido |PGlite/Postgreslocal bloco2×/dados/defaults/constraints/preflight/atomicidade,API/cache schema explícito. |
| CA-022 | atendido |Congelamento/hash/spies/commitambíguo/restart/>48h ecard/aparições,Python. |
| CA-023 | atendido |Clienteestrito/whitelist/logs saneados/diagnósticolocal/rejeiçãosemremoto,Python. |
| CA-024 | atendido |CLIexemplo/semcredenciais/rede/JSON/equivalência/códigos0/2/1,Python. |
| CA-025 | nao atendido |241executados/240passaram/umtimeout de2s ao iniciar foto; sem skips ou alterações de garantias. |
| CA-026 | atendido |Medições históricas reproduzíveis/datasets/custos separados/variação eREADME/rollback/limites preservados; sem código novo exigindo novo antes/depois; testes de simulação atuais passaram. |

#### Parecer e continuidade

**20/21 requisitos atendidos,1 parcialmente atendido(RN-004);25/26 critérios atendidos,CA-025 não atendido.** Bloqueante: fechamento obrigatório da regressão ainda negativo. Nenhuma nova vulnerabilidade, perda de dados ou defeito de filtro confirmado no recorte; não é auditoria universal nem prova de ausência de races. Padrões positivos preservados: centavos, snapshotvalidado, decisão/hashsoberanos,whitelist ePUTparcial/pausados. Sem refatorações de estilo ou novo código diagnóstico em produção.

Estado **`bloqueado`**,T07/proteção de fechamento continuam abertos. Não há aceite parcial nem autorização inferida para etapa3. Próximo passo: **decisão explícita do usuário sobre ambiente antes de qualquer outra tentativa integral** — disponibilizar ambiente Linuxlocal adequado ou autorizar intervenção controlada no WSL, com preservação dos demais processos/dados e confirmação de armazenamento antes/depois. Nenhum reinício/ajuste foi executado. Mover apenas fontes ou reiniciar não é correção garantida do disco virtual. Após ambiente preparado, solicitar `/sdd-validar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`; não indicar implementação especulativa dos filtros como solução.

Limites mantidos: corpus/heurísticas sintéticas semdetectoruniversal;Node20/browserreal/Telegram/Supabase/VPS/produção não executados;SQLlocal não validaRLS/extensõesreais. PublicaçãoGit/deploy/SQLremoto/contas,identidade/hashhistórico,imagens/auth/etapa3 fora do escopo. **Esta revalidação foi encerrada; nenhuma execução adicional está planejada automaticamente.**

**Histórico:** as matrizes abaixo permanecem negativas como resultados das suas próprias rodadas. Não são reescritas nem substituem o resultado desta revalidação.

### Validação após diagnóstico de VAL-ET2-005 — 2026-11-05 — não aprovada

Nova invocação explícita de `sdd-validar`. Raiz/runtime global, leitura integral de `_comum.md`/`validar.md`/PRD e `CLAUDE.md`, aprovação v1/estado `em_validacao`, base `main / 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a` e único worktree confirmados. Sem runtime local ou AGENTS.md; todo o diff e os238 testes são preexistentes e serão preservados.

Intenção: validar extração e filtros ponta a ponta, sem perder durabilidade, decisões congeladas/hash, dados ou proteções. Roteiro **VF01 — revisão de contrato/diagnóstico e suíte normal; VF02 — controles/ciclo curto/métricas/checagens entre camadas; VF03 — matrizes e decisão: concluídos na validação**. Resultado da entrega: **`em_implementacao`**, sem aprovação final. Não há alteração material/aprovação nova necessária. Resultados anteriores não são automaticamente aprovados. Sem conta/SQL remoto, publicação, etapa3 ou alteração de garantias.

Ciclo curto autorizado por `validar.md`, sem mudança material: em contraprova cruzada, `Memória RAM: 16 GB DDR4 (antes de R$ 1500)` entre preço genérico do notebook e preçoàvista deixava `(antes )` na descrição. `_PRECO_DESCRICAO` consumia só `de R$1500`, tornando o resto um falso modelo/objeto e gerando `multiplas_ofertas`. Causa localizada em uma alternativa da regex: `antes`→`antes(?:\s+de)?`, sem mudar classificação monetária, agrupamento, schema, regras/contratos ou identidade. Controle existente `antes R$` já era removido integralmente. Defeito exigido por RF-001/002 e CA-004/007, pequeno, objetivo e reversível; sem nova inferência monetária/detector universal.

Novo `bot/tests/test_validacao_pos_diagnostico_etapa2.py`, três métodos sintéticos: anterior composto em especificação quantitativa, marca/modelo/condição preservados e inbox/pipeline aprova único produto/rejeita múltiplos sem remoto. Antes do fix:3métodos/10falhas de subcasos em0,123s. Após o fix, dirigido112 teve quatro falhas **somente numa expectativa incorreta do novo teste**: títuloinline deveria manter a especificação na primeira linha, não `Notebook Dell` sozinho. Esperado corrigido para igualdade exata `Notebook Dell - Memória RAM: [quantidade]` conforme RF-001 e `_descricao` existente; não se alterou produção para esse ponto, nenhuma assertion dos238 métodos anteriores foi modificada. Novo módulo final3/3 em0,479s. Revisão independente somente leitura aprovou o recorte:17 controles síncronos emPython3.14.4/Windows, `-B`/socketbloqueado, regex anterior comparada somente em memória. Sem alteração de arquivos/testes completos/benchmarks pelo revisor; não é aceite SDD integral. As três regressões novas também passaram no fechamento completo. A causa histórica de VAL-ET2-005 continua inconclusiva; não confundir os dois achados.

#### Achado impeditivo atual — VAL-ET2-005 permanece aberto

Suíte recebida:238/238 em94,452s, zero skips/erros, antes do ciclo curto. Após a correção, `unittest discover -s tests -q` não concluiu no limite **externo da ferramenta de300s**: nenhum resumo final, portanto contagem/resultados totais inconclusivos, não aprovação nem prova de timeout de3s de um teste específico. Houve taskSDK lenta25,537s e migração1,780s nessa execução; não estabelecem causa. Conferência local `pgrep -af "python.*unittest"` saiu1/sem processo remanescente.

Uma única execução diagnóstica subsequente foi previamente delimitada para localizar a parada: mesmo módulo unittest/discovery, verbosidadeporcaso e `faulthandler.dump_traceback_later(90, repeat=True)` **somente para imprimir stacks, sem cancelar tarefa**. Limite externo600s; **watchdogs/assertions/debug/SQLite originais intactos**, sem substituição de métodos. Resultado: **241 executados,240 passaram,um erro,zero falhas de assertion/skips,163,425s,saída1**. Não foi feita outra repetição completa até verde.

Erro em `test_pipeline.TestPipeline.test_rajada_concorrencia_justica_e_heartbeat`, `test_pipeline.py:300`, aguardando finalização da mensagem100: watchdog original3s→`finalizada`→`EstadoLocal.evento`→`_executar`/shield→cancelamento→`TimeoutError`. Heartbeat teve aviso de tarefa0,690s nessa rodada. O teste de refresh originalmente associado ao005 e os quatro controles de interleavings passaram; a falha reapareceu numa regressão de justiça/concorrência do mesmo pipeline. **Não é prova de defeito no extrator ou de causa ambiental.** CA-025/RN-004 não têm fechamento satisfatório atual.

O dump periódico aos90s **totais** da execução, durante `test_retencao.test_oferta_nova_processa_durante_limpeza_real`, mostrou threadSQLite dentro de `EstadoLocal.limpar.<locals>.op`, linha418 (`with db`), e loop principal no seletor. Esse teste terminouok depois. É uma amostra de espera/execução em fronteiraSQLite, não prova de operação específica de fsync travada por90s, nem causalidade do timeout de rajada que já ocorrera. SDK nessa rodada teve tasklenta5,991s e coleta4,566s. Não somar avisos como explicação causal.

Revisão das evidências da retomada: JSONs234/20 sem falhas/skips e arquivos preservados, perfis recuperados9p/ext4 coerentes com custo de metadados observado; sondas modificam execução em memória e têm limites documentados. A investigação anterior é útil, mas não isolou a causa do episódio original nem fecha a nova falha. **Nenhuma correção especulativa em worker/cache/SQLite foi aplicada, nem o teste foi pulado/relaxado.** Reabrir T07/proteção de regressões e retornar à implementação para instrumento de progresso/estado/fatal/operação em curso nos casos de rajada/retenção, sem depender de uma leitura no executor potencialmente ocupado.

#### Escopo e comandos desta validação

Diff preexistente previsto/necessário: extrator/regras/contexto/SQLite/whitelist/CLI, CRUD/API/UI, SQL aditivo e documentação. Factories e PGlite temporário são desvios menores já documentados, não nova stack. Os três prompts são trabalho preexistente do usuário. Criados nesta validação apenas os três testes sintéticos e este registro/checklist; única alteração funcional de produção é uma alternativa de regex em `bot/src/extractor.py:39`, enquadrada no ciclo curto. Sem refatoração, migração/identidade/hash novo, dependência, autenticação ou código diagnóstico em produção.

Python em`bot/` com prefixo **`wsl --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`**,3.12.3/SDKsfixados/WSL2Linux6.6.87.2/glibc2.39. Fontes/venv em`/mnt/c`9p; SQLite temporário ext4 conforme diagnóstico anterior. API/UI Windows/Node**24.11.1**, não Node20. Nenhum pacote instalado/atualizado. Benchmarks finais sequenciais, após testes/build e sem carga iniciada pelo agente concorrendo; host não isolado.

| Comando/procedimento | Resultado real e limite |
|---|---|
| `python -B -m unittest discover -s tests -q` antes do ciclo curto |238/238 em94,452s,zero skips,saída0; prova do código recebido, não fechamento pós-correção. |
| Controles sintéticos por stdin, socketbloqueado |Primeira execução interrompida na50ªverificação:49 passaram e especificação`antes de` falhou. Após correção, mesmos **61/61 passaram**,saída0 (serviços/veto/múltiplos/componentes/moedas/URL/cupom). |
| `python -B -m unittest tests.test_validacao_pos_diagnostico_etapa2 -v` antes/após |Antes3métodos/10falhas/0,123s; final3/3em0,479s/saída0. Todos os238 métodos anteriores/assertions preservados. |
| `python -B -m unittest tests.test_validacao_pos_diagnostico_etapa2 tests.test_validacao_final_etapa2 tests.test_segunda_retomada_etapa2 tests.test_revalidacao_etapa2 tests.test_validacao_etapa2 tests.test_correcao_etapa2 tests.test_extracao tests.test_decisoes_etapa2 tests.test_filtros_etapa2 tests.test_progresso_configuracao -q` |112 métodos/21,531s,quatro falhas somente de títuloinline no novo teste, depois corrigidas conforme contrato. Não chamar essa rodada de112aprovados; demais108 passaram. |
| `python -B -m unittest discover -s tests -q` pós-fix |Ferramenta interrompeu em300s/sem resumo final; resultado inconclusivo, não aprovado. |
| `python -B -c "import faulthandler,runpy,sys; faulthandler.dump_traceback_later(90,repeat=True); sys.argv=['unittest','discover','-s','tests','-v']; runpy.run_module('unittest',run_name='__main__')"` |**241 executados/240 passaram/um erro/163,425s**,zero skips,saída1. Watchdogs inalterados; impressão de stacks não cancela ou substitui testes.005aberto. |
| `npm test` em`backend/` |40/40,zero skips/546,0437ms,saída0, fakes sem Supabasereal. |
| `npm test` em`frontend/` |7/7,zero skips/1112,6884ms,saída0; componentes reais com API/Auth/hooksfalsos, não browserE2E. |
| `npm run lint`; `npx --no-install tsc --noEmit --incremental false` em`frontend/` |Ambossaída0,sem warnings/erros ESLint/TS. |
| BuildNext comenvfictício eSQLlocal — comandos abaixo |Build14.2.5 compilou/lint/tipos/6páginas,saída0; PostgreSQL18.6/PGlite0.5.11 aplicoubloco2×/dados/defaults/constraints/preflight/atomicidade aprovados,saída0. Executados antes do ciclo curtoPython; essas camadas não foram modificadas depois. |
| `python -m pip check` |No broken requirements found,saída0. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` |Saída0,SSDKingstonNV2-1TB-NVMe,299,90/399,90,`AbC123`,URL/query/caixa preservadas,aceita/regra1. Códigos0/2/1,semcredenciais/socketbloqueado/equivalência também passaram na suíte. |
| `node -e`/`spawnSync(process.execPath,['--check',file])` recursivo em`backend/src`/`tests` |23JS/MJS aprovados,Node24.11.1; backend sem scriptslint/build/typecheck próprios, não declarados executados. |
| Leitura deJSONs/perfis históricos de diagnóstico |Métricas/contagens/imutabilidade/límites conferidos; sem reexecutar ensaios nem promover tempo de sonda a runnernormal/prova causal. |
| Fontes/testes/README/SQL/UI/diff e segurança aplicável |Invariantes dePUT/pausado/erros, esquemas explícitos,HTTP(S),escapeReact,whitelist,logs/retencão/permissões e ausência de rede extra conferidos. Não é auditoria universal/pentest/infra Supabasereal. |
| AST/conferência estrutural em memória |47 arquivos Python parseados/241 métodos,21 requisitos/26 critérios únicos;20/25 atendidos; estado`em_implementacao`/v1/aprovação preservados. Extrator/teste novo/PRD sem whitespace final. |
| `git diff --check`; `git diff --cached --exit-code`; status/diff e arquivos protegidos |Sem erro de whitespace ou staging; avisos LF/CRLF. Trabalho anterior preservado; sem arquivos temporários/segredos no worktree. |

Build executado em`frontend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['node_modules/next/dist/bin/next','build'],{stdio:'inherit',env:{...process.env,NEXT_PUBLIC_SUPABASE_URL:'https://supabase.invalid',NEXT_PUBLIC_SUPABASE_ANON_KEY:'fake-anon-key',NEXT_PUBLIC_API_URL:'http://127.0.0.1:3333/api',NEXT_TELEMETRY_DISABLED:'1'}});process.exit(r.status??1)"
```
SQL executado em`backend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['tests/sql-etapa2.local.mjs'],{stdio:'inherit',env:{...process.env,DEALBOT_TEST_POSTGRES_URL:'',DEALBOT_TEST_PGLITE_MODULE:'C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql/node_modules/@electric-sql/pglite/dist/index.js'}});process.exit(r.status??1)"
```

#### Medições atuais

Comando exato: `python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1`,saída0. **130recebidas/produtos/aprovadas**,zero descartes/duplicatas/falhas; **4,857889s/26,760594ofertas/s**. Livep50/p95/máx176,299/393,600/437,549ms;histórico3157,335/4682,612/4824,807ms;heartbeatmáx1,992534ms. Janela914,634857852–919,492746978,inícioUTC`2026-11-05T17:34:12.928148+00:00`,semsetup/shutdown/drenagemdefotos.

Workers máximos4/1; filas inicial/pico/final: live0/7/0, histórico0/100/0, mídia0/113/113.17 mídias prontas,112 pendentes/uma processando,17 tentativas/zero falhas;18 buscas de produto de mídia/17 vínculos. Uma carga de filtros/130 de cada operação fake de oferta, cinco esperas20ms/oferta/mídia200ms. Buffer/página100,zero task por mensagem,ambas as origens progrediram. Hash live`606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb`/histórico`27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805` inalterados.

Corpus por stdin equivalente a`python -B -m medir_extracao --iteracoes 100 --limites`,omitindo só exemplos/linhasporcaso:28casos sintéticos/seed42/3aquecimentos/2800amostras,SHA256`1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c`,janela2,825513s/990,97mensagens/s. p50/p95/máxµs: extração188,610/10880,975/14753,446;conjunto208,210/10915,477/14775,947;avaliação2500válidas19,801/31,002/86,404;preparo100amostras15,301/21,701/322,314. Regrasnolímite10×50termos/lista×100caracteres,preparoúnico118788,974µs,20avaliaçõessemreextração: curta1524,044/1562,597/1608,900µs,longa2668,515/2738,770/2764,372µs,adversarial1510,043/1593,899/1629,801µs.

Nenhum ganho causal/SLA ou causa ambiental inferidos:4,857889s atual não apaga34,241864s histórico,não explica300s da ferramenta ou163,425s da suíte,nem absolve o timeoutde3s. Custopuro/esperasfake/SQLite/debug são dimensões distintas. Dataset feliz,sucessoCPU e limitesworkers não substituem regressões obrigatórias.

#### Matriz atual de requisitos

| ID | Resultado | Evidência atual |
|---|---|---|
| RF-001 | atendido |Extrator/derivados compartilhados,título/conteúdo separados; ciclo curto retira marcador composto inteiro e mantém marca/modelo/condição/inline; testes e61controles. |
| RF-002 | atendido |Centavos/BRL/papéis/contexto,ambiguidade/múltiplos e especificação quantitativa; três novos controles/anteriores completos passaram. |
| RF-003 | atendido |TelegramSDK/live/raw/UTF-16/emoji/entidades/botões/links/restart passaram, semRPCextra. |
| RF-004 | atendido |Cuponscontextuais/grafia/categorias/palavrascompletas/fallback e extensão semformatoinventado passaram. |
| RF-005 | atendido |Regras preparadas/OR/AND/frases/conteúdodescritivo/centavos/zero/desconhecido/razõesporregra,controlesatuais. |
| RF-006 | atendido |Veto global/local/modos/schema/snapshotvalidado;casooriginalderefresh e quatrointerleavings passaram no fechamento. RajadaépendênciaRN004/CA025,semalegarcausado pelo cache. |
| RF-007 | atendido |40API/7UI,pausado/PUTparcial/omitido/null/[]/limites/erros,lint/tipos/build efonteaprovados. |
| RF-008 | atendido |SQLitev5aditivo/rollback,preservaçãoJSON/hash,spies/restart,whitelist/congelamento antesrede,terminal legítimo e reconciliação passaram. |
| RF-009 | atendido |CLI/códigosJSON/diagnósticoseparado/IDs/logssaneados,semcredenciais/rede,reutilização produtiva testada. |
| RF-010 | atendido |README/PRD com semântica,antes/depois sintético,migração/rollback,comandos/limites e falhasatuais expostas. |
| RN-001 | atendido |Evidência descritiva e preçosunknown,divulgação/serviços/múltiplos rejeitados,semmin/maxarbitrário; testesatuais. |
| RN-002 | atendido |Globalantesinteresses,veto local não global,condiçõescombinadas e ausência deinteresses sócomsnapshotválido;testes. |
| RN-003 | atendido |Decisões/hashsoberanos/spies/restart/commitsambíguos,sem reprocessamentohistórico; testes. |
| RN-004 | parcialmente atendido |Coleta/gerações/paginação/workerlimitado/async/foto/sinais/retenção passaram,mas rajada/justiça termina por timeout.005aberto. |
| RN-005 | atendido |Dedup/janela48h inalterados,aparições/reconciliação/checkpoints atuais aprovados. |
| RN-006 | atendido |Sem dados/contas/SQLremoto/publicação,prompts e mudanças anteriores preservados. |
| RNF-001 | atendido |Extração/avaliaçãopuras,socketproibido,semIA/loja/redirect/enriquecimento/sleepnovo produtivo. |
| RNF-002 | atendido |Snapshotpreparado/derivadosreutilizados,corpuslongo/adversarial/listaslimite medidos;semexplosãoobservada,nãoprovacomplexidadeuniversal. |
| RNF-003 | atendido |Number/null/centavos/JSON/SQLitelegado/categorias/IDs/pins/auth/stack preservados. |
| RNF-004 | atendido |Whitelists/logs/diagnósticolocal/retencão/permissões efixtures sintéticas; privacidade testada. |
| RNF-005 | atendido |Interrupçãoexterna/falhaderajada/expectativa incorretadonovoteste diferenciadas,nãoocultadas;semrelaxarasserts/watchdogs/debug. |

#### Matriz atual de critérios de aceitação

| ID | Resultado | Procedimento/evidência atual |
|---|---|---|
| CA-001 | atendido |Chamada+SSD e hífens/modelo/variante/títuloinline,extração econtraprovas atuaissemmudarcontrato. |
| CA-002 | atendido |CurtaSSD99 válida,grupo/URL/cupom/rodapé não provam produto/matching; testes. |
| CA-003 | atendido |De/por/frete atuaisanteriores distintos,controlesfretecom marcadores/pontuação aprovados. |
| CA-004 | atendido |Parcela/vista/semderivartotal,camposrotulados eanteriorcomposto semfalsomúltiplo aprovados. |
| CA-005 | atendido |Desconto/mínimo/percentual/modelos não preço,anteriorinconsistente ecardsem%fictício;Python/UI. |
| CA-006 | atendido |BRL/NBSP/ambiguidades/faixa/JSON/centavos/zero,tetoigual ecentavomaior;API/UI/Python. |
| CA-007 | atendido |Multilinha/inline/montantesiguais detectados; únicocomponentequantitativocomantesdepreservado;pipeline econtroles. |
| CA-008 | atendido |Comercialacimasocial/curto/caixa/query/delimitadores/HTTP(S),testes eCLI. |
| CA-009 | atendido |Live/rawSDK/UTF-16/emoji/botões/contexto/semRPCextra passaram. |
| CA-010 | atendido |Bancos0–4→5reaislocais/rollback/restart/preservaçãojobs/hash/IDs/fronteiras/mídia passaram. |
| CA-011 | atendido |CupomcomcontextopreservaAbC123,isolado/incompleto/ambíguonulo; controles. |
| CA-012 | atendido |Cadeira/headset/jogo/limitesdetokens/incerto/sete categorias/rejeição`todos`,fontes/testes. |
| CA-013 | atendido |SSD+Kingstonqualquer/todas/teto/listavazia/OR,noavaliadorpreparado,passaram. |
| CA-014 | atendido |Frasecontíguanormalizada,semtermosdispersos/coladosporcláusula,semfuzzy;testes. |
| CA-015 | atendido |Unknownrejeitasóteto,alternativaaceita/razõesporregra;testes. |
| CA-016 | atendido |Globalqualquer/todas/local econdiçõespósserviço/preço,inclusiveparênteses/aspas/vírgulas,atuais. |
| CA-017 | atendido |Seminteresses/semativos/globais/configinválida/desconhecida/últimoválido,refresh einterleavings passaram. |
| CA-018 | atendido |40APIdedefaults/enums/termos/categorias/limites/moeda/CRUDsemgravaçãoinválida. |
| CA-019 | atendido |PUTpausado/ativo-only/parcial/omitido/null/[]/invariantes/schema versus404;API/UI. |
| CA-020 | atendido |7UIcomcomponente real/fakes,criar/editar/listar/toggle/ajuda/zero/erro/escape;browserE2Enãoexigido/nãoexecutado. |
| CA-021 | atendido |PGlitePostgreslocal bloco2×/preservação/defaults/constraints/preflight/atomicidade;schemaAPI/cache explícito. |
| CA-022 | atendido |Spies/frozenhash/commitambíguo/restart/>48h/cardúnico/aparições,rejeiçõessemreabrir; testes. |
| CA-023 | atendido |Whitelist/clienteestrito/logssemconteúdo/cupom/URLs/tokens,rejeiçãolegítimasemremoto;testes. |
| CA-024 | atendido |CLI exemplo e testesJSON/equivalência/códigos0/2/1/semcredenciais/socketbloqueado. |
| CA-025 | nao atendido |Fechamentopós-ciclocurto241/240+timeoutderajada; rodada anteriorinterrompidaexternamente. Semskip/relaxamento. |
| CA-026 | atendido |Simulaçãomesmoshashes/carga130/130/corpus/limites/custosseparados/variabilidade eREADME/migração/rollback/etapa3,semSLAinventado. |

#### Decisão e continuidade

**20/21 requisitos atendidos,1 parcialmente atendido(RN-004);25/26 critérios atendidos,CA-025 não atendido.** ResidualVAL-ET2-003 corrigido pelo ciclo curto e revisado; **VAL-ET2-005 permanece bloqueante de validação** pelo fechamento de regressão ainda negativo, não por um SLA deprodução inventado. Estado`em_implementacao`, aprovação v1 mantida, T07/proteção de fechamento reabertos. Não há aceite parcial ou desvio material.

Próximo comando: **`/sdd-implementar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`** para diagnóstico de rajada/espera de executor/progresso com evidência temporal/estado/fatal e preservação de todos os241 testes. Não repetir outra suíte cegamente atéverde nem concluir causa ambiental com base em perfis/metadados ou stackúnica. Não propor mudança deSQLite/durabilidade/testes apenas para fechar o watchdog. Se houver impedimento indispensável deambiente comprovado,registrá-lo com suas evidências emvezdeinferi-lo.

Limites:heurísticas/corpus sintético semdetectoruniversal,Node20/browserreal/Telegram/Supabase/VPS/produção nãoverificados;SQLlocal não validaRLS/extensõesreais. Sem novascontas,publicaçãoGit/deploy/SQLremoto,identidade/hashhistórico,imagens/auth/etapa3. Nenhum staging/commit/push/merge autorizado ou realizado.

**Histórico preservado:** os resultados abaixo correspondem aos comandos anteriores de validação. Referências a “atual” e pendências nos registros antigos descrevem aquelas rodadas; não substituem a matriz e a decisão desta nova validação acima.

### Validação após segunda retomada — 2026-11-05 — não aprovada

Raiz/runtime global, `_comum.md`/`validar.md`/PRD integral e `CLAUDE.md`, aprovação v1 e estado `em_validacao` confirmados. Base `main / 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a`, único worktree desta cópia; sem `.sdd-lite` local ou AGENTS.md. Toda implementação, testes, PRD e prompts existentes são preexistentes e serão preservados. Nenhuma autorização para publicação/contas/SQL remoto/etapa3.

Intenção: verificar extração contextual e filtros ponta a ponta sem perder coleta, decisões congeladas/hash e dados. **QV01 — revisão e verificações; QV02 — contraprovas/ciclo curto; QV03 — matrizes e decisão: concluídos na validação.** Resultado da entrega: **`em_implementacao`**, sem aceite final. Aprovação de requisitos v1 preservada: não houve mudança material. Evidências anteriores não são promovidas automaticamente a resultado atual.

#### Escopo, revisão e ciclo curto

O diff preexistente do bot/API/UI/SQL/testes/documentação é previsto/necessário ao PRD. Mudanças prévias nas assertions de texto bruto/contexto/cupom e SQLite5 são mudanças de semântica aprovadas, com controles positivos/negativos, não exclusão de regressões. Injeção de dependências e runners offline são necessários aos testes; PGlite permanece fora do projeto. Os três prompts não rastreados são trabalho preexistente do usuário e não foram alterados. Nenhum desvio material ou modificação fora do escopo foi identificado; nada foi staged/commitado/publicado.

**VAL-ET2-001, residual adicional — corrigido no ciclo curto:** contraprova sintética `SSD Kingston R$ 299,90 - Frete a calcular,USADO` burlava o veto global. Das38 verificações cruzadas iniciais,37 passaram e esta falhou. Antes da correção, o novo arquivo `bot/tests/test_validacao_final_etapa2.py` reproduziu duas falhas em quatro métodos (extração/avaliação e pipeline). Causa restrita à constante `_SEPARADOR_TRECHO`: vírgula sem espaço não abria cláusula, e o fallback de frete removia a condição.

Correção localizada de uma expressão e comentário, permitida por `validar.md`: separar vírgula diante de conteúdo não numérico, mesmo sem espaço, preservando vírgula antes de número/formatos ambíguos. A primeira tentativa exigia letra; revisão independente encontrou regressão em `, (USADO)`, `, [USADO]` e `, "USADO"` anteriormente reconhecidos. Essa tentativa não foi aceita: expressão final usa `,\s*(?=[^\s\d])`, que conserva pontuação e impede retrocesso de espaços antes de número. Teste ampliado com oito caudas de condição; númerosBRL/ambíguos, URL/cupom negativos e descarte durável também cobertos. **Todos os230 métodos preexistentes ficaram intactos.** Nenhum requisito/contrato/arquitetura/permissão/risco foi alterado; mudança objetiva, pequena e reversível. Única alteração de produção desta validação: constante/comentário em `bot/src/extractor.py`.

Revisão independente somente leitura: primeiro recorte rejeitou três condições parentetizadas/entre aspas (10 comparações e15 controles monetários); após ajuste final aprovou **3 métodos síncronos ampliados e23 controles adicionais**, com socket bloqueado. Sem nova contraprova confirmada no recorte, sem nova regra ou redesign; não é aprovação SDD integral. Demais achados concretos de extração das validações históricas passam atualmente nos arquivos preservados `test_validacao_etapa2`, `test_revalidacao_etapa2`, `test_correcao_etapa2` e `test_segunda_retomada_etapa2`.

#### Achado ainda aberto

**VAL-ET2-005 — bloqueante de validação, CA-025/RN-004 e garantia de RF-006:** a suíte completa pós-correção executou234 testes em78,683s: **233 passaram, um erro, zero falhas de assertion/skips**, saída1. `test_pipeline.TestPipeline.test_falha_config_inicial_nao_aceita_tudo_e_refresh_preserva_snapshot` excedeu o watchdog de3s em `test_pipeline.py:173`, após carregar snapshot válido vazio e acordar workers. Trace: `aguardar` → `finalizada` → `EstadoLocal.evento` → `_executar` → `asyncio.shield`, cancelamento pelo `wait_for` e `TimeoutError`. Não há prova de perda de dados, de reavaliação indevida ou de defeito específico no extrator; **também não há causa comprovada para descartar a falha como ambiental**.

Na mesma execução houve avisos de tasks lentas de4,250s na coleta, até1,408s na migração e4,356s no SDK; correlação temporal não estabelece causa. O caso isolado passou em0,509s; conjunto dirigido incluindo todo `tests.test_pipeline` e regressões passou121/121 em6,177s. Esses verdes delimitam a reprodução intermitente, **não fecham o achado nem substituem a suíte completa final**. Não foi aumentado timeout, alterada espera/assertion, pulado teste nem realizada repetição completa até obter verde. Falhas temporais anteriores permanecem observações históricas, não diagnóstico causal deste episódio.

Encaminhamento: diagnosticar com instrumentação local transitória de estados/latências/worker/SQLite na execução completa e caso isolado; distinguir lentidão de I/O/scheduling de falha de progresso/configuração. Se confirmar defeito, corrigir na implementação com regressão equivalente; se confirmar impedimento indispensável do ambiente, documentar evidência e estado apropriado. Depois reexecutar suíte completa sem relaxar garantias e solicitar `/sdd-validar`. Não atribuir culpa ao ambiente ou declarar regressão funcional específica sem comprovação.

#### Comandos e verificações atuais

Em `bot/`, prefixo real **`wsl --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`**, Python3.12.3, Linux6.6.87.2/WSL2/glibc2.39, fontes em`/mnt/c`; SDKs fixados. Em API/UI: Windows/Node**24.11.1**, não Node20. Sem instalação/upgrade nesta validação. Benchmarks sequenciais, sem build/testes concorrentes iniciados pelo agente; host/filesystem não isolados.

| Comando/procedimento | Resultado e limite |
|---|---|
| `python -B -m unittest discover -s tests -q` antes do ciclo curto |230/230 passaram, sem skips. Prova do código recebido, não do fechamento pós-correção. |
| `python -B -m unittest tests.test_validacao_final_etapa2 -v` antes da correção |4 métodos, duas falhas, saída1; causa funcional reproduzida sem rede. |
| `python -B -m unittest tests.test_validacao_final_etapa2 tests.test_segunda_retomada_etapa2 tests.test_revalidacao_etapa2 tests.test_validacao_etapa2 tests.test_correcao_etapa2 tests.test_extracao tests.test_decisoes_etapa2 tests.test_filtros_etapa2 -q` após primeira expressão |105/105 em1,648s, saída0; ainda não cobria a regressão que o revisor encontrou depois. |
| `python -B -m unittest discover -s tests -q` após expressão final/testes ampliados |**234 executados/233 passaram/um erro/78,683s**, zero skips; saída1, VAL-ET2-005 aberto. Warnings GoTrue deprecado e tasks lentas visíveis. |
| `python -B -m unittest tests.test_pipeline.TestPipeline.test_falha_config_inicial_nao_aceita_tudo_e_refresh_preserva_snapshot -v` |1/1 em0,509s, saída0; não reproduziu timeout isoladamente, causa não isolada. |
| `python -B -m unittest tests.test_pipeline tests.test_validacao_final_etapa2 tests.test_segunda_retomada_etapa2 tests.test_revalidacao_etapa2 tests.test_validacao_etapa2 tests.test_correcao_etapa2 tests.test_extracao tests.test_decisoes_etapa2 tests.test_filtros_etapa2 -q` |121/121 em6,177s, saída0, sem skips. Inclui quatro métodos novos no código final e regressões históricas intactas. |
| `python -m pip check` |No broken requirements found, saída0. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` |Saída0; SSDKingston NV2 - 1TB - NVMe,299,90/399,90,`AbC123`,URL/query/caixa preservadas, regra1 aceita. CLI sem credenciais/rede, equivalência e códigos0/2/1 também verificados em `TestPreviaEtapa2`. |
| `npm test` em`backend/` |40/40 passaram, zero skips; CRUD/service/model/rotas com fakes, sem servidor/Supabase reais. |
| `npm test` em`frontend/` |7/7 passaram, zero skips; componentes reais com hooks/API/Auth falsos, **não browserE2E**. |
| `npm run lint` em`frontend/` |Sem warnings/erros, saída0. |
| `npx --no-install tsc --noEmit --incremental false` em`frontend/` |Saída0, sem diagnósticos. |
| Build local Next14.2.5 com comando abaixo |Compilação/lint/tipos e6/6 páginas, saída0. Somente valores fictícios, sem login/API externos. |
| SQL local com comando abaixo |PostgreSQL18.6/PGlite0.5.11; bloco aditivo aplicado duas vezes, dados/defaults/constraints/preflight/atomicidade aprovados. Sem schema/RLS/extensões Supabase reais. |
| `node -e` +`spawnSync(process.execPath,['--check',file])` para os quatro JS alterados |Sintaxe de controller/model/routes/service de filtro aprovada, saída0. Sem scripts lint/build/typecheck backend configurados; não se declara execução deles. |
| AST local `ast.parse` em`src/*.py`, `tests/test_*.py`, `previa.py`, `medir_extracao.py`, `simulacao.py` |45 arquivos parseados,234 métodos de teste; não é lint/mypy nem cobertura percentual. |
| `git diff --check`, `git status --short --branch` e revisão do diff/arquivos novos |Saída0 no diff-check, somente avisosLF/CRLF; sem staging/commit, arquivos do ciclo restritos ao extrator/teste novo/PRD. Status conserva todo trabalho anterior. |
| `git diff --exit-code -- bot/src/dedup.py bot/src/main.py bot/src/recuperacao.py bot/src/sinais.py bot/src/midia.py bot/bot.py bot/requirements.txt bot/dealbot.service bot/simulacao.py backend/package-lock.json frontend/package-lock.json backend/src/middlewares/auth.js frontend/hooks/useAuth.ts frontend/lib/api.ts` |Saída0/vazia; arquivos protegidos inalterados contraHEAD. |
| Conferência estrutural local do PRD/teste/extrator via Python |21 requisitos/26 critérios,19/25 atendidos, estado/aprovação corretos e ausência de whitespace final. Primeira tentativa do helper falhou no delimitador acentuado do título; corrigido para âncorasASCII e passou, sem alteração funcional ou arquivo temporário. |
| Revisão de erros/contratos/segurança aplicável |Zod, merge parcial, schema explícito, escape React, schemes, projeção remota, logs e falhas de migração conferidos nas fontes e testes. Auth central inalterada; sem auditoria universal/dependências remotas ou pentest de produção. |

Build executado em`frontend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['node_modules/next/dist/bin/next','build'],{stdio:'inherit',env:{...process.env,NEXT_PUBLIC_SUPABASE_URL:'https://supabase.invalid',NEXT_PUBLIC_SUPABASE_ANON_KEY:'fake-anon-key',NEXT_PUBLIC_API_URL:'http://127.0.0.1:3333/api',NEXT_TELEMETRY_DISABLED:'1'}});process.exit(r.status??1)"
```

SQL executado em`backend/`:
```powershell
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['tests/sql-etapa2.local.mjs'],{stdio:'inherit',env:{...process.env,DEALBOT_TEST_POSTGRES_URL:'',DEALBOT_TEST_PGLITE_MODULE:'C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql/node_modules/@electric-sql/pglite/dist/index.js'}});process.exit(r.status??1)"
```

#### Desempenho atual e variabilidade preservada

Comando exato em`bot/`: **`python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1`**, saída0.

- 130 recebidas/produtos/aprovadas, zero descartes/duplicatas/falhas; janela monotônica291,910336206–296,789919675, inícioUTC`2026-11-05T16:37:12.242546+00:00`, **4,879583s/26,641618 ofertas/s**. Live30: p50/p95/máx**299,035/393,980/423,628ms**; histórico100:**3213,844/4643,282/4850,491ms**; heartbeatmáx**1,892326ms**.
- Workers configurados/máximos4/1; filas inicial/pico/final live0/9/0, histórico0/100/0, mídia0/113/113. Mídia17 prontas,112 pendentes/uma processando,18 tentativas/zero falhas; não foi drenada para melhorar latência. Ambas as origens progrediram antes do fim da outra; página100, buffer100, zero task por mensagem.
- Hash live`606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb`, histórico`27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805`, mesmos parâmetros/delays/instrumentação. Uma carga de filtros e130 de cada operação fake da oferta;18 buscas de mídia/17 vínculos. Sem enriquecimento por mensagem.

Comando **`python -B -m medir_extracao --iteracoes 100 --limites`**, saída0:28 casos sintéticos imutáveis, seed42, três aquecimentos,2800 amostras, SHA256`1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c`. Janela2,809010s/996,79mensagens/s. p50/p95/máxµs: extração**186,512/10796,877/14354,537**; extração+avaliação**205,940/10838,283/14375,536**; só avaliação2500 válidas**19,799/30,306/72,914**; preparo snapshot100 amostras**15,399/33,198/276,381**. Longa p95/max11022,261/11445,875µs; adversarial12402,469/14354,537µs, sem explosão observada nessa amostra.

Regras no limite:10×50termos/lista×100caracteres; preparo único115176,589µs,20 avaliações por entrada sem reextração. Curta p50/p95/máx1555,954/1631,519/1700,332µs; longa2672,422/2718,931/2758,940µs; adversarial1518,147/1576,109/1679,828µs. Snapshot reutilizado, sem espera/rede na lógica pura; derivação compartilhada conferida no teste e fonte.

A medição atual de4,879583s **não apaga** os34,241864s/3,796522ofertas/s do fechamento anterior nem comprova sua causa. Baseline da segunda retomada4,713740s/27,578949ofertas/s, com hashes/carga iguais; houve variação expressiva entre execuções. CPU conjunto p95 anterior10849,022µs e atual10838,283µs são próximos, mas não explicam causalmente o custo SQLite/fake remoto/scheduler. Nenhum SLA novo, garantia de produção ou causalidade ambiental inferida. Investigação/registro atende à exigência documental de CA-026; timeout de teste obrigatório continua impeditivo separado.

#### Matriz atual de requisitos — não substitui matrizes históricas abaixo

| ID | Resultado | Implementação/verificação atual |
|---|---|---|
| RF-001 | atendido | Extrator/derivados transitórios e conteúdo; regressões sintéticas preservadas e novo ciclo curto mantêm condição/variante/limites de frase, sem duplicar texto persistido. |
| RF-002 | atendido | Papéis monetários/grupos por cláusula/centavos; 121 dirigidos e corpus, dois objetos inline/igual preço, especificações rotuladas e negativos frete/parcela/anterior passam. |
| RF-003 | atendido | `telegram.py`/SQLite; testes tipados live/raw/UTF-16/emoji/botões/links e restart passaram na suíte atual, sem RPC adicional. |
| RF-004 | atendido | Cupons com contexto/categorias por objeto/sete categorias e fallback/adaptador; controles positivos/negativos passaram, sem formato real inventado. |
| RF-005 | atendido | Filtros preparados/normalização única/centavos; OR/AND/frase/teto zero/desconhecido/rejeições por regra e conteúdo além do título passaram nos dirigidos. |
| RF-006 | parcialmente atendido | Veto local/global/modos/snapshot inválido e schema passam; progresso após primeiro refresh válido excedeu3s uma vez na suíte completa, isolado verde não fecha005. |
| RF-007 | atendido |40API/7UI, merge parcial/omitido/null/[]/pausado/erros/zero, lint/tipos/build e sintaxe atuais aprovados; contrato/auth mantidos. |
| RF-008 | atendido | SQLite5 aditivo/rollback, decisões produtoJSON/hash soberano/restart, spies, rejeição terminal e whitelist; testes atuais passaram. |
| RF-009 | atendido | Diagnóstico pequeno separado, logs saneados, CLI com módulos produtivos/JSON/códigos0/2/1 sem tokens/rede; testes atuais e comando exemplo. |
| RF-010 | atendido | README/PRD com semântica, antes/depois sintético, comandos/resultados/limites/migração/rollback/continuidade, inclusive falha atual exposta. |
| RN-001 | atendido | Curta com evidência aceita; divulgação/desconto isolados e múltiplos claros rejeitados; grupos válidos não viram múltiplos. |
| RN-002 | atendido | Global precede interesse, veto local só na própria regra e ausência de interesse requer snapshot válido; controles passam. Incerteza de progresso do refresh registrada emRF-006. |
| RN-003 | atendido | Congelamento/retry/decisões antigas/hash com spies e restart aprovados; sem reprocessamento em massa. |
| RN-004 | parcialmente atendido | Coleta/paginação/gerações/limites/async/mídia/sinais/retenção passaram; fechamento integral da regressão de cache/pipeline falhou uma vez,005 permanece aberto. |
| RN-005 | atendido | Dedup/janela48h inalterados; reconciliação/aparições/locks/checkpoints aprovados; nenhum hash histórico recalculado. |
| RN-006 | atendido | Sem remoto/contas/publicação, prompts e trabalho preexistente preservados. |
| RNF-001 | atendido | Extração/avaliação locais, sem IA/redirect/loja/RPC/sleep novo; socket/fakes e revisão do caminho produtivo. |
| RNF-002 | atendido | Preparo por refresh e derivados compartilhados; corpus longo/adversarial e limites medidos, sem explosão observada; não prova complexidade universal. |
| RNF-003 | atendido | Number/null,centavos,SQL aditivo,JSON/SQLite/IDs legados,categorias sincronizadas; pins/auth/stack preservados. |
| RNF-004 | atendido | Campos internos locais/whitelist/logs/retencão/diretório privado e fixtures sintéticas conferidos; sem exposição de dados reais. |
| RNF-005 | atendido | Suíte falha/dirigidos verdes diferenciados, zero skips e causa não estabelecida explicitados; nenhuma assertion/watchdog alterada para verde. |

#### Matriz atual de aceitação

| ID | Resultado | Procedimento/evidência atual |
|---|---|---|
| CA-001 | atendido | `test_extracao`+corpus: chamada genérica ignorada e títuloSSD/modelo/hífens preservados. |
| CA-002 | atendido | CurtaSSD99 aceita; divulgação/cupom/URL/rodapé não autorizam matching; negativos novos preservados. |
| CA-003 | atendido | De/por299,90/399,90 e frete15 não vira preço; formato/serviço testados com socketbloqueado. |
| CA-004 | atendido | Parcela+vista899 e apenas parcelas nulo, inclusive com serviço nas especificações, sem derivar total. |
| CA-005 | atendido | Desconto/mínimo/modelo não são preço e anterior inconsistente não gera badge falso; Python+UI atuais. |
| CA-006 | atendido | BRL/inteiro/NBSP/zero/centavos/faixa/JSON, novo teste preserva1,234/1, 234/1,NBSP234 nulos; API e UI passam. |
| CA-007 | atendido | Contraprovas históricas e novas: múltiplos inline/multilinha com preços iguais/diferentes, terminal sem remoto; de/por não vira múltiplo. |
| CA-008 | atendido | Prioridade comercial/curto/query/fragmento/parênteses/HTTP(S), testes atuais e CLI exemplo. |
| CA-009 | atendido | SDKfixado live/raw com emoji/UTF-16/entidades/botões, sem refetch: `test_contexto` e transporte passaram. |
| CA-010 | atendido | Migrações0–4→5 reais locais, rollback/restart/contexto/decisões/hash/mídia/IDs/fronteiras aprovados. |
| CA-011 | atendido | CupomAbC123 contextual, isolado/incompleto/ambíguo nulo, positivos/negativos atuais. |
| CA-012 | atendido | Cadeira/headset/jogo, limites de token/incerto e categorias sincronizadas; `todos` inválidoAPI/Python. |
| CA-013 | atendido | Qualquer/todas/OR/lista vazia/categoria/teto, regras preparadas e dirigidos atuais. |
| CA-014 | atendido | Frase normalizada contígua, não dispersa/colada entre cláusulas; Unicode/tokens, sem fuzzy. |
| CA-015 | atendido | Desconhecido só falha teto, outro interesse aceita; IDs/razões por regra preservados. |
| CA-016 | atendido | Global qualquer/todas e local não sobrepõem; novo veto após `Frete a calcular,USADO` e delimitadores testados inclusive pipeline. |
| CA-017 | atendido | Globais semmatch/sem ativos, config inválida/desconhecida não vira[] e conserva snapshot; testes funcionais passam. Timeout de progresso do refresh é005/CA025. |
| CA-018 | atendido |40API: enums/listas/limites/frases/duplicatas/moeda/defaults/tipos, sem gravação inválida. |
| CA-019 | atendido | API+UI: pausado/ativo-only/merge/omitidos/null/[]/erro schema versus inexistente. |
| CA-020 | atendido |7UI com componentes reais/fakes: criar/editar/listar/toggle/ajuda/zero/erro/XSS. BrowserE2E não exigido/não executado. |
| CA-021 | atendido | PGlite/Postgres executou bloco duas vezes+constraints/preflight; API/cache exigem colunas e não escondem schema. |
| CA-022 | atendido | Decisão/hash congelados/restart/commit ambíguo/>48h e spies sem reextração/avaliação/hash novo, mesmo card/aparição. |
| CA-023 | atendido | Cliente estrito/whitelist, logs sem texto/termos/cupom/URL/token, descarte sem remoto; testes atuais passam. |
| CA-024 | atendido |CLI exemplo e `TestPreviaEtapa2`: equivalência offline/semcredenciais/socketbloqueado/JSON/códigos0/2/1. |
| CA-025 | nao atendido |Obrigatória suíte final não passou integralmente:234/233+um timeout. Caso isolado e121 dirigidos verdes não fecham causa. Zero skips/relaxamentos. |
| CA-026 | atendido |Simulação130/130/mesmoshashes, limites/progresso/corpus e custo separados, variação34s→4,9s registrada sem causalidade/SLA; README/migração/rollback/etapa3. |

#### Decisão, limites e próximo passo

**19/21 requisitos atendidos,2 parcialmente atendidos (RF-006/RN-004)**; **25/26 critérios atendidos, CA-025 não atendido**. VAL-ET2-001 residual corrigido e revisado; **VAL-ET2-005 permanece bloqueante de validação**. T07 e proteção de fechamento das regressões reabertos. Estado`em_implementacao`, não`concluido` nem`parcialmente_concluido`. Aprovação v1 continua válida.

Próximo passo: **`/sdd-implementar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`** para diagnóstico/evidência do timeout sem retirar controles, depois nova validação. Não executar outra rodada cega só até verde. Corpus/heurísticas não cobrem qualquer post; Node20, browserreal, Telegram/Supabase/VPS/produção não verificados, SQL local não valida todo ambiente Supabase. Autenticação nova, algoritmo de identidade, recálculo histórico, imagens, etapa3, publicação e SQL remoto fora do escopo. Nenhum commit/push/merge/deploy autorizado ou realizado.

**Histórico de validação:** os resultados abaixo precedem o fechamento da segunda retomada da seção15. O implementador retornou a `em_validacao`; ainda não houve nova validação SDD desses últimos ajustes. Reprovações/matrizes anteriores permanecem como evidência, não como estado de aceite atual.

### Nova validação após retomada — 2026-11-03 — REPROVADA

Invocação explícita de `sdd-validar` para este PRD. Raiz `C:/Users/Alexandre_HP/Documents/DellBot/dealbot`, runtime global, leitura integral de `_comum.md`/`validar.md`/PRD, instruções `CLAUDE.md`, estado `em_validacao`, versão1/aprovação e base `main / 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a` confirmados; único worktree desta cópia, sem runtime local ou AGENTS.md. Todo o diff de implementação, regressões e prompts é preexistente e será preservado.

Intenção: verificar extração contextual e regras ponta a ponta, preservando coleta, decisões congeladas, hash e dados. Roteiro concluído: **NV01 — revisão de requisitos/correções/contratos; NV02 — verificações locais completas e contraprovas; NV03 — matrizes e decisão**. Resultados históricos abaixo não são automaticamente promovidos a aprovação atual. Sem commit, deploy, credenciais, SQL remoto ou etapa3.

**Decisão: `em_implementacao`.** As contraprovas originais e todos os212 testes anteriores passaram, mas quatro assertions novas em três métodos reproduzem perdas de conteúdo e associação incorreta de produtos/preços. Não há aceite parcial, alteração de requisito nem invalidação da aprovação v1. Nenhum módulo de produção foi alterado durante esta validação; criados somente cinco testes sintéticos e este registro. Não é suficiente passar o corpus feliz ou os casos exatos já corrigidos.

#### Achados atuais e critérios de fechamento

**VAL-ET2-001 — residual, alta/bloqueante: serviço não monetário ainda apaga condição e burla veto.**

- `bot/src/extractor.py:278-280`: fallback de `_SERVICO_DESCRICAO.search` corta toda a cauda a partir do marcador, quando não há um intervalo monetário/gratuito reconhecido para retirar.
- Entrada sintética: `SSD Kingston R$ 299,90 - Frete incluso, USADO`; global id1 com bloqueio `usado`, interesse id2 permissivo. Real: título/conteúdo `SSD Kingston`/`ssd kingston`, preço299,90, `aceita_por_regra`/2; global informa `sem_correspondencia`. Esperado: preservar condição `usado`, `bloqueio_global`/1 e nenhum aceite.
- Controle: `Frete grátis, USADO` preserva a condição e veta; o defeito não foi resolvido para serviço não monetário explícito. O corte é a mesma causa de preservação incompleta, não pedido de fuzzy ou enriquecimento.
- Impacto RF-001/005/006, RN-002 e CA-016. Fechamento: remover apenas o serviço identificado/preservar cláusula descritiva, com controle de cupom/rodapé e serviços que não podem fabricar produto. Regressão `test_condicao_apos_frete_incluso_continua_sujeita_ao_veto` falha.

**VAL-ET2-003 — residual, média/importante impeditivo: campo rotulado de componente ainda é falso produto.**

- `bot/src/extractor.py:293-318`: qualquer objeto reconhecido fora da pequena lista de especificações pode trocar `ultima_descricao`; um campo explícito de especificação é associado ao preço final como se fosse uma segunda oferta.
- Entrada: `Notebook Dell\nR$ 3500,00\nProcessador: Intel Core i5\nÀ vista R$ 2999,90\nhttps://loja.example/notebook`. Real: produto nulo e `multiplas_ofertas`. Esperado: notebook por2999,90, preservando `Processador: Intel Core i5` na descrição. O campo não tem preço próprio nem link independente; os dois valores pertencem ao notebook.
- Controle: SSD com `Capacidade 1 TB` entre valores passou; ofertas reais separadas de SSD/headset continuam ambíguas. Não se exige classificador universal: há rótulo de campo e continuidade explícita do anúncio único.
- Impacto RF-002 e CA-004/007. Fechamento: usar evidência de independência/continuidade, sem tratar somente palavra de categoria como segundo produto; preservar detecção de processador realmente anunciado com preço próprio. Regressão `test_campo_processador_do_notebook_nao_e_oferta_independente` falha.

**VAL-ET2-004 — novo, alta/bloqueante: dois objetos com preços próprios na mesma linha viram um card.**

- `bot/src/extractor.py:310-344`: grupo/conjunto é identificado pelo número da linha. Há um único `ultima_descricao` para todos os valores da linha; `finais[0]` ganha precedência sem distinguir o objeto a que pertence. Deduplicar montantes também esconde produtos diferentes de mesmo preço.
- Entrada: `SSD Kingston R$ 350,00 / Headset Logitech por R$ 149,90\nhttps://loja.example/ofertas`. Real: título `SSD Kingston - Headset Logitech`, preço149,90 e aceite com snapshot vazio (`aceita_sem_interesses`). Esperado: `multiplas_ofertas`, produto nulo, rejeição terminal; não associar preço do headset a um card composto/SSD.
- Segunda prova: `SSD Kingston R$ 299,90 / Headset Logitech R$ 299,90\nhttps://loja.example/ofertas` também publica um card. Dois objetos têm evidência comercial própria, mesmo com valores iguais. Substituir `/` por quebra de linha no primeiro caso faz o detector funcionar.
- Impacto RF-002, RN-001 e CA-007. Não se pede desmembramento/identidade nova nem detector de todo formato; são dois nomes de objetos e preços explícitos separados pelo delimitador que o extrator já usa.
- Fechamento: associar spans/cláusulas descritivas a seus valores antes de aplicar precedência/deduplicação de montantes, mantendo de/por/parcela/frete do mesmo produto. `test_produtos_com_precos_proprios_na_mesma_linha_nao_viram_card_unico` tem dois subcasos falhos.

**NV-OBS-001 — importante, custo redundante (RNF-002), sem novo SLA.** `_precos` chama `_descricao_linha` em314 e `_descricao` repete o mesmo derivado em366. A retomada já perfilou os scans/normalizações adicionais; a revalidação confirmou p95 conjunto~14,911ms, versus~5,588ms antes da retomada. Preparação de regras é reutilizada corretamente, mas o derivado descritivo por linha é recalculado, não apenas consumido por dois cálculos distintos. RNF-002 fica parcialmente atendido nessa dimensão explícita; considerar computá-lo uma vez por mensagem durante a correção, sem engine paralelo/estado global ou alteração semântica. Não bloquear por um orçamento numérico inexistente nem prometer que todo texto tem custo linear a partir de um corpus.

As falhas exigem vários blocos de extração/associação e controles cruzados; não se aplicou ciclo curto de produção neste comando. Requisitos continuam os mesmos, sem migração/dependência/permissão nova. Os pontos positivos persistem: decisões/hash congelados, whitelist remota dupla, precisão em centavos, contexto UTF-16 durável, snapshot validado, update parcial/pausado e UI com escopos explícitos.

#### Verificações executadas nesta nova validação

Comandos Python em `bot/`, com prefixo `wsl --exec /mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`; npm em seu serviço. Ambiente confirmado: Python3.12.3, Telethon1.36.0, Supabase2.9.1, HTTPX0.27.2, Storage3 0.8.2, dotenv1.0.1; Node **24.11.1/Windows**, não Node20. Fontes/contas/fixtures privadas não foram abertas. Nenhuma instalação ou upgrade.

| Comando/procedimento | Resultado real | Limite |
|---|---|---|
| `python -B -m unittest discover -s tests -q`, antes dos novos testes | **212/212 passaram, 92,291s**, zero falhas/erros/skips, saída0 | Suíte/SDKs/SQLite/processos locais; warnings GoTrue e tarefas asyncio lentas visíveis. Nenhuma intermitência anterior reapareceu nessa execução; não prova causa resolvida. |
| `python -B -m unittest tests.test_validacao_etapa2 tests.test_correcao_etapa2 -q` | **23/23 passaram, 0,250s**, saída0 | Os seis testes originais e17 da retomada foram preservados. VAL-ET2-002 e entradas exatas anteriores de001/003 confirmadas. |
| Contraprovas por stdin com socket bloqueado e fixtures sintéticas | Três causas acima reproduzidas; controles de quebra de linha/capacidade/frete grátis passaram | A primeira sonda via pipe PowerShell perdeu caracteres acentuados. Essa observação foi descartada como prova de preço à vista; repetida com escapes Unicode ASCII e texto preservado, além dos testes UTF-8 em arquivo. Não é falha do extrator de encoding. |
| `python -B -m unittest tests.test_revalidacao_etapa2 -v` | **5 métodos, quatro assertions falhas em três métodos, dois controles passaram, 0,024s**, zero erros/skips, saída1 | Duas falhas pertencem aos subcasos do mesmo método inline. Sem skip/expectedFailure ou asserts enfraquecidos. |
| `python -B -m unittest discover -s tests -q`, após regressões e sem build/benchmark concorrente | **217 métodos, quatro assertions falhas nos três métodos novos, 98,823s**, zero erros/skips, saída1 | Os212 anteriores e dois controles novos passaram; não chamar de suíte aprovada. |
| `npm test` backend | **40/40 passaram**, zero falhas/skips, 750,134ms | Serviço/model/controller/router e auth central com dependências falsas. |
| `npm test` frontend | **7/7 passaram**, zero falhas/skips, 1237,910ms | UI real transpilada/renderizada com hooks/API/Auth falsos; cobre fluxo/estado/erros, não browser E2E. |
| `npm run lint` frontend | Sucesso, sem warnings/erros ESLint, saída0 | Configuração existente. |
| `npx --no-install tsc --noEmit --incremental false` frontend | Sucesso, saída0 | Sem instalar TypeScript. |
| Next build com env fictício, comando abaixo | Sucesso: compilação/lint/tipos e seis páginas; `/filtros`4,26kB, first load160kB | Só `.env.example` encontrado, sem credencial; não iniciou servidor de produção. |
| SQL local, comando abaixo | **PostgreSQL18.6/PGlite0.5.11: aplicação dupla, preservação, defaults, constraints e preflight aprovados** | Instância descartável em memória, sem Supabase/RLS real; não é dependência de produção. |
| `python -m pip check` | **No broken requirements found**, saída0 | Nenhum pin alterado. |
| `node --check` em todos JS/MJS de `backend/src`/`backend/tests` | **23 arquivos aprovados**, saída0 | Não há script backend lint/build/typecheck para declarar aprovado. |
| AST de fontes/runners/testes Python em memória | **45 arquivos parseados, 217 métodos test_**, saída0 | Não escreve bytecode e não substitui testes. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` | Saída0, 299,90/399,90, título descritivo, `AbC123`, URL/query/caixa preservadas, `aceita_por_regra`/1 | CLI offline com códigos0/2/1 e rede bloqueada também exercitada na suíte. Não absolve os novos negativos. |
| Leitura/diff/arquivos novos/contratos e teste de UI com API falsa | Nenhuma alteração de auth, identidade, imagens, dependências, rede de enriquecimento ou implementação da etapa3 | Mock de UI permitido pelo PRD, sem browser nem login real. Privacidade de logs/projeção confirmada pela suíte. |
| `git diff --exit-code --` para arquivos protegidos | Vazio, saída0: dedup/main/recuperação/sinais/mídia/legado/requirements/unit/locks/auth central/hook/api frontend | Arquivos protegidos não alterados; todo o diff da entrega anterior preexistente e preservado. |
| `git diff --check` padrão e conferência estrutural dos arquivos novos | Saída0, somente avisos LF/CRLF; PRD v1/aprovação/estado,21 itens de requisito e26 critérios únicos confirmados; cinco testes novos parseados e sem whitespace final | Tentativa com override `core.autocrlf=false` apontou CR de linhas preexistentes como whitespace; repetida na configuração real do checkout, sem editar conversões/arquivos. Primeira checagem do PRD via pipe falhou ao procurar cabeçalho acentuado; repetida com seletor ASCII, sem alterar o documento para acomodar a ferramenta. |

Comandos exatos adicionais, reutilizando somente ferramentas instaladas:

```text
# frontend/
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['node_modules/next/dist/bin/next','build'],{stdio:'inherit',env:{...process.env,NEXT_PUBLIC_SUPABASE_URL:'https://supabase.invalid',NEXT_PUBLIC_SUPABASE_ANON_KEY:'fake-anon-key',NEXT_PUBLIC_API_URL:'http://127.0.0.1:3333/api',NEXT_TELEMETRY_DISABLED:'1'}});process.exit(r.status??1)"

# backend/ — sem URL de banco, apenas instância local em memória
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['tests/sql-etapa2.local.mjs'],{stdio:'inherit',env:{...process.env,DEALBOT_TEST_POSTGRES_URL:'',DEALBOT_TEST_PGLITE_MODULE:'C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql/node_modules/@electric-sql/pglite/dist/index.js'}});process.exit(r.status??1)"
```

#### Medições repetidas sem mudar runner/datasets

Sequenciais, após testes/build, mesmo WSL/filesystem `/mnt/c`, sem carga concorrente iniciada pelo agente. Não há isolamento do host. Simulação: `python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1`.

- **130 ofertas recebidas/aprovadas/produtos**, zero descartes/duplicatas/falhas; **4,443404s / 29,256846 ofertas/s**. Live p50/p95/máx **178,814/274,883/284,299ms**, histórico **2816,945/4286,875/4416,466ms**; heartbeat máximo **2,052ms**.
- Workers máximos4/1, filas inicial/pico/final live **0/7/0**, histórico **0/100/0**, mídia **0/114/114**;16 prontas,113 pendentes/uma em processamento. Ambas as origens avançaram antes do fim da outra; página máxima100, zero task por mensagem.
- Hashes live `606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb` e histórico `27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805` iguais aos anteriores. Cinco operações20ms por oferta e mídia200ms; medição não espera drenar fotos. Nenhuma melhoria causal/SLA inferido de variações locais.

Corpus: `python -B -c "import asyncio,json,medir_extracao as m; r=asyncio.run(m.medir(100)); r['limites_regras']=m.medir_limites(); r.pop('exemplos'); r.pop('extracao_por_caso'); print(json.dumps(r,ensure_ascii=False,indent=2))"`.

28 casos sintéticos, seed42, três aquecimentos,100 iterações/**2800 amostras**, SHA256 `1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c`. Extração p50/p95/máx **219,545/14872,040/37976,098µs**, conjunto **240,645/14910,842/38025,797µs**, janela3,964335s/**706,30 mensagens/s**. Só avaliação: **21/38,802/125,198µs**,2500 ofertas consideradas válidas; preparo snapshot **15,5/29,6/310,893µs**,100 amostras. Custo substancial versus extrator base/antes da retomada continua exposto, não tratado como otimização. Contraprovas novas ficam nos testes, sem mudar corpus/hash para alterar comparação.

Listas no limite:10 regras,50 termos/lista,100 caracteres/termo,20 avaliações por entrada, sem reextração; preparo único **116755,201µs**, curta **1546,436/1643,492/1681,994µs**, longa **2687,999/2843,759/2862,460µs**, adversarial **1519,084/1596,689/1603,989µs**. Snapshot preparado corretamente; duplicação de descrição é questão separada em NV-OBS-001. Sem rede/espera artificial na lógica pura.

#### Matriz atual — requisitos, regras e não funcionais

| Item | Resultado | Evidência atual |
|---|---|---|
| RF-001 | parcialmente atendido | Título/modelo/hífens e casos originais passam; VAL-ET2-001 residual apaga `USADO` após serviço não monetário. |
| RF-002 | parcialmente atendido | VAL-ET2-002 confirmado corrigido, centavos/BRL/parcela/à vista passam; falso múltiplo de campo e múltiplos inline ainda falham (003/004). |
| RF-003 | atendido | Contexto SDK/live/raw/UTF-16/emoji/botões/restart e links preservados, sem RPC extra; suíte completa atual. |
| RF-004 | atendido | Cupom com evidência/grafia/ambiguidade, sete categorias e fallback/adaptadores vazios; testes atuais e revisão. |
| RF-005 | parcialmente atendido | Avaliador isolado correto, OR/AND/centavos/razões cobertos; descrição truncada compromete correspondência descritiva fim a fim. |
| RF-006 | parcialmente atendido | Tipos/modos/defaults/cache inválido e escopos corretos isoladamente; veto global burlado por conteúdo perdido (001 residual). |
| RF-007 | atendido | API40/UI7, CRUD/PUT parcial/pausados/zero/invariantes/erros, lint/tipos/build atuais; sem mudar auth. |
| RF-008 | atendido | SQLite aditivo real/rollback, JSON/hash soberanos, spies sem reavaliação, commit ambíguo/whitelist; suíte atual passou. |
| RF-009 | atendido | CLI/diagnóstico/IDs/razões/códigos e privacidade testados, motivos terminais/configuração distintos. Dado errado do extrator não é curado pelo diagnóstico. |
| RF-010 | atendido | Documentação, antes/depois, migração/ordem/rollback, comandos/métricas/limitações/continuidade atualizados sem esconder rejeição. |
| RN-001 | parcialmente atendido | Evidência e negativos básicos passam;004 publica card de produtos independentes. |
| RN-002 | parcialmente atendido | Semântica preparada local/global/OR/AND passa;001 residual ainda remove condição do veto. |
| RN-003 | atendido | Decisões/hash antigos soberanos, sem reprocessamento; spies/checkpoints e restart atuais aprovados. |
| RN-004 | atendido | Todos os212 testes anteriores passaram; inbox/ID/paginação/gerações/workers/async/foto/sinais/retenção preservados. Intermitências históricas não reproduzidas nem declaradas resolvidas. |
| RN-005 | atendido | Dedup/janela48h inalterados, aparições/reconciliação/locks testados atualmente. |
| RN-006 | atendido | Sem dados/contas/SQL remoto/publicação, prompts e diff anterior preservados. |
| RNF-001 | atendido | Extração/avaliação locais, nenhuma IA/rede/espera artificial/enriquecimento extra; fakes/socket e fontes revisados. |
| RNF-002 | parcialmente atendido | Snapshot/regra reutilizados e corpus/limites medidos; derivado de descrição/normalização recalculado em duas passagens, NV-OBS-001. Sem SLA inventado. |
| RNF-003 | atendido | Number/null, JSON/SQLite/categorias/IDs compatíveis, pins/locks/auth preservados. |
| RNF-004 | atendido | Logs/projeção remota sem conteúdo/termos/URL/cupom; contexto local com retenção/permissões e fixtures sintéticas. |
| RNF-005 | atendido | Resultados negativos, custo alto, limite do encoding da sonda e históricos preservados; nenhum assert relaxado/skip novo. |

**Resumo:14 atendidos,7 parcialmente atendidos; entrega não aprovada.**

#### Matriz atual — critérios de aceitação

| Critério | Resultado | Procedimento/evidência |
|---|---|---|
| CA-001 | atendido | Chamada+SSD, modelo/capacidade/hífens e título exato cobertos pelos testes atuais aprovados. |
| CA-002 | atendido | Oferta curta, divulgação/grupo e exclusão de URL/cupom/rodapé passaram. |
| CA-003 | atendido | De/por e frete não fornecem atual/anterior nos casos previstos e corrigidos; regressões originais atuais passaram. |
| CA-004 | parcialmente atendido | Parcela/à vista/não derivação e capacidade passam; campo `Processador:` faz perder preço final do único produto (003 residual). |
| CA-005 | atendido | Desconto/mínimo/percentual/modelos/anteriores inconsistentes e card cobertos por Python/UI atuais. |
| CA-006 | atendido | BRL/ambiguidade/limites/zero/centavos e teto zero, inclusive frete grátis, passaram nos testes atuais. |
| CA-007 | parcialmente atendido | Dois objetos em linhas distintas rejeitados; na mesma linha dois subcasos falhos revelam associação/publicação incorreta (004), além do falso múltiplo de especificação. |
| CA-008 | atendido | Links/contexto/schemes/delimitadores/caixa/query/curtos sem redirects testados atualmente. |
| CA-009 | atendido | SDK tipado bruto live/raw/UTF-16/emoji e ausência de RPC extra aprovados na suíte atual. |
| CA-010 | atendido | Bancos antigos reais, migração v5/rollback/contexto/restart e preservação de jobs/decisão/hash/fronteiras/mídia passaram. |
| CA-011 | atendido | Cupom contextual preserva caixa, código isolado/marcador/ambiguidades ficam nulos; testes atuais. |
| CA-012 | atendido | Objetos/categorias/palavras completas, sincronia de categorias e rejeição de `todos` passaram. |
| CA-013 | atendido | SSD/Kingston todas/qualquer, teto/lista vazia/regras alternativas: testes atuais. |
| CA-014 | atendido | Frases contíguas normalizadas/NBSP/acentos/limites de tokens e negativo disperso passaram. |
| CA-015 | atendido | Preço desconhecido rejeita só teto, aceita alternativa sem teto e preserva razões por regra; frete não cria zero nos controles atuais. |
| CA-016 | nao atendido | Global `usado` perde condição após `Frete incluso,`, aceita interesse permissivo (001 residual). |
| CA-017 | atendido | Somente globais/sem ativos/sem match, configuração inválida/inicial desconhecida/último válido: testes atuais. |
| CA-018 | atendido | API40 e Python: defaults/enums/listas/normalização/categoria/faixa/precisão e CRUD com fakes aprovados. |
| CA-019 | atendido | PUT parcial/omitido/null/[]/pausado/invariantes/erro inexistente versus banco/schema: API/UI atuais. |
| CA-020 | atendido | UI7 real com API/Auth/hooks falsos: criar/editar/listar/pausar/modos/escopos/erros, sem login; não E2E de browser. |
| CA-021 | atendido | SQL local aplicado duas vezes, defaults/IDs/ativo/constraints/preflight e erro de schema API/cache comprovados atualmente. |
| CA-022 | atendido | Spies, hash congelado, commit remoto/resposta perdida, restart e retry tardio: suíte atual sem reextração/novo card. |
| CA-023 | atendido | Whitelist/fake estrito, logs saneados, diagnóstico local e rejeição sem remoto comprovados. |
| CA-024 | atendido | CLI e produção compartilham lógica; sem env/rede nos testes, JSON/códigos0/2/1 e exemplo atual aprovado. |
| CA-025 | nao atendido | Suíte ampliada217 termina com quatro assertions falhas em três métodos, sem erros/skips;212 anteriores passaram. |
| CA-026 | atendido | Simulação/corpus/limites atuais, hashes/ambiente e comparação/custo explícitos; sem SLA/ganho causal e sem etapa3. Duplicação CPU segue RNF-002. |

**Resumo:22 atendidos,2 parcialmente atendidos,2 não atendidos.** Quatro assertions falhas na suíte: uma em001, uma em003 e duas nos subcasos de004.

#### Diff, ciclo curto e próximo passo

| Classificação | Constatação |
|---|---|
| Previsto/necessário | Implementação entre bot/API/UI/SQL/CLI/documentação corresponde ao PRD, sem nova identidade/serviço. |
| Desvios menores anteriores | Factories para testes, contexto bruto/spans e PGlite temporário são compatíveis e documentados; nenhum novo desvio material. |
| Preexistente nesta validação | Toda implementação, regressões originais/retomada, PRD e três prompts; nada descartado/estagiado automaticamente. |
| Criado nesta validação | Apenas `bot/tests/test_revalidacao_etapa2.py` (cinco métodos sintéticos) e metadados/checklist/resultado deste PRD. |
| Correção funcional/ciclo curto | Nenhuma: várias causas/blocos cruzados exigem retorno à implementação, não patch amplo em validação. |
| Fora do escopo | Nenhuma operação Git de publicação, conta real, SQL remoto, deploy, nova identidade/hash histórico, auth ou migração de imagens. |

Revisão técnica nesta nova execução feita pela sessão principal, não apresentada como revisão independente de outro agente. Ausência de teste em Node20/browser real/produção/Supabase/VPS permanece limitação explícita; UI falsa e Postgres local são as verificações requeridas no escopo aprovado. Não há decisão de produto/ambiente indispensável pendente que justifique `bloqueado`; há defeitos locais comprovados, portanto **`em_implementacao`**.

Próximo comando: `/sdd-implementar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`. Corrigir VAL-ET2-001 residual,003 residual e004, considerar o derivado redundante em RNF-002, preservar todas as assertions/contratos e repetir suíte/medições afetadas antes de nova validação. Não reabrir finalizados nem recalcular hashes para compensar estes defeitos. Sem commit/push/deploy/etapa3.

**Histórico preservado:** o resultado abaixo precede a retomada corretiva da seção15 e a nova validação acima. Seus comandos/matrizes/encaminhamentos descrevem aquela execução, não o estado atual.

### Validação final — 2026-11-03 — REPROVADA

O usuário autorizou voltar ao checkout original e executar a validação SDD. Sessão movida de volta a `C:/Users/Alexandre_HP/Documents/DellBot/dealbot`; base **main / 7c327d203b053eb8325c7c2efb9f1dc9d5d7327a**, único worktree desta cópia, PRD v1 com aprovação do usuário e estado inicial `em_validacao` confirmados. Runtime global `_comum.md`/`validar.md` relidos integralmente; PRD integral, instruções e fontes relacionadas conferidos. Sem `.sdd-lite` local ou `AGENTS.md` no workspace. Todo o diff de implementação e os prompts eram preexistentes e foram preservados.

Intenção da revisão: comprovar extração contextual e filtros ponta a ponta sem perder decisões, inbox e dedup. Roteiro executado: **V01 revisão e verificações → V02 contraprovas/regressões → V03 matriz e retorno à implementação**. Aprovação da versão 1 permanece válida: não se alterou requisito para acomodar defeitos.

**Decisão:** `em_implementacao`, não `concluido` nem aceite parcial. Cinco assertions novas falham por três causas reproduzidas independentemente e na sessão principal. Nenhum módulo de produção foi corrigido nesta validação; retorno a `sdd-implementar` para o conjunto de ajustes.

### Achados impeditivos e evidências

#### VAL-ET2-001 — Cauda após preço inline é apagada e burla veto global (alta, bloqueante)

- **Local:** `bot/src/extractor.py:303-307`, `_descricao` corta toda a linha no primeiro valor monetário, em vez de excluir somente o trecho monetário e preservar descrição posterior.
- **Entrada sintética:** `SSD Kingston R$ 299,90 - USADO`; global id 1 com `palavras_bloqueio=["usado"]`; interesse id 2 com teto 350.
- **Real:** conteúdo `ssd kingston`; `aceita=True`, motivo `aceita_por_regra`/2; global informa `sem_correspondencia`. **Esperado:** conteúdo mantém `usado`, veto `bloqueio_global`/1 e rejeição independente de interesse permissivo.
- **Segunda prova:** `SSD Kingston R$ 299,90 - NV2 1 TB NVMe` vira título `SSD Kingston`, perdendo modelo/capacidade/variante.
- **Impacto:** RF-001/005/006, RN-002 e CA-016 não atendidos integralmente. Não é pedido de fuzzy ou cobertura universal: trata-se de condição explícita de produto removida pelo parser.
- **Correção requerida:** separar apresentação de conteúdo e remover somente intervalos monetários/serviço identificados, mantendo a cauda relevante e a condição. Acrescentar controles para não inserir cupom, frete ou divulgação no conteúdo.
- **Regressões:** `test_condicao_apos_preco_inline_nao_pode_furar_bloqueio_global` e `test_modelo_capacidade_e_variante_apos_preco_inline_sao_descritivos` no novo `bot/tests/test_validacao_etapa2.py`: ambas falharam.

#### VAL-ET2-002 — Frete é confundido com gratuidade ou preço anterior (alta, bloqueante)

- **Locais:** `bot/src/extractor.py:205-218` (`_papel_preco`) e `268-271` (gratuidade).
- **Entrada sintética:** `SSD Kingston\nFrete: grátis\nhttps://loja.example/SSD`, com interesse `preco_max=0`.
- **Real:** preço **0.0**, fonte `gratuidade_explicita`, aceita pelo teto zero. **Esperado:** preço desconhecido, rejeição nessa regra por `preco_desconhecido`. Sem o link, só frete gratuito também não deveria fabricar oferta conhecida como gratuita.
- **Entrada relacionada:** `SSD Kingston\nFrete de R$ 15,00\nhttps://loja.example/SSD` gera `preco_original=15.0`, embora não haja preço anterior do produto. O contexto `frete de` cai no marcador genérico `de`.
- **Causa:** exclusão de frete grátis exige espaço, não aceita `:`; precedência dos papéis não reconhece a forma `frete de`. Valores continuam exatos em centavos, mas semanticamente errados.
- **Impacto:** RF-002/005, RN-001, CA-003/006/015. Zero explícito de produto permanece legítimo; não corrigir tratando todo zero como ausente.
- **Correção requerida:** classificar frete/entrega/envio e seus marcadores/pontuação antes da inferência de gratuidade/preço anterior; testar valores com/sem total e controles de produto efetivamente grátis.
- **Regressões:** `test_frete_gratis_com_dois_pontos_nao_e_preco_zero_do_produto` e `test_frete_de_valor_nao_vira_preco_anterior`: ambas falharam; controle de jogo grátis passou.

#### VAL-ET2-003 — Especificação é contada como produto independente (média, importante impeditivo)

- **Local:** `bot/src/extractor.py:230-258,263-265`; `ultima_descricao` troca para qualquer linha alfabética e o conjunto de linhas é tratado como número de produtos.
- **Entrada sintética:** `SSD Kingston\nR$ 350,00\nCapacidade 1 TB\nÀ vista R$ 299,90\nhttps://loja.example/SSD`.
- **Real:** produto nulo, `multiplas_ofertas`, descarte terminal. **Esperado:** um SSD, atual 299,90 por precedência do à vista, conteúdo preservando capacidade. Remover só `Capacidade 1 TB` faz a mesma oferta ser aceita.
- **Impacto:** RF-002 e CA-004/007: inferência de ambiguidade deve ter evidência de produtos/preços independentes, não apenas mudança de linha descritiva. Não exige arquitetura multioferta ou cobertura completa de todos os posts.
- **Correção requerida:** distinguir continuidade/especificações do mesmo produto de objeto independente; manter rejeição de SSD + headset com preços separados e casos de finais conflitantes.
- **Regressão:** `test_especificacao_entre_precos_nao_define_segundo_produto` falhou; `test_controles_gratuidade_e_multiplos_reais_continuam_distintos` passou.

### Ciclo curto, escopo e preservação

Os três achados exigem ajustes em preservação de conteúdo, classificação semântica de valores/gratuidade e detecção de múltiplos produtos. Embora estejam no mesmo arquivo, são vários blocos com regressões cruzadas; não se improvisou uma correção ampla no comando de validação. Isso segue a regra de retorno à implementação de `validar.md`. **Nenhum requisito, arquitetura, dependência, migração ou proteção foi relaxado.**

| Classificação do diff | Escopo e decisão |
|---|---|
| Previsto/necessário | Extrator, normalização/dinheiro, filtros/cache, contexto/SQLite, pipeline/repositório, CLI/benchmark/testes, CRUD/tela, bloco SQL aditivo e documentação correspondem ao PRD. |
| Desvio menor documentado | Factories de model/service/controller/router para testes sem ambiente; Postgres PGlite temporário sem dependência de produção; uso de texto bruto/spans em vez de markup, com regressões equivalentes. |
| Preexistente à validação | Todo o diff anterior, PRD aprovado e três prompts não rastreados. Nada descartado, sobrescrito ou incluído em Git automaticamente. |
| Criado por esta validação | Apenas `bot/tests/test_validacao_etapa2.py` (seis casos sintéticos) e este registro/checklist/estado do PRD. |
| Fora do escopo | Nenhuma alteração funcional nova de produção; sem identidade nova, imagens, auth, stack, deploy, SQL remoto ou etapa 3. |

Os cinco testes novos negativos ficam intencionalmente vermelhos até a correção. Não foram marcados como skip/expectedFailure e não substituem os 189 testes existentes. Revisão destacou como pontos positivos a separação do produto/diagnóstico, comparação em centavos, preparação de snapshot e proteção de decisões/hash.

### Comandos executados nesta validação

Python: ambiente WSL existente `/mnt/c/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa01-linux/bin/python`, 3.12.3, SDKs fixados já instalados. Node: **v24.11.1**, não Node 20 do ambiente documentado. Nenhuma instalação/upgrade de pacote nesta validação. Comandos Python partem de `bot/`; npm de seu serviço.

| Comando/procedimento | Resultado real | Observação |
|---|---|---|
| Git status/log/worktrees e leituras integrais de runtime/PRD | Base/aprovação coerentes, alterações preservadas | Sem staging/reset/commit/push. |
| `python -B -m unittest discover -s tests -q` antes das regressões | **189 testes: 188 passaram, 1 erro de timeout; zero skips; 205,628s**, código 1 | `test_rajada_concorrencia_justica_e_heartbeat`, watchdog 3s. Não atribuir a defeito funcional sem prova nem declarar sucesso. Houve testes Node concorrentes no começo dessa execução e warnings de tarefas lentas. |
| `python -B -m unittest tests.test_pipeline.TestPipeline.test_rajada_concorrencia_justica_e_heartbeat -v` isolado, código inalterado | 1 passou, **2,388s** | Timeout/assertions não alterados; causa temporal exata permanece não comprovada. |
| Revisão independente somente leitura | Três contraprovas; seis testes direcionados anteriores passaram | Revisor usou Python 3.14.4/Windows, fixtures sintéticas e nenhum serviço real; provas repetidas no WSL pela sessão principal. |
| `python -B -m unittest tests.test_validacao_etapa2 -v` | **6 testes: 1 passou, 5 falharam; 0,074s**, código 1 | Cinco assertions reproduzem três causas; controle grátis/múltiplos genuínos passa. |
| `python -B -m unittest discover -s tests -q` após regressões, sem build/benchmark concorrente | **195 testes: 190 passaram, 5 falharam, zero erros/skips; 133,403s**, código 1 | Todas as cinco falhas são contraprovas novas; os 189 anteriores passaram nessa execução. Não é suíte aprovada. |
| `npm test` backend | **40 passaram**, zero falhas/skips; 996,608ms | Serviços/models/controllers/routes falsos/injetados, sem banco remoto. |
| `npm test` frontend | **7 passaram**, zero falhas/skips; 1774,515ms | Componente TSX real renderizado com hooks/API/Auth falsos; não é browser E2E. |
| `npm run lint` frontend | Sucesso, sem warnings/erros | ESLint existente. |
| `npx --no-install tsc --noEmit --incremental false` frontend | Sucesso | Nenhum tipo público de preço mudou para string/Decimal. |
| CLI Next build com env fictício explícito, comando abaixo | Sucesso, compilação/lint/tipos e seis páginas; `/filtros` 4,26kB / first load 160kB | Sem `.env` privado/credencial/serviço real; telemetry desativada. |
| SQL runner com PGlite absoluto, comando abaixo | **Sucesso: PostgreSQL 18.6/PGlite 0.5.11**, aplicação dupla/preservação/defaults/constraints/preflight atômico | Banco local em memória; não valida extensões/RLS/produção. |
| `python -m pip check` | Primeira tentativa timeout 30s; repetida com 120s: **No broken requirements found** | Não atualizou pacote nem mascarou falha da aplicação. |
| `node --check` recursivo em `backend/src` e `backend/tests` | Sucesso | Backend sem lint/typecheck/build configurados; não foram inventados. |
| AST em memória dos Python/fontes/testes/runners | **43 arquivos parseados, 195 métodos test_** | Não escreve bytecode; não substitui as assertions. |
| `python -B -m previa --mensagem exemplos/etapa02/mensagem.txt --filtros exemplos/etapa02/filtros.json` | Saída 0: 299,90/399,90, título descritivo, cupom `AbC123`, link comercial, aceita regra 1 | Exemplo sintético feliz; não absolve as contraprovas. |
| `git diff --exit-code --` para legado/dedup/pins/locks/sinais/recuperação/mídia/unit/env/auth central | Saída vazia, código 0 | Arquivos protegidos preservados. |
| `git diff --check` e revisão de arquivos novos | Sem erro de whitespace; avisos LF/CRLF | Estado local/bancos/segredos não incluídos no diff. |

Comandos adicionais exatos, em seus diretórios:

```text
# frontend/ — equivalente ao npm run build com ambiente fictício explícito
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['node_modules/next/dist/bin/next','build'],{stdio:'inherit',env:{...process.env,NEXT_PUBLIC_SUPABASE_URL:'https://supabase.invalid',NEXT_PUBLIC_SUPABASE_ANON_KEY:'fake-anon-key',NEXT_PUBLIC_API_URL:'http://127.0.0.1:3333/api',NEXT_TELEMETRY_DISABLED:'1'}});process.exit(r.status??1)"

# backend/ — PostgreSQL embarcado local temporário, sem URL remota
node -e "const {spawnSync}=require('node:child_process');const r=spawnSync(process.execPath,['tests/sql-etapa2.local.mjs'],{stdio:'inherit',env:{...process.env,DEALBOT_TEST_POSTGRES_URL:'',DEALBOT_TEST_PGLITE_MODULE:'C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa02-sql/node_modules/@electric-sql/pglite/dist/index.js'}});process.exit(r.status??1)"
```

### Simulação e custo local repetidos

Executado novamente em `bot/`, **depois da suíte e fora de build/testes**, sem editar runner/dataset:

```text
python -B -m simulacao --seed 42 --live 30 --historico 100 --db-ms 20 --midia-ms 200 --oferta-workers 4 --midia-workers 1
```

- 130 ofertas recebidas/aprovadas/produtos, zero descartes/duplicatas/falhas de oferta; duração **22,570s**, vazão **5,760 ofertas/s**.
- Live p50/p95/máximo **274,195/442,603/1451,830ms**; histórico **20710,893/22399,848/22539,131ms**. Heartbeat máximo **2,714ms**.
- Workers máximos 4/1; fila live 0/8/0, histórico 0/100/0, mídia 0/106/106; 24 mídias prontas, 105 pendentes/uma em processamento. Ambos os produtores progrediram antes do fim da outra classe; página máxima 100 e zero task por mensagem.
- SHA256 live `606566d45b45b7aa62fe26fac20f4cf6711d3d218db3ce92028f6f69ad8305fb` e histórico `27d06c6d95354250d1f535ba588fcfc84bab6e75246b0330959534ed7ecb2805` iguais aos anteriores. Cinco operações de 20ms por oferta e mídia 200ms, sem drenar fotos para medir disponibilidade.
- **Piora local substancial** comparada ao fechamento de 4,749s na implementação, sem mudança de produção nesta validação. Host/filesystem/pausas não foram isolados; não afirmar melhora nem causalidade. Sucesso do dataset feliz não valida conteúdo/preços dos casos negativos. Sem SLA de VPS/frontend ou prova do RPC de histórico pelo benchmark.

Corpus e regras no limite repetidos por comando equivalente à CLI, omitindo apenas impressão de exemplos/tempos por caso:

```text
python -B -c "import asyncio,json,medir_extracao as m; r=asyncio.run(m.medir(100)); r['limites_regras']=m.medir_limites(); r.pop('exemplos'); r.pop('extracao_por_caso'); print(json.dumps(r,ensure_ascii=False,indent=2))"
```

28 casos sintéticos, 3 aquecimentos, 100 iterações/2800 amostras, mesmo seed/hash `1365e78aad2e86f2fd3ec6676b67170a8a027a631c6a72b0a606b44b64ebb34c`. Extração p50/p95/máx **159,103/5720,579/12453,973µs**; extração+avaliação **178,653/5769,780/12482,874µs**; vazão **1609,49 mensagens/s**, janela 1,739686s. Só avaliação: 20,101/42,401/150,603µs (2500 ofertas consideradas válidas); preparo snapshot: 15/19,6/347,104µs. As contraprovas novas não foram inseridas silenciosamente no corpus comparativo para mudar seu hash; ficam nos testes novos.

Dez regras, 50 termos/lista, 100 caracteres/termo e 20 avaliações por entrada: preparo único **120498,171µs**; avaliação p50/p95/máx curta **1586,172/1801,225/1878,826µs**, longa **2762,889/2925,840/3116,643µs**, adversarial **1590,472/1714,824/1810,925µs**. Sem rede/espera artificial; custo adicional versus extrator legado permanece explicitado na seção 15. Não comprova correção funcional só por tempo baixo.

### Matriz final — requisitos, regras e não funcionais

Resultados limitados ao escopo local/offline; `parcialmente atendido` não significa aceite parcial da entrega.

| Item | Resultado | Evidência atual |
|---|---|---|
| RF-001 | parcialmente atendido | Título genérico/curto/hífens, normalização e rastreabilidade passaram; VAL-ET2-001 corta cauda com condição/modelo após preço. |
| RF-002 | parcialmente atendido | BRL/Decimal/centavos/nullable e casos básicos passaram; VAL-ET2-002 inventa zero/anterior de frete e VAL-ET2-003 dá falso múltiplo. |
| RF-003 | atendido | `test_contexto`/SDK: UTF-16/emoji, bruto live/raw, botões, restart, delimitadores e HTTP(S); sem RPC de enriquecimento. |
| RF-004 | atendido | Cupom contextual/caixa/ambiguidade, sete categorias e extensão vazia, fixtures sintéticas; `test_extracao`/API/UI passaram. |
| RF-005 | parcialmente atendido | Avaliador isolado combina condições, frases/modos e razões; entrada perde `usado`/preço desconhecido nos casos VAL-ET2-001/002. |
| RF-006 | parcialmente atendido | Globais/locais/snapshot inválido e defaults corretos isoladamente; veto fim a fim é burlado por VAL-ET2-001. |
| RF-007 | atendido | 40 API e 7 UI, PUT parcial/ativo pausado/zero/invariantes/erros; lint/tipos/build atuais aprovados. |
| RF-008 | atendido | Migração v4→v5 real/rollback e versões antigas; spies provam ausência de reavaliação/hash novo, commit ambíguo e whitelist remota; testes atuais passaram. |
| RF-009 | atendido | Diagnóstico/ID/razões sem dados privados e CLI com lógica de produção, sem tokens/rede; códigos de saída e estados terminal/configuração distintos passaram. Diagnóstico pode explicar dado incorreto herdado do extrator (RF-001/002). |
| RF-010 | atendido | README/PRD com exemplos, políticas, migração/rollback, comandos, medições e limites; novos resultados negativos registrados sem ocultação. |
| RN-001 | parcialmente atendido | Controles de evidência/ambiguidade passaram, mas frete grátis fabrica preço zero (VAL-ET2-002). |
| RN-002 | parcialmente atendido | OR/AND e escopos corretos no avaliador; perda de condição permite aceitação globalmente vetada (VAL-ET2-001). |
| RN-003 | atendido | Decisões/hash existentes soberanos, nenhum reprocessamento histórico; `test_decisoes_etapa2`/checkpoints passaram. |
| RN-004 | atendido | Entrada, coleta/geração/página, workers/cache/canais, async, foto posterior, sinais/retenção preservados; suíte ampliada final não teve falha nesses testes. Timeout inicial de rajada registrado. |
| RN-005 | atendido | `dedup.py` e janela de 48h inalterados; aparições/reconciliação tardia e locks cobertos por testes atuais. |
| RN-006 | atendido | Sem conta/SQL remoto/publicação; prompts/trabalho anterior preservados, testes sintéticos e bancos temporários. |
| RNF-001 | atendido | Extração/avaliação locais puras; SDK só lê metadados próprios, nenhum enriquecimento/rede/IA/espera nova no caminho crítico. |
| RNF-002 | atendido | Snapshot/regex preparados, pré-teste literal e cache de correspondência; corpus/adversarial/listas no limite medidos, sem crescimento explosivo comprovado. Preparo grande ~120ms de refresh continua ressalva. |
| RNF-003 | atendido | Número/null públicos, JSON/SQLite antigo, categorias e IDs preservados; locks/pins/auth sem mudanças. |
| RNF-004 | atendido | Projeção remota estrita e teste de logs sem texto/cupom/URL/termos; contexto/diagnóstico locais sujeitos à mesma retenção/permissões; nenhuma fixture privada. |
| RNF-005 | atendido | Falhas/timeouts/limitações e comandos reais registrados, nenhuma assertion retirada ou skip novo para verde, sem inferir SLA de mocks. |

Resumo: **15 atendidos, 6 parcialmente atendidos**, nenhum aceite global enquanto os bloqueantes persistirem.

### Matriz final — critérios de aceitação

| Critério | Resultado | Procedimento/evidência |
|---|---|---|
| CA-001 | atendido | Mensagem exata de chamada/SSD/hífens mantém título e matching nos testes anteriores atuais; perda específica após moeda é achado RF-001. |
| CA-002 | atendido | Curto válido, grupo genérico, URL/cupom/rodapé fora do matching: `test_extracao`/decisões passaram. |
| CA-003 | parcialmente atendido | De/por/frete simples corretos; `Frete de R$ 15,00` produz anterior fictício (VAL-ET2-002). |
| CA-004 | parcialmente atendido | Parcela/à vista básicos e não derivação passaram; especificação entre valores impede precedência à vista (VAL-ET2-003). |
| CA-005 | atendido | Desconto/compra mínima/20%/modelos e anterior inconsistente cobertos e passaram. |
| CA-006 | nao atendido | Precisão/BRL/limites e zero real passaram; `Frete: grátis` vira zero e permite teto 0 (VAL-ET2-002). |
| CA-007 | parcialmente atendido | Dois produtos/finais conflitantes são rejeitados; especificação única vira falso múltiplo (VAL-ET2-003). |
| CA-008 | atendido | Grupo antes de link, URL curta, delimitadores/caixa/query e schemes inválidos cobertos nos testes atuais. |
| CA-009 | atendido | Live/raw SDK tipado com emoji/TextUrl/botão, um pedido por página e nenhuma RPC extra; `test_contexto` passou. |
| CA-010 | atendido | Contexto/restart e bancos antigos/DDL v4/falha no ALTER com rollback preservam jobs/hash/decisão/fronteiras/mídia. |
| CA-011 | atendido | Cupom com marcador preserva `AbC123`, isolado/incompleto/ambíguo não fabricam código; testes atuais passaram. |
| CA-012 | atendido | Objeto principal/frases/palavras curtas/categorias sincronizadas e rejeição de `todos` passaram. |
| CA-013 | atendido | SSD+Kingston todas/qualquer, teto e interesses alternativos/lista vazia: `test_filtros_etapa2` passou. |
| CA-014 | atendido | Frase contígua normalizada versus dispersa, acentos/NBSP/limites de tokens e sem fuzzy: testes passaram. |
| CA-015 | parcialmente atendido | Rejeição por regra e razões corretas com preço realmente nulo, mas frete grátis fabrica preço conhecido e impede `preco_desconhecido` fim a fim. |
| CA-016 | nao atendido | `SSD Kingston R$ 299,90 - USADO` passa apesar do veto global explícito (VAL-ET2-001). |
| CA-017 | atendido | Globais sem match não autorizam contra interesse; sem interesses/sem ativos, inválidos e cache preservado cobertos nos testes. |
| CA-018 | atendido | CRUD/defaults/enums/categoria/termos/duplicatas/limites/moeda: 40 API aprovados e casos Python correspondentes. |
| CA-019 | atendido | Pausado/PUT parcial/null/[]/invariantes e inexistência versus schema/erro técnico cobertos por API/UI. |
| CA-020 | atendido | Sete testes da tela real com API/Auth/hooks falsos e renderização: criar/editar/listar/pausar, modos/escopos/teto 0/erros; não se alega browser real. |
| CA-021 | atendido | SQL local executado duas vezes, dados/defaults/constraints/preflight atômico e schema ausente API/cache verificados. |
| CA-022 | atendido | Spies extração/avaliação/hash, resposta perdida e restart >48h mantêm decisão/hash/card/aparições; testes atuais passaram. |
| CA-023 | atendido | Fake estrito rejeita extras remotos; logs saneados e descarte sem salvar remotamente nos testes atuais. |
| CA-024 | atendido | Prévia e produção equivalentes com rede bloqueada/sem env, códigos 0/2/1; testes e CLI executados. |
| CA-025 | nao atendido | Suíte ampliada termina com cinco falhas concretas; timeout inicial e repetição sem timeout registrados. Nenhuma assertion removida. |
| CA-026 | atendido | Simulação/corpus atuais comparáveis à base registrada, limites e custos altos informados; documentação/rollback/etapa 3 explícitos, sem SLA real. |

Resumo: **19 atendidos, 4 parcialmente atendidos, 3 não atendidos**; nenhum não executado obrigatório usado como aprovação. A proteção de veto fim a fim foi reaberta no checklist, apesar dos demais testes de compatibilidade/migração/privacidade aprovados.

### Pendências e próximo passo

- **Executar:** `/sdd-implementar docs/sdd/incrementos/dealbot-etapa-02-extracao-filtros.md`, corrigindo VAL-ET2-001 a 003 no contrato já aprovado. Não há nova decisão de produto bloqueante ou autorização remota necessária para voltar ao requisito original.
- Manter `test_validacao_etapa2.py` e todos os asserts anteriores; fechar as cinco contraprovas, repetir suíte ampliada/benchmark afetados e encaminhar a nova validação SDD. Observar timeout de rajada e compensação histórico sem aumentar limites para esconder problema.
- Não reavaliar ofertas já decididas nem recalcular hash histórico para compensar as falhas. Alteração do extrator só vale para decisões ainda não congeladas.
- Nenhuma migração real, staging, commit, push, merge, deploy ou etapa 3. Estado de saída **`em_implementacao`**, com trabalho válido preservado e matriz/evidências negativas registradas.

### Autoavaliação do planejamento — histórica

- [x] Comportamento confirmado com caminhos reais; desejado e não confirmado separados.
- [x] Escopo/fora de escopo e requisitos/26 critérios verificáveis; arquitetura existente respeitada.
- [x] Modo rigoroso e risco alto justificados, com proteções de compatibilidade/migração/privacidade e reversão.
- [x] Decisões propostas explícitas, premissas e perguntas não bloqueantes registradas; nenhuma aprovação ou resultado de teste inventado.
- [x] Na fase de planejamento, a única alteração foi o PRD; a implementação posterior foi autorizada pela invocação explícita registrada nos metadados/seção 15.
