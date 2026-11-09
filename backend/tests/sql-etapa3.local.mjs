// node tests/sql-etapa3.local.mjs (não altera package.json/não lê .env).
// Exige psql e banco LOCAL VAZIO DESCARTÁVEL, sem senha/credenciais reais:
// DEALBOT_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:55439/dealbot_teste_etapa3
// DEALBOT_TEST_POSTGRES_DISPOSABLE=SIM
// DEALBOT_TEST_PSQL=caminho absoluto opcional para psql (Windows fora do PATH).
// O banco fica com fixtures para inspeção; não apaga banco/schema/cluster.
// Alternativa DEALBOT_TEST_PGLITE_MODULE absoluta: DDL/semântica SOMENTE, exit 2;
// nunca equivale à prova de concorrência PostgreSQL de sessões independentes.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";
import { setTimeout as esperar } from "node:timers/promises";
import { validarRevisao3, validarRevisao3Concorrente } from "./sql-revisao3.local.mjs";

const endereco = process.env.DEALBOT_TEST_POSTGRES_URL;
const modulo = process.env.DEALBOT_TEST_PGLITE_MODULE;
if ((!endereco && !modulo) || (endereco && modulo)) {
  throw new Error("Defina apenas URL PostgreSQL local descartável ou módulo PGlite absoluto; SQL etapa 3 NÃO validado.");
}
if (endereco) {
  const alvo = new URL(endereco);
  if (!["postgres:", "postgresql:"].includes(alvo.protocol)
    || !["localhost", "127.0.0.1", "[::1]"].includes(alvo.hostname)
    || !/^\/dealbot_teste(?:_[a-z0-9_]+)?$/.test(alvo.pathname)
    || alvo.search || alvo.hash || alvo.password
    || process.env.DEALBOT_TEST_POSTGRES_DISPOSABLE !== "SIM") {
    throw new Error("Recusado: somente host local, banco dealbot_teste[_sufixo] vazio, sem senha/query e confirmação DISPOSABLE=SIM.");
  }
}
if (modulo && !isAbsolute(modulo)) throw new Error("PGlite deve ser módulo local absoluto.");

const schema = readFileSync(new URL("../../supabase/schema.sql", import.meta.url), "utf8");
const bloco = schema.match(/-- ETAPA 3 OFERTAS: início[\s\S]+?-- ETAPA 3 OFERTAS: fim\.[^\n]*/)?.[0];
assert.ok(bloco, "Bloco etapa 3 ausente");
const base = schema.slice(0, schema.indexOf("-- ETAPA 3 OFERTAS: início"));
const bootstrap = readFileSync(new URL("./sql-etapa3.local.sql", import.meta.url), "utf8");

// Um processo psql persistente = uma conexão real. Sentinel delimita cada
// comando, sem shell, driver externo, sleeps como substituto de barreiras ou senha.
class Sessao {
  constructor() {
    this.numero = 0;
    this.fila = null;
    this.buffer = "";
    this.erros = "";
    this.processo = spawn(process.env.DEALBOT_TEST_PSQL || "psql", [
      "-X", "-qAt", "-w", "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "--dbname", endereco,
    ], { stdio: ["pipe", "pipe", "pipe"], env: {
      ...Object.fromEntries(Object.entries(process.env).filter(([chave]) => !/^PG/i.test(chave))),
      PGAPPNAME: "dealbot_sql_etapa3", PGCLIENTENCODING: "UTF8",
      // Não usar credenciais/serviço/arquivo de senha implícitos do usuário.
      PGPASSFILE: process.platform === "win32" ? "NUL" : "/dev/null", PGSSLMODE: "disable",
      PGOPTIONS: "-c statement_timeout=15000 -c lock_timeout=10000 -c timezone=UTC -c client_min_messages=warning",
    } });
    this.processo.stdout.setEncoding("utf8");
    this.processo.stderr.setEncoding("utf8");
    this.processo.stdout.on("data", (dados) => {
      this.buffer += dados;
      let quebra;
      while ((quebra = this.buffer.indexOf("\n")) >= 0) {
        const linha = this.buffer.slice(0, quebra).replace(/\r$/, "");
        this.buffer = this.buffer.slice(quebra + 1);
        if (this.fila && linha === this.fila.marcador) {
          const atual = this.fila;
          this.fila = null;
          atual.resolve(atual.linhas.join("\n"));
        } else if (this.fila) this.fila.linhas.push(linha);
      }
    });
    this.processo.stderr.on("data", (dados) => { this.erros += dados; });
    this.processo.on("error", (erro) => { this.fechada = true; this.fila?.reject(erro); });
    this.processo.on("close", (codigo) => {
      this.fechada = true;
      this.fila?.reject(new Error(`psql terminou (${codigo}): ${this.erros}`));
    });
    // Evitar erro não tratado quando psql encerra por ON_ERROR_STOP.
    this.processo.stdin.on("error", () => {});
  }
  exec(sql) {
    assert.ok(!this.fila, "Uma operação por conexão, use outra sessão para concorrência");
    if (this.fechada) return Promise.reject(new Error(`Conexão encerrada: ${this.erros}`));
    const marcador = `ETAPA3_FIM_${++this.numero}`;
    return new Promise((resolve, reject) => {
      this.fila = { marcador, resolve, reject, linhas: [] };
      this.processo.stdin.write(`${sql}\nselect '${marcador}';\n`);
    });
  }
  async rows(sql) { return JSON.parse(await this.exec(`select coalesce(json_agg(q),'[]'::json)::text from (${sql}) q;`)); }
  async close() {
    if (this.fechada) return;
    await new Promise((resolve) => { this.processo.once("close", resolve); this.processo.stdin.end("\\q\n"); });
  }
}

let pglite;
const sessoes = [];
function abrir() { const s = new Sessao(); sessoes.push(s); return s; }
let db;
if (modulo) {
  const { PGlite } = await import(pathToFileURL(modulo).href);
  pglite = new PGlite();
  db = { exec: (sql) => pglite.exec(sql), rows: async (sql) => {
    const resultado = await pglite.query(`select coalesce(json_agg(q),'[]'::json)::text as dados from (${sql}) q`);
    return JSON.parse(resultado.rows[0].dados);
  } };
} else db = abrir();

const literal = (valor) => `'${JSON.stringify(valor).replaceAll("'", "''")}'::jsonb`;
const inicio = Date.now() - 3_600_000;
const iso = (minutos = 0) => new Date(inicio + minutos * 60_000).toISOString();
const identidade = (chave = "a", campos = { loja: "sintetica", variante: "sku-1", condicoes: "completas" }) => ({
  versao: 2, chave: chave === null ? null : chave.repeat(64), componentes: {
    regra: "fixture_v1", confianca: chave === null ? "insuficiente" : "forte", campos,
    evidencias: {}, conflitos: [], incertezas: [], desconhecidos: [],
    comparacao: { regra: "fixture_v1", campos, url: { origem: "https://exemplo.invalid", path: "/sku-1" } },
  },
  motivo: chave === null ? "provisoria" : "fixture_forte", url_identidade: null,
});
const evento = (canal, msg, minutos = 0) => ({ canal_id: canal, msg_id: msg,
  canal_origem: `sintetico_${canal}`, data_origem: iso(minutos), recebido_em: new Date().toISOString(),
  tem_foto: false, enriquecer: false });
const produto = (preco = 300) => ({ titulo: "Fixture sintética", preco, preco_original: 400,
  cupom: "AbC10", link: "https://exemplo.invalid/AbC?SKU=1", categoria: "outros", raw_text: "Sintético" });
const registrarSQL = (e, p = produto(), i = identidade(), janela = 48) =>
  `select * from public.oferta_registrar(${literal(e)},${literal(p)},${literal(i)},${janela})`;
const registrar = async (e, p, i, janela, sessao = db) => (await sessao.rows(registrarSQL(e, p, i, janela)))[0];
const legadoRegistrarSQL = (e, p, hash) =>
  `select * from public.oferta_legado_registrar(${literal(e)},${literal(p)},'${hash}')`;
const registrarLegado = async (e, p, hash) => (await db.rows(legadoRegistrarSQL(e, p, hash)))[0];
const enriquecerSQL = (e, i) => `select * from public.oferta_enriquecer(${e.canal_id},${e.msg_id},${literal(i)})`;
const buscar = async (id) => (await db.rows(`select * from public.oferta_buscar(${id})`))[0];
const contar = async (tabela, filtro = "true") => Number((await db.rows(`select count(*) as n from public.${tabela} where ${filtro}`))[0].n);
let aprovados = 0;
function ok(nome) { aprovados++; console.log(`OK ${aprovados}: ${nome}`); }

// Comparar linhas completas também detecta backfill/reescrita silenciosa de
// preços, grafia, identidade, timestamps e ownership durante migração/retry.
async function dadosOfertas() {
  const dados = {};
  for (const tabela of ["produtos", "produto_aparicoes", "oferta_eventos", "oferta_midias", "oferta_controle"]) {
    dados[tabela] = await db.rows(`select * from public.${tabela} order by 1,2`);
  }
  return dados;
}
const indicesOfertas = () => db.rows(`select c.oid,c.relname,c.relkind,pg_get_indexdef(i.indexrelid) as definicao,
  i.indisunique,i.indisvalid,i.indisready from pg_class c join pg_namespace n on n.oid=c.relnamespace
  left join pg_index i on i.indexrelid=c.oid where n.nspname='public'
  and (i.indrelid in ('public.produtos'::regclass,'public.produto_aparicoes'::regclass)
    or c.relname in ('uq_produto_msg','uq_aparicao_canal_msg','uq_produto_evento_etapa3','uq_aparicao_evento_etapa3'))
  order by c.relname`);
function rejeitarSQL(sql, condicao) {
  return `do $teste$ begin
    begin
      execute $regressao$${sql}$regressao$;
      raise exception 'Regressão: operação deveria falhar';
    exception when others then
      if not (${condicao}) then raise; end if;
    end;
  end $teste$;`;
}

async function legadoAntigo(nome, msg) {
  await db.exec(`insert into public.produtos(titulo,preco,preco_original,cupom,link,
    raw_text,canal_origem,telegram_msg_id,dedup_hash,criado_em,data_oferta)
    values('Legado antigo sintético',17,29,'CuPoM','https://exemplo.invalid/Legado',
      'Texto congelado','${nome}',${msg},'hash_original_${msg}','2020-01-01T01:02:03Z','2020-01-01T01:00:00Z');`);
  const [p] = await db.rows(`select * from public.produtos where canal_id is null
    and canal_origem='${nome}' and telegram_msg_id=${msg}`);
  await db.exec(`insert into public.produto_aparicoes(produto_id,canal_origem,telegram_msg_id,visto_em)
    values(${p.id},'${nome}',${msg},'2020-01-01T01:02:04Z');`);
  const [a] = await db.rows(`select * from public.produto_aparicoes where produto_id=${p.id}`);
  return { p, a };
}

async function bloqueada(pid) {
  const prazo = Date.now() + 5000;
  while (Date.now() < prazo) {
    const [linha] = await db.rows(`select exists(select 1 from pg_locks where pid = ${pid}
      and locktype = 'advisory' and not granted) as bloqueada`);
    if (linha.bloqueada) return;
    await esperar(10);
  }
  assert.fail("A segunda conexão não chegou à barreira advisory real");
}

try {
  const objetos = await db.rows(`select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
    where n.nspname in ('public','auth','storage') and c.relkind in ('r','p','v','m','S')`);
  assert.equal(objetos.length, 0, "Banco não vazio: runner recusa sobrescrever dados");
  assert.equal((await db.rows("select count(*) as n from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public'"))[0].n, 0,
    "Banco com funções públicas não é descartável vazio");
  console.log((await db.rows("select version() as versao"))[0].versao);
  await db.exec(`${bootstrap}\n${base}
    -- Reproduzir explicitamente o schema herdado, não somente instalação nova.
    create unique index uq_produto_msg on public.produtos(canal_origem,telegram_msg_id);
    create unique index uq_aparicao_canal_msg on public.produto_aparicoes(canal_origem,telegram_msg_id);`);
  const globaisHerdados = (await indicesOfertas()).filter((i) => i.relname.startsWith("uq_"));
  assert.equal(globaisHerdados.length, 2);
  assert.ok(globaisHerdados.every((i) => !i.definicao.includes("WHERE")));
  await db.exec(`begin; ${bloco}\n${bloco}\nrollback;`);
  assert.equal(await contar("produtos"), 0);
  ok("aplicação dupla em schema vazio, revertida antes da fixture legada");
  await db.exec(`insert into public.produtos(titulo,preco,dedup_hash,canal_origem,telegram_msg_id)
    values('Legado sintético',0,'hash_legado','legado',77);
    alter table public.produtos add column identidade_versao text;
    do $teste$ begin
      begin
        execute $migracao$${bloco}$migracao$;
        raise exception 'Preflight deveria rejeitar tipo incorreto';
      exception when raise_exception then
        if sqlerrm not like 'Etapa 3: coluna incompatível:%' then raise; end if;
      end;
      if exists(select 1 from information_schema.columns where table_schema='public'
        and table_name='produtos' and column_name='estado_oferta') then
        raise exception 'Migração parcial sobreviveu à falha';
      end if;
    end $teste$;
    alter table public.produtos drop column identidade_versao;
    ${bloco}
    ${bloco}`);
  const [legado] = await db.rows("select id,preco,dedup_hash,identidade_versao,identidade_chave from public.produtos where id=1");
  assert.deepEqual(legado, { id: 1, preco: 0, dedup_hash: "hash_legado", identidade_versao: null, identidade_chave: null });
  ok("preflight atômico, aplicação dupla e legado sem confiança atribuída");

  const indicesEvento = [
    ["uq_produto_msg", "produtos", "canal_origem", "canal_id is null"],
    ["uq_aparicao_canal_msg", "produto_aparicoes", "canal_origem", "canal_id is null"],
    ["uq_produto_evento_etapa3", "produtos", "canal_id", "canal_id is not null"],
    ["uq_aparicao_evento_etapa3", "produto_aparicoes", "canal_id", "canal_id is not null"],
  ];
  assert.deepEqual(await db.rows(`select c.relname as nome,i.indisunique as unico,
    pg_get_indexdef(c.oid,1,false) as primeira,pg_get_indexdef(c.oid,2,false) as segunda,
    pg_get_expr(i.indpred,i.indrelid) as predicado from pg_class c join pg_index i on i.indexrelid=c.oid
    where c.relname in (${indicesEvento.map(([nome]) => `'${nome}'`).join(",")}) order by c.relname`),
  indicesEvento.map(([nome, , coluna]) => ({ nome, unico: true, primeira: coluna,
    segunda: "telegram_msg_id", predicado: coluna === "canal_id" ? "(canal_id IS NOT NULL)" : "(canal_id IS NULL)" }))
    .sort((a, b) => a.nome.localeCompare(b.nome)));
  assert.equal((await db.rows(`select is_nullable from information_schema.columns
    where table_schema='public' and table_name='produtos' and column_name='canal_id'`))[0].is_nullable, "YES");
  const erroIndice = "sqlstate='P0001' and sqlerrm like 'Etapa 3: índice incompatível:%'";
  for (const [nome, tabela, coluna, predicado] of indicesEvento) {
    // Nome correto não basta: ordem, unicidade, predicado e tipo do objeto.
    const definicoesErradas = [
      `create unique index ${nome} on public.${tabela}(telegram_msg_id,${coluna}) where ${predicado}`,
      `create index ${nome} on public.${tabela}(${coluna},telegram_msg_id) where ${predicado}`,
      `create unique index ${nome} on public.${tabela}(${coluna},telegram_msg_id) where telegram_msg_id>0`,
      `create sequence public.${nome}`,
    ];
    for (const ddl of definicoesErradas) {
      await db.exec(`begin; drop index public.${nome}; ${ddl};
        update public.oferta_controle set legado_pronto=false;`);
      const dados = await dadosOfertas();
      const indices = await indicesOfertas();
      await db.exec(rejeitarSQL(bloco, erroIndice));
      assert.deepEqual(await dadosOfertas(), dados, nome);
      assert.deepEqual(await indicesOfertas(), indices, nome);
      await db.exec(rejeitarSQL("select * from public.oferta_legado_pronto()", erroIndice));
      assert.deepEqual(await dadosOfertas(), dados, "Gate não pode confirmar índice errado");
      assert.deepEqual(await indicesOfertas(), indices);
      await db.exec("rollback;");
    }
    await db.exec(`begin; drop index public.${nome}; update public.oferta_controle set legado_pronto=false;`);
    const dados = await dadosOfertas();
    const indices = await indicesOfertas();
    await db.exec(rejeitarSQL("select * from public.oferta_legado_pronto()", erroIndice));
    assert.deepEqual(await dadosOfertas(), dados, "Gate não pode confirmar índice ausente");
    assert.deepEqual(await indicesOfertas(), indices);
    await db.exec("rollback;");
  }
  await db.exec(`begin; drop index public.uq_produto_evento_etapa3;
    alter table public.produtos alter column canal_id type text using canal_id::text;`);
  const dadosTipo = await dadosOfertas();
  const indicesTipo = await indicesOfertas();
  await db.exec(rejeitarSQL(bloco, "sqlstate='P0001' and sqlerrm='Etapa 3: coluna incompatível: canal_id'"));
  assert.deepEqual(await dadosOfertas(), dadosTipo);
  assert.deepEqual(await indicesOfertas(), indicesTipo);
  await db.exec("rollback;");
  ok("preflight/gate rejeitam índices com definição/tipo errado ou ausentes sem alterar dados/índices");

  for (const [nome, tabela, coluna] of indicesEvento) {
    // Simular instalação parcial: a troca dos globais conhecidos também deve
    // reverter quando a criação de QUALQUER um dos quatro índices encontra duplicatas.
    await db.exec(`begin;
      ${indicesEvento.map(([indice]) => `drop index public.${indice};`).join("\n")}
      ${indicesEvento.filter(([indice, , chave]) => chave === "canal_origem" && indice !== nome)
        .map(([indice, alvo]) => `create unique index ${indice} on public.${alvo}(canal_origem,telegram_msg_id);`).join("\n")}`);
    const numerico = coluna === "canal_id";
    if (tabela === "produtos") {
      await db.exec(`insert into public.produtos(titulo,canal_origem,telegram_msg_id,canal_id)
        values('Duplicata sintética A','duplicata_a',910001,${numerico ? -910001 : "null"}),
          ('Duplicata sintética B','${numerico ? "duplicata_b" : "duplicata_a"}',910001,${numerico ? -910001 : "null"});`);
    } else {
      await db.exec(`insert into public.produto_aparicoes(produto_id,canal_origem,telegram_msg_id,canal_id)
        values(1,'duplicata_a',910001,${numerico ? -910001 : "null"}),
          (1,'${numerico ? "duplicata_b" : "duplicata_a"}',910001,${numerico ? -910001 : "null"});`);
    }
    const dados = await dadosOfertas();
    const indices = await indicesOfertas();
    await db.exec(rejeitarSQL(bloco, `sqlstate='23505' and sqlerrm like '%${nome}%'`));
    assert.deepEqual(await dadosOfertas(), dados, nome);
    assert.deepEqual(await indicesOfertas(), indices, "Falha deve preservar inclusive OIDs dos globais herdados");
    await db.exec("rollback;");
  }
  ok("duplicatas textuais/numéricas abortam atomicamente a migração, inclusive substituição dos globais");

  const funcoes = await db.rows(`select p.oid::regprocedure::text as nome,p.prosecdef,
    has_function_privilege('anon',p.oid,'EXECUTE') as anon,
    has_function_privilege('authenticated',p.oid,'EXECUTE') as autenticado,
    has_function_privilege('service_role',p.oid,'EXECUTE') as servico,
    exists(select 1 from aclexplode(p.proacl) a where a.grantee=0 and a.privilege_type='EXECUTE') as publico
    from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and (p.proname like 'oferta_%' or p.proname like '_oferta_%' or p.proname like 'midia_%')`);
  assert.equal(funcoes.length, 16);
  assert.ok(funcoes.some((f) => /(?:public\.)?_oferta_equivalentes\(jsonb,jsonb\)/.test(f.nome)),
    "Comparador aditivo de identidades também deve constar na auditoria de privilégios");
  for (const f of funcoes) {
    assert.equal(f.prosecdef, false, f.nome);
    assert.equal(f.anon || f.autenticado || f.publico, false, f.nome);
    assert.equal(f.servico, true, f.nome);
  }
  assert.equal((await db.rows("select count(*) as n from pg_class where oid in ('public.produtos'::regclass,'public.produto_aparicoes'::regclass,'public.oferta_eventos'::regclass,'public.oferta_midias'::regclass) and relrowsecurity"))[0].n, 4);
  await db.exec("set role service_role;");
  const e1 = evento(-1001, 1);
  const r1 = await registrar(e1);
  assert.equal(r1.status, "novo");
  await db.exec("reset role;");
  if (!modulo) {
    for (const papel of ["anon", "authenticated"]) {
      const negada = abrir();
      await assert.rejects(negada.exec(`set role ${papel}; select * from public.oferta_buscar(${r1.id});`), /permission denied|permissão negada/);
    }
  }
  ok("invoker e privilégios restritos inclusive auxiliares; service_role permitido sem relaxar RLS");

  const repetido = await registrar({ ...e1, canal_origem: "username_renomeado" });
  assert.equal(repetido.id, r1.id);
  assert.equal(repetido.status, "retomado");
  assert.equal((await registrar(e1, produto(123))).status, "conflito");
  assert.equal(await contar("oferta_eventos", `produto_id=${r1.id}`), 1);
  assert.equal(await contar("produto_aparicoes", `produto_id=${r1.id}`), 1);
  assert.equal((await buscar(r1.id)).preco, 300);
  ok("retry/resposta perdida/renomeação sem efeito adicional; payload conflitante não reescreve decisão");

  const r2 = await registrar(evento(-1002, 2, 1), produto(250));
  assert.equal(r2.id, r1.id);
  assert.equal(r2.status, "atualizado");
  assert.equal((await buscar(r1.id)).preco_anterior_atualizacao, 300);
  assert.equal((await buscar(r1.id)).preco_original, 400);
  await registrar(evento(-1003, 3, 2), produto(300));
  assert.equal((await buscar(r1.id)).preco, 300);
  assert.equal((await buscar(r1.id)).preco_anterior_atualizacao, 250);
  const antes = await buscar(r1.id);
  const antigo = await registrar(evento(-1004, 4, -10), produto(200));
  assert.equal(antigo.id, r1.id);
  assert.equal((await buscar(r1.id)).preco, 300);
  assert.equal((await buscar(r1.id)).expira_em, antes.expira_em);
  await registrar(evento(-1005, 5, 3), produto(0));
  assert.equal((await buscar(r1.id)).preco, 0);
  await registrar(evento(-1006, 6, 4), produto(null));
  assert.equal((await buscar(r1.id)).preco, null);
  assert.equal((await buscar(r1.id)).preco_anterior_atualizacao, null);
  await registrar(evento(-1007, 7, -9), produto(100));
  assert.equal((await buscar(r1.id)).preco, null);
  ok("300→250→300, histórico atrasado, zero/nulo e expiração por tempo original");

  const empate1 = await registrar(evento(-2001, 1, 5), produto(111), identidade("b"));
  await registrar(evento(-2000, 1, 5), produto(222), identidade("b"));
  assert.equal((await buscar(empate1.id)).preco, 222); // -2000 > -2001, ordem numérica
  await registrar(evento(-2002, 99, 5), produto(333), identidade("b"));
  assert.equal((await buscar(empate1.id)).preco, 222);
  ok("desempate temporal total por canal/mensagem numéricos independente da ordem de chegada");

  const provisoria1 = await registrar(evento(-3001, 1), produto(), identidade(null));
  const provisoria2 = await registrar(evento(-3002, 1), produto(), identidade(null));
  assert.notEqual(provisoria1.id, provisoria2.id);
  const conflitoComponentes = await registrar(evento(-3003, 1), produto(), identidade("a", { loja: "outro_seller" }));
  assert.notEqual(conflitoComponentes.id, r1.id);
  for (const campo of ["seller", "variante", "kit", "pagamento", "cupom", "elegibilidade"]) {
    const separado = await registrar(evento(-3100 - aprovados, campo.length), produto(),
      identidade("a", { campo, valor: "conflitante" }));
    assert.notEqual(separado.id, r1.id);
  }
  ok("sem dedup por título/URL opaca, chave sozinha ou condições conflitantes");

  const prova1 = identidade("7");
  const prova2 = structuredClone(prova1);
  prova1.componentes.evidencias = { vendedor: [{ fonte: "contexto" }] };
  prova2.componentes.evidencias = { vendedor: [{ fonte: "texto.linha:3" }] };
  prova1.componentes.urls = { original: "https://exemplo.invalid/?tag=canal1" };
  prova2.componentes.urls = { original: "https://exemplo.invalid/?tag=canal2" };
  const rp1 = await registrar(evento(-3301, 1), produto(), prova1);
  const rp2 = await registrar(evento(-3302, 1), produto(), prova2);
  assert.equal(rp1.id, rp2.id, "Proveniência não é condição comercial");
  const comparacaoDiferente = structuredClone(prova2);
  comparacaoDiferente.componentes.comparacao.url.path = "/sku-2";
  assert.notEqual((await registrar(evento(-3303, 1), produto(), comparacaoDiferente)).id, rp1.id);
  // Mesmo hash com payload conflitante não ganha confiança e não chega à escrita.
  for (const campo of ["conflitos", "incertezas", "desconhecidos"]) {
    const invalida = structuredClone(prova1);
    invalida.componentes[campo] = ["vendedor"];
    await db.exec(`do $teste$ begin
      begin
        perform public._oferta_validar_identidade(${literal(invalida)});
        raise exception 'Identidade forte conflitante aceita';
      exception when invalid_parameter_value then null; end;
    end $teste$;`);
  }
  ok("comparação comercial completa além da chave, proveniências independentes e conflito forte rejeitado");

  const semData = await registrar({ ...evento(-3201, 1), data_origem: "inválida" });
  const futuro = await registrar({ ...evento(-3202, 1), data_origem: new Date(Date.now() + 86400000).toISOString() });
  assert.notEqual(semData.id, r1.id);
  assert.notEqual(futuro.id, r1.id);
  assert.equal(await buscar(semData.id), undefined);
  assert.equal(await buscar(futuro.id), undefined);
  assert.equal((await db.rows(`select motivo_data from public.oferta_eventos where produto_id=${futuro.id}`))[0].motivo_data, "data_futura");
  ok("datas inválidas/futuras não substituem nem renovam instância corrente");

  const eventoVelho = { ...evento(-4001, 1), data_origem: new Date(Date.now() - 4 * 86400000).toISOString(),
    recebido_em: new Date(Date.now() - 4 * 86400000 + 1000).toISOString() };
  const velha = await registrar(eventoVelho, produto(), identidade("c"));
  const nova = await registrar(evento(-4002, 1), produto(), identidade("c"), 24);
  assert.notEqual(velha.id, nova.id);
  assert.equal((await registrar({ ...eventoVelho, recebido_em: new Date().toISOString() }, produto(), identidade("c"))).id, velha.id);
  assert.equal((await buscar(nova.id)).janela_horas, 24);
  assert.equal((await registrar(evento(-4003, 1, 1), produto(), identidade("c"), 99)).id, nova.id);
  assert.equal((await buscar(nova.id)).janela_horas, 24);
  ok("instâncias além de 48h, retry no vínculo original e janela congelada");

  // Mesma âncora do evento atual. Não criar um falso gap exatamente na borda
  // móvel de Date.now() enquanto os comandos de banco consomem segundos.
  const egap1 = { ...evento(-4101, 1), data_origem: new Date(inicio - 49 * 3600_000).toISOString(),
    recebido_em: new Date(inicio - 49 * 3600_000 + 1000).toISOString() };
  const egap2 = evento(-4102, 1);
  const gap1 = await registrar(egap1, produto(), identidade("6"));
  const gap2 = await registrar(egap2, produto(), identidade("6"));
  assert.notEqual(gap1.id, gap2.id);
  const [validadeVelha] = await db.rows(`select expira_em,ultima_aparicao_em from public.produtos where id=${gap1.id}`);
  const gapAtrasado = await registrar({ ...evento(-4103, 1),
    data_origem: new Date(inicio - 90 * 60_000).toISOString() }, produto(123), identidade("6"));
  assert.equal(gapAtrasado.id, gap1.id, "Histórico contido não invade a instância mais nova");
  assert.deepEqual((await db.rows(`select expira_em,ultima_aparicao_em from public.produtos where id=${gap1.id}`))[0], validadeVelha);
  assert.equal((await buscar(gap2.id)).preco, 300);
  const eterm = evento(-4111, 1);
  const term = await registrar(eterm, produto(), identidade("5"));
  await db.rows(`select * from public.oferta_remover(${term.id})`);
  const novaAparicaoRemovida = await registrar(evento(-4112, 1, 1), produto(), identidade("5"));
  assert.equal(novaAparicaoRemovida.id, term.id);
  assert.equal(novaAparicaoRemovida.status, "removido");
  assert.equal(await buscar(term.id), undefined);
  ok("histórico dentro de instância fechada não atravessa lacuna; exclusão é terminal na instância");

  const janela1 = evento(-4201, 1);
  const janela2 = evento(-4202, 1);
  const w1 = await registrar(janela1, produto(), identidade(null), 24);
  const w2 = await registrar(janela2, produto(), identidade(null), 48);
  await db.rows(enriquecerSQL(janela1, identidade("8")));
  const [wj] = await db.rows(enriquecerSQL(janela2, identidade("8")));
  assert.equal(wj.id, w2.id);
  assert.notEqual(wj.id, w1.id);
  await db.rows(enriquecerSQL(eventoVelho, identidade("c")));
  assert.equal(await buscar(velha.id), undefined);
  assert.ok(await buscar(nova.id));
  ok("enriquecimento não cruza janela congelada incompatível nem reativa instância expirada");

  const ep1 = evento(-5001, 1, 0);
  const ep2 = evento(-5002, 1, 1);
  const p1 = await registrar(ep1, produto(300), identidade(null));
  const p2 = await registrar(ep2, produto(250), identidade(null));
  await db.rows(`select * from public.oferta_foto(${p2.id},'https://midia.invalid/adotada.jpg')`);
  await db.rows(enriquecerSQL(ep1, identidade("d")));
  // Falha injetada DEPOIS de transferir eventos/aparições deve reverter tudo.
  await db.exec(`create function public.teste_etapa3_falhar() returns trigger language plpgsql as
    $f$begin raise exception 'falha_sintetica_fusao'; end$f$;
    create trigger teste_etapa3_falha before update on public.produtos
      for each row when (new.estado_oferta='fundida') execute function public.teste_etapa3_falhar();
    do $teste$ begin
      begin
        perform public.oferta_enriquecer(${ep2.canal_id},${ep2.msg_id},${literal(identidade("d"))});
        raise exception 'Falha injetada não ocorreu';
      exception when raise_exception then
        if sqlerrm <> 'falha_sintetica_fusao' then raise; end if;
      end;
    end $teste$;
    drop trigger teste_etapa3_falha on public.produtos;
    drop function public.teste_etapa3_falhar();`);
  assert.equal(await contar("oferta_eventos", `produto_id=${p1.id}`), 1);
  assert.equal(await contar("oferta_eventos", `produto_id=${p2.id}`), 1);
  const [fundida] = await db.rows(enriquecerSQL(ep2, identidade("d")));
  assert.equal(fundida.id, Math.min(p1.id, p2.id));
  assert.equal(fundida.status, "fundido");
  assert.equal((await buscar(p2.id)).id, p1.id);
  assert.equal((await buscar(p2.id)).preco, 250);
  assert.equal((await buscar(p2.id)).foto_url, "https://midia.invalid/adotada.jpg");
  assert.equal(await contar("oferta_eventos", `produto_id=${p1.id}`), 2);
  assert.equal(await contar("produto_aparicoes", `produto_id=${p1.id}`), 2);
  assert.equal((await registrar(ep2, produto(250), identidade(null))).id, p1.id);
  assert.equal((await db.rows(enriquecerSQL(ep2, identidade("d"))))[0].id, p1.id);
  ok("rollback durante fusão, menor ID, transferência explícita, decisão inicial intacta e foto adotada");

  assert.equal((await db.rows("select * from public.midia_reservar_remocao('https://midia.invalid/adotada.jpg')"))[0].permitido, false);
  assert.equal((await db.rows(`select * from public.oferta_foto(${p2.id},'https://midia.invalid/sobra.jpg')`))[0].status, "existente");
  assert.equal((await db.rows("select * from public.midia_reservar_remocao('https://midia.invalid/sobra.jpg')"))[0].permitido, true);
  assert.equal((await db.rows(`select * from public.oferta_foto(${provisoria1.id},'https://midia.invalid/sobra.jpg')`))[0].status, "remocao_reservada");
  await db.rows("select * from public.midia_confirmar_remocao('https://midia.invalid/sobra.jpg')");
  assert.equal((await db.rows(`select * from public.oferta_foto(${provisoria1.id},'https://midia.invalid/sobra.jpg')`))[0].status, "remocao_reservada");
  assert.equal((await db.rows("select * from public.midia_reservar_remocao('https://midia.invalid/sobra.jpg')"))[0].permitido, true,
    "Upload repetido depois de DELETE confirmado precisa de nova compensação durável");
  const [removida] = await db.rows(`select * from public.oferta_remover(${p2.id})`);
  assert.equal(removida.id, p1.id);
  assert.equal(await buscar(p1.id), undefined);
  assert.equal(await buscar(p2.id), undefined);
  assert.equal((await db.rows(enriquecerSQL(ep2, identidade("d"))))[0].status, "removido");
  assert.equal((await registrar(ep2, produto(250), identidade(null))).status, "removido");
  assert.equal((await db.rows(`select * from public.oferta_foto(${p2.id},'https://midia.invalid/tardia.jpg')`))[0].status, "removida");
  assert.ok((await db.rows("select * from public.oferta_limpar()" )).some((r) => r.url === "https://midia.invalid/adotada.jpg"));
  ok("reservas impedem vínculo futuro, alias/exclusão terminal e remoção Storage retomável");

  const ecadeia = [evento(-5301, 1), evento(-5302, 1, 1), evento(-5303, 1, 2)];
  const pcadeia = [];
  for (const e of ecadeia) pcadeia.push(await registrar(e, produto(), identidade(null)));
  await db.rows(`select * from public.oferta_foto(${pcadeia[0].id},'https://midia.invalid/sobrevivente.jpg')`);
  await db.rows(`select * from public.oferta_foto(${pcadeia[1].id},'https://midia.invalid/perdedora.jpg')`);
  for (const e of ecadeia) await db.rows(enriquecerSQL(e, identidade("9")));
  for (const p of pcadeia) assert.equal((await buscar(p.id)).id, pcadeia[0].id);
  assert.equal((await buscar(pcadeia[0].id)).foto_url, "https://midia.invalid/sobrevivente.jpg");
  assert.equal(await contar("oferta_eventos", `produto_id=${pcadeia[0].id}`), 3);
  assert.equal(await contar("produtos", `canonico_id=${pcadeia[0].id}`), 2);
  assert.equal(await contar("oferta_midias", "url='https://midia.invalid/perdedora.jpg' and estado='reservada'"), 1);
  ok("três fusões convergem sem cadeia/ciclo; duas fotos preservam a do menor ID e reservam só sobra");

  await db.exec(`update public.produtos set criado_em=now()-interval '30 days' where id=${nova.id};
    update public.produtos set terminal_em=now()-interval '30 days' where id in (${p1.id},${p2.id});`);
  await db.rows("select * from public.oferta_limpar()");
  assert.equal(await contar("produtos", `id=${p1.id}`), 1, "pin não pode expirar por TTL");
  assert.ok(await buscar(nova.id), "criado_em não governa limpeza nova");
  await db.rows(`select * from public.oferta_confirmar(${ep1.canal_id},${ep1.msg_id})`);
  await db.rows(`select * from public.oferta_confirmar(${ep2.canal_id},${ep2.msg_id})`);
  await db.rows("select * from public.oferta_limpar()");
  assert.equal(await contar("produtos", `id=${p1.id}`), 1, "retenção conta depois do ack");
  await db.exec(`update public.oferta_eventos set confirmado_em=now()-interval '8 days' where produto_id=${p1.id};`);
  const purga = await db.rows("select * from public.oferta_limpar()");
  assert.ok(purga.some((r) => r.id === p1.id && r.status === "purgado"));
  assert.equal(await contar("produtos", `id in (${p1.id},${p2.id})`), 0);
  assert.equal(await contar("oferta_eventos", `produto_id=${p1.id}`), 0);
  assert.equal(await contar("produto_aparicoes", `produto_id=${p1.id}`), 0);
  assert.equal((await db.rows(enriquecerSQL(ep2, identidade("d"))))[0].status,"ausente");
  ok("pin recuperável >48h, retenção ≥7d após ack, purga limitada e validade independente de criado_em");

  const resumo = await buscar(r1.id);
  for (const e of await db.rows(`select canal_id,msg_id from public.oferta_eventos where produto_id=${r1.id}`)) {
    await db.rows(`select * from public.oferta_confirmar(${e.canal_id},${e.msg_id})`);
  }
  await db.exec(`update public.oferta_eventos set confirmado_em=now()-interval '8 days' where produto_id=${r1.id};`);
  await db.rows("select * from public.oferta_limpar()");
  assert.equal(await contar("oferta_eventos", `produto_id=${r1.id} and observacao is not null`), 1);
  assert.equal(await contar("oferta_eventos", `produto_id=${r1.id}`), 1);
  const depoisCompactacao = await buscar(r1.id);
  for (const campo of ["preco", "preco_original", "preco_canal_id", "preco_msg_id", "expira_em"]) {
    assert.equal(depoisCompactacao[campo], resumo[campo], campo);
  }
  const vencedor = evento(resumo.preco_canal_id, resumo.preco_msg_id, 4);
  assert.equal((await registrar(vencedor, produto(null))).status, "duplicado");
  assert.equal((await registrar(vencedor, produto(999))).status, "conflito");
  ok("retenção purga mapas/aparições confirmados antigos, conserva vencedor e resumo sem histórico infinito");

  await db.exec("update public.produtos set criado_em=now()-interval '30 days' where id=1;");
  await db.rows("select * from public.oferta_limpar()");
  assert.equal((await db.rows("select estado_oferta from public.produtos where id=1"))[0].estado_oferta, "ativa",
    "Legado não pode ser limpo antes do bot fixar referências recuperáveis");
  const legadoEvento = { ...evento(-7901,77), canal_origem:"username_novo", aliases:["@legado","username_novo"],
    produto_id:1, data_origem:iso() };
  const legadoProduto = {titulo:"Legado sintético",preco:0,link:null};
  const legadoSQL = `select * from public.oferta_legado_registrar(${literal(legadoEvento)},${literal(legadoProduto)},'${"a".repeat(32)}')`;
  const [legadoFixado] = await db.rows(legadoSQL);
  assert.equal(legadoFixado.id,1);
  assert.equal((await db.rows(legadoSQL))[0].id,1);
  assert.equal((await db.rows("select identidade_versao,dedup_hash from public.produtos where id=1"))[0].dedup_hash,"hash_legado");
  assert.equal((await db.rows("select pin from public.oferta_eventos where canal_id=-7901 and msg_id=77"))[0].pin,true);
  await db.rows("select * from public.oferta_legado_pronto()");
  await db.rows("select * from public.oferta_limpar()");
  await db.exec("update public.produtos set terminal_em=now()-interval '30 days' where id=1;");
  await db.rows("select * from public.oferta_limpar()");
  assert.equal(await contar("produtos","id=1"),1);
  ok("migração de referência legada por aliases/ID sem refiltro/hash novo; gate e pin impedem purga");

  // V-ET3-001: username é apresentação, não identidade do evento. Pode ser
  // reutilizado por outro canal enquanto o texto antigo continua congelado.
  const nomeReutilizado = "username_reutilizado";
  const en1 = { ...evento(-99101, 500001), canal_origem: nomeReutilizado };
  const en2 = { ...evento(-99102, 500001), canal_origem: nomeReutilizado };
  const pn1 = await registrar(en1, produto(), identidade(null));
  const pn2 = await registrar(en2, produto(), identidade(null));
  assert.notEqual(pn1.id, pn2.id);
  assert.equal(await contar("oferta_eventos", "canal_id in (-99101,-99102) and msg_id=500001"), 2);
  assert.equal(await contar("produto_aparicoes", "canal_id in (-99101,-99102) and telegram_msg_id=500001"), 2);
  assert.equal((await registrar({ ...en1, canal_origem: "renomeado" }, produto(), identidade(null))).id, pn1.id);
  assert.equal((await buscar(pn1.id)).canal_origem, nomeReutilizado);
  ok("V-ET3-001: provisórios de canais distintos não colidem por username/mensagem");

  const es1 = { ...evento(-99201, 500002), canal_origem: nomeReutilizado };
  const es2 = { ...evento(-99202, 500002), canal_origem: nomeReutilizado };
  const forteNumerica = identidade("a", { loja: "sintetica", variante: "numerica_equivalente" });
  const ps1 = await registrar(es1, produto(), forteNumerica);
  const ps2 = await registrar(es2, produto(), forteNumerica);
  assert.equal(ps1.id, ps2.id);
  assert.equal(await contar("oferta_eventos", `produto_id=${ps1.id}`), 2);
  assert.equal(await contar("produto_aparicoes", `produto_id=${ps1.id}`), 2);
  assert.equal((await registrar(es2, produto(), forteNumerica)).id, ps1.id);
  const separada = await registrar({ ...evento(-99203, 500002), canal_origem: nomeReutilizado }, produto(),
    identidade("a", { loja: "sintetica", variante: "numerica_incompativel" }));
  assert.notEqual(separada.id, ps1.id);
  ok("V-ET3-001: oferta forte reúne duas aparições numéricas sem bloquear variante diferente");

  for (const legadoPrimeiro of [true, false]) {
    await db.exec("begin;");
    const nome = `colisao_legado_${legadoPrimeiro}`;
    const e = { ...evento(-99301, 500003), canal_origem: nome };
    let versionada;
    if (!legadoPrimeiro) versionada = await registrar(e, produto(), identidade(null));
    const antigo = await legadoAntigo(nome, e.msg_id);
    if (legadoPrimeiro) versionada = await registrar(e, produto(), identidade(null));
    assert.notEqual(versionada.id, antigo.p.id);
    assert.deepEqual((await db.rows(`select * from public.produtos where id=${antigo.p.id}`))[0], antigo.p);
    assert.deepEqual((await db.rows(`select * from public.produto_aparicoes where id=${antigo.a.id}`))[0], antigo.a);
    assert.equal((await buscar(versionada.id)).canal_origem, nome);
    assert.equal(await contar("produto_aparicoes", `canal_origem='${nome}' and telegram_msg_id=${e.msg_id}`), 2);
    const dados = await dadosOfertas();
    assert.equal((await registrar({ ...e, canal_origem: "novo_username" }, produto(), identidade(null))).id, versionada.id);
    assert.deepEqual(await dadosOfertas(), dados);
    await db.exec("rollback;");
  }
  ok("V-ET3-001: legado sem número e v2 coexistem nas duas ordens, sem mutar legado ou usernames");

  for (const mesmoHash of [false, true]) {
    await db.exec("begin;");
    const nome = `rpc_legada_${mesmoHash}`;
    const ea = { ...evento(-99401, 500004), canal_origem: nome, aliases: [nome] };
    const eb = { ...evento(-99402, 500004), canal_origem: nome, aliases: [`@${nome.toUpperCase()}`] };
    const hashA = "1".repeat(32); const hashB = (mesmoHash ? "1" : "2").repeat(32);
    const la = await registrarLegado(ea, produto(51), hashA);
    const lb = await registrarLegado(eb, produto(52), hashB);
    assert.equal(la.status, "novo");
    assert.equal(lb.status, mesmoHash ? "duplicado" : "novo");
    if (mesmoHash) assert.equal(lb.id, la.id);
    else assert.notEqual(lb.id, la.id);
    assert.deepEqual(await db.rows(`select canal_id,telegram_msg_id,produto_id,canal_origem
      from public.produto_aparicoes where canal_id in (-99401,-99402) order by canal_id desc`), [
      { canal_id: ea.canal_id, telegram_msg_id: ea.msg_id, produto_id: la.id, canal_origem: nome },
      { canal_id: eb.canal_id, telegram_msg_id: eb.msg_id, produto_id: lb.id, canal_origem: nome },
    ]);
    assert.deepEqual(await db.rows(`select canal_id,resultado_inicial from public.oferta_eventos
      where canal_id in (-99401,-99402) order by canal_id desc`), [
      { canal_id: ea.canal_id, resultado_inicial: "novo" },
      { canal_id: eb.canal_id, resultado_inicial: mesmoHash ? "duplicado" : "novo" },
    ]);
    const dados = await dadosOfertas();
    for (const [e, p, hash, id, status] of [
      [ea, produto(51), hashA, la.id, "retomado"],
      [eb, produto(52), hashB, lb.id, mesmoHash ? "duplicado" : "retomado"],
    ]) {
      assert.deepEqual(await registrarLegado({ ...e, canal_origem: "renomeado", aliases: ["renomeado"] }, p, hash),
        { id, status, foto_url: null });
    }
    assert.deepEqual(await dadosOfertas(), dados);
    await db.exec("rollback;");
  }
  ok("RPC legada: username compartilhado separa hashes distintos, deduplica hash igual e conserva dois eventos numéricos/retries");

  await db.exec("begin;");
  const ev2 = { ...evento(-99501, 500005), canal_origem: "nao_adotar_v2" };
  const pv2 = await registrar(ev2, produto(), identidade(null));
  const v2Antes = (await db.rows(`select * from public.produtos where id=${pv2.id}`))[0];
  const apV2Antes = await db.rows(`select * from public.produto_aparicoes where produto_id=${pv2.id}`);
  const elv2 = { ...evento(-99502, ev2.msg_id), canal_origem: ev2.canal_origem, aliases: ["@NAO_ADOTAR_V2"] };
  const lv2 = await registrarLegado(elv2, produto(), "3".repeat(32));
  assert.equal(lv2.status, "novo");
  assert.notEqual(lv2.id, pv2.id);
  assert.deepEqual((await db.rows(`select * from public.produtos where id=${pv2.id}`))[0], v2Antes);
  assert.deepEqual(await db.rows(`select * from public.produto_aparicoes where produto_id=${pv2.id}`), apV2Antes);
  assert.equal((await db.rows(`select identidade_versao,canal_id from public.produtos where id=${lv2.id}`))[0].identidade_versao, null);
  await db.exec("rollback;");
  ok("RPC legada não adota produto/aparição v2 por texto correspondente");

  await db.exec("begin;");
  const original = await legadoAntigo("@CaSe_Legado", 500006);
  await db.exec(`update public.produto_aparicoes set canal_origem='cAsE_lEgAdO' where id=${original.a.id};`);
  original.a = (await db.rows(`select * from public.produto_aparicoes where id=${original.a.id}`))[0];
  const eOriginal = { ...evento(-99601, 500006), canal_origem: "username_atual",
    aliases: ["@CASE_LEGADO", "username_atual"], data_origem: "2020-01-01T01:00:00.000Z" };
  const lOriginal = await registrarLegado(eOriginal, produto(999), "4".repeat(32));
  assert.deepEqual(lOriginal, { id: original.p.id, status: "retomado", foto_url: null });
  assert.deepEqual((await db.rows(`select * from public.produtos where id=${original.p.id}`))[0],
    { ...original.p, canal_id: eOriginal.canal_id });
  assert.deepEqual((await db.rows(`select * from public.produto_aparicoes where id=${original.a.id}`))[0],
    { ...original.a, canal_id: eOriginal.canal_id });
  assert.equal(await contar("produto_aparicoes", `produto_id=${original.p.id}`), 1);
  const originalFixado = await dadosOfertas();
  assert.deepEqual(await registrarLegado({ ...eOriginal, canal_origem: "renomeado_de_novo", aliases: ["outro"] },
    produto(999), "4".repeat(32)), lOriginal);
  assert.deepEqual(await dadosOfertas(), originalFixado);
  await db.exec("rollback;");
  ok("legado >48h por alias/case/@ mantém IDs/hash/preços/identidade/grafia/tempos; somente ownership pontual e retry exato");

  for (const donoRenomeado of [false, true]) {
    await db.exec("begin;");
    const retido = await legadoAntigo("origem_retida", 500007);
    // Mapa estrangeiro sem aparição OU com outro nome após renomeação protege
    // a origem. Grafia diferente não prova que se trata de uma dedup alheia.
    await db.exec(`insert into public.oferta_eventos(canal_id,msg_id,produto_id,decisao_hash,recebido_em)
      values(-99701,500007,${retido.p.id},'fixture_retida','2020-01-01T01:00:00Z');`);
    if (donoRenomeado) await db.exec(`insert into public.produto_aparicoes
      (produto_id,canal_origem,telegram_msg_id,canal_id)
      values(${retido.p.id},'nome_atual_do_dono',500007,-99701);`);
    const retidosAntes = await dadosOfertas();
    const tentativa = { ...evento(-99702, 500007), canal_origem: "origem_retida", aliases: ["@ORIGEM_RETIDA"] };
    const naoRoubado = await registrarLegado(tentativa, produto(), "5".repeat(32));
    assert.equal(naoRoubado.status, "novo");
    assert.notEqual(naoRoubado.id, retido.p.id);
    for (const [tabela, linhas] of Object.entries(retidosAntes)) {
      const atuais = await db.rows(`select * from public.${tabela} order by 1,2`);
      for (const antiga of linhas) assert.ok(atuais.some((a) => JSON.stringify(a) === JSON.stringify(antiga)),
        `Não alterar dado/ownership retido: ${tabela}`);
    }
    await db.exec("rollback;");
  }

  await db.exec("begin;");
  const compartilhado = await legadoAntigo("origem_genuina", 500008);
  // Outro alias no MESMO msg_id é ambíguo (pode ser renomeação). O checkpoint
  // explícito prova o vínculo, não a posse da origem: reconciliar sem inventá-la.
  await db.exec(`insert into public.produto_aparicoes(produto_id,canal_origem,telegram_msg_id,canal_id)
    values(${compartilhado.p.id},'outro_alias',500008,-99801),(${compartilhado.p.id},'terceiro_alias',500009,-99802);
    insert into public.oferta_eventos(canal_id,msg_id,produto_id,decisao_hash,recebido_em)
    values(-99801,500008,${compartilhado.p.id},'fixture_outro_alias',now()),
      (-99802,500009,${compartilhado.p.id},'fixture_outro_evento',now());`);
  const outrosAntes = await db.rows(`select * from public.produto_aparicoes where canal_id in (-99801,-99802) order by id`);
  const mapasAntes = await db.rows(`select * from public.oferta_eventos where canal_id in (-99801,-99802) order by canal_id`);
  const checkpoint = { ...evento(-99803, 500008), canal_origem: "renomeado_original",
    aliases: ["@ORIGEM_GENUINA"], produto_id: compartilhado.p.id, data_origem: "2020-01-01T01:00:00.000Z" };
  const reconciliado = await registrarLegado(checkpoint, produto(), "6".repeat(32));
  assert.equal(reconciliado.id, compartilhado.p.id);
  assert.equal(reconciliado.status, "duplicado");
  assert.deepEqual((await db.rows(`select * from public.produtos where id=${compartilhado.p.id}`))[0],
    compartilhado.p);
  assert.deepEqual((await db.rows(`select * from public.produto_aparicoes where id=${compartilhado.a.id}`))[0],
    compartilhado.a);
  assert.equal(await contar("produto_aparicoes", `produto_id=${compartilhado.p.id}
    and canal_id=${checkpoint.canal_id} and telegram_msg_id=500008`), 1);
  assert.deepEqual(await db.rows(`select * from public.produto_aparicoes where canal_id in (-99801,-99802) order by id`), outrosAntes);
  assert.deepEqual(await db.rows(`select * from public.oferta_eventos where canal_id in (-99801,-99802) order by canal_id`), mapasAntes);
  const checkpointFixado = await dadosOfertas();
  assert.deepEqual(await registrarLegado(checkpoint, produto(), "6".repeat(32)), reconciliado);
  assert.deepEqual(await dadosOfertas(), checkpointFixado);
  await db.exec("rollback;");
  ok("ownership retido bloqueia roubo textual, mas aliases/eventos alheios no mesmo card não bloqueiam checkpoint genuíno");

  await db.exec("begin;");
  const sobreviventeLegado = await legadoAntigo("origem_canonicadesconhecida", 500013);
  const aliasLegado = await legadoAntigo("origem_alias", 500014);
  await db.exec(`update public.produtos set estado_oferta='fundida',canonico_id=${sobreviventeLegado.p.id},terminal_em=now()
    where id=${aliasLegado.p.id};`);
  const produtosAliasAntes = await db.rows(`select * from public.produtos where id in
    (${sobreviventeLegado.p.id},${aliasLegado.p.id}) order by id`);
  const eAliasLegado = { ...evento(-99811, 500014), canal_origem: "origem_alias", aliases: ["origem_alias"],
    produto_id: sobreviventeLegado.p.id };
  const aliasReconciliado = await registrarLegado(eAliasLegado, produto(), "7".repeat(32));
  assert.equal(aliasReconciliado.id, sobreviventeLegado.p.id);
  assert.deepEqual(await db.rows(`select * from public.produtos where id in
    (${sobreviventeLegado.p.id},${aliasLegado.p.id}) order by id`), produtosAliasAntes,
  "Evidência da origem de alias não atribui posse à origem do sobrevivente");
  assert.deepEqual((await db.rows(`select * from public.produto_aparicoes where id=${aliasLegado.a.id}`))[0],
    { ...aliasLegado.a, canal_id: eAliasLegado.canal_id });
  assert.equal((await registrarLegado(eAliasLegado, produto(), "7".repeat(32))).id, sobreviventeLegado.p.id);
  await db.exec("rollback;");
  ok("reconciliação canônica preserva origem do sobrevivente e identidade da aparição legada do alias");

  await db.exec("begin;");
  const donoCanonico = await legadoAntigo("origem_dono_canonico", 500015);
  const aliasComDono = await legadoAntigo("origem_alias_com_dono", 500016);
  await db.exec(`update public.produtos set estado_oferta='fundida',canonico_id=${donoCanonico.p.id},terminal_em=now()
    where id=${aliasComDono.p.id};
    insert into public.produto_aparicoes(produto_id,canal_origem,telegram_msg_id,canal_id)
      values(${donoCanonico.p.id},'nome_atual_dono_canonico',500016,-99821);
    insert into public.oferta_eventos(canal_id,msg_id,produto_id,decisao_hash,recebido_em)
      values(-99821,500016,${donoCanonico.p.id},'fixture_dono_canonico',now());`);
  const posseCanonicaAntes = await dadosOfertas();
  const outroCanalAlias = { ...evento(-99822, 500016), canal_origem: "origem_alias_com_dono",
    aliases: ["origem_alias_com_dono"] };
  const aliasNaoRoubado = await registrarLegado(outroCanalAlias, produto(), "8".repeat(32));
  assert.notEqual(aliasNaoRoubado.id, donoCanonico.p.id);
  assert.equal(aliasNaoRoubado.status, "novo");
  for (const [tabela, linhas] of Object.entries(posseCanonicaAntes)) {
    const atuais = await db.rows(`select * from public.${tabela} order by 1,2`);
    for (const antiga of linhas) assert.ok(atuais.some((a) => JSON.stringify(a) === JSON.stringify(antiga)),
      `Ownership canônico retido não pode ser roubado por alias: ${tabela}`);
  }
  await db.exec("rollback;");
  ok("mapa estrangeiro no sobrevivente protege também origem/aparição ainda sem número do alias");

  // Os fixtures permanentes acima já possuem duplicatas textuais permitidas
  // tanto em produtos provisórios quanto nas aparições fortes do mesmo card.
  await db.exec("begin;");
  await legadoAntigo("legado_sem_backfill", 500012);
  const dadosReaplicacao = await dadosOfertas();
  const indicesReaplicacao = await indicesOfertas();
  await db.exec(bloco);
  assert.deepEqual(await dadosOfertas(), dadosReaplicacao, "Bloco não faz backfill");
  assert.deepEqual(await indicesOfertas(), indicesReaplicacao);
  await db.exec(schema);
  assert.deepEqual(await dadosOfertas(), dadosReaplicacao, "Schema completo não recria globais nem faz backfill");
  assert.deepEqual(await indicesOfertas(), indicesReaplicacao);
  await db.exec("rollback;");
  ok("reaplicação do bloco e schema completo após duplicatas textuais preserva todas as linhas e índices");

  const revisao3 = { db, evento, produto, identidade, literal, registrar, registrarSQL,
    enriquecerSQL, buscar, contar, dadosOfertas, ok };
  await validarRevisao3(revisao3);

  if (!modulo) {
    const a = abrir(); const b = abrir();
    await a.exec("set role service_role;");
    await b.exec("set role service_role;");
    const [pidA] = await a.rows("select pg_backend_pid() as pid");
    const [pidB] = await b.rows("select pg_backend_pid() as pid");
    assert.notEqual(pidA.pid, pidB.pid);
    async function disputar(sqlA, sqlB) {
      await a.exec("begin; select pg_advisory_xact_lock(730030003::bigint);");
      const resultadoA = await a.rows(sqlA);
      const pendente = b.rows(sqlB);
      // Registrar rejeição imediatamente para não esconder timeout de sessão.
      pendente.catch(() => {});
      await bloqueada(pidB.pid);
      await a.exec("commit;");
      return [resultadoA, await pendente];
    }
    await validarRevisao3Concorrente({ ...revisao3, disputar });
    const ec1 = evento(-6001, 1, 10);
    const ec2 = evento(-6002, 1, 11);
    const [ca, cb] = await disputar(registrarSQL(ec1, produto(123), identidade("e")), registrarSQL(ec2, produto(234), identidade("e")));
    assert.equal(ca[0].id, cb[0].id);
    assert.equal(await contar("oferta_eventos", `produto_id=${ca[0].id}`), 2);
    assert.equal((await buscar(ca[0].id)).preco, 234);
    const ec3 = evento(-6003, 1, 12);
    const [mesmoA, mesmoB] = await disputar(registrarSQL(ec3, produto(), identidade("f")), registrarSQL(ec3, produto(), identidade("f")));
    assert.equal(mesmoA[0].id, mesmoB[0].id);
    assert.equal(mesmoB[0].status, "retomado");
    assert.equal(await contar("oferta_eventos", `produto_id=${mesmoA[0].id}`), 1);
    assert.equal(await contar("produto_aparicoes", `produto_id=${mesmoA[0].id}`), 1);
    ok(`duas sessões reais (${pidA.pid} ≠ ${pidB.pid}), primeira criação e mesmo evento com barreira pg_locks`);

    for (const forte of [false, true]) {
      const nome = `username_concorrente_${forte}`;
      const ea = { ...evento(forte ? -99911 : -99901, forte ? 500011 : 500010, 20), canal_origem: nome };
      const eb = { ...evento(forte ? -99912 : -99902, ea.msg_id, 21), canal_origem: nome };
      const identidadeConcorrente = forte
        ? identidade("0", { loja: "sintetica", variante: "concorrente_numerica" }) : identidade(null);
      const [ra, rb] = await disputar(registrarSQL(ea, produto(), identidadeConcorrente),
        registrarSQL(eb, produto(), identidadeConcorrente));
      assert.equal(ra[0].status, "novo");
      assert.equal(rb[0].status, forte ? "atualizado" : "novo");
      if (forte) assert.equal(ra[0].id, rb[0].id);
      else assert.notEqual(ra[0].id, rb[0].id);
      assert.deepEqual(await db.rows(`select canal_id,telegram_msg_id,produto_id,canal_origem
        from public.produto_aparicoes where canal_id in (${ea.canal_id},${eb.canal_id}) order by canal_id desc`), [
        { canal_id: ea.canal_id, telegram_msg_id: ea.msg_id, produto_id: ra[0].id, canal_origem: nome },
        { canal_id: eb.canal_id, telegram_msg_id: eb.msg_id, produto_id: rb[0].id, canal_origem: nome },
      ]);
      assert.equal(await contar("oferta_eventos", `canal_id in (${ea.canal_id},${eb.canal_id}) and msg_id=${ea.msg_id}`), 2);
      assert.equal(await contar("produto_aparicoes", `produto_id in (${ra[0].id},${rb[0].id})`), 2);
      assert.equal((await buscar(ra[0].id)).canal_origem, nome);
      assert.equal((await buscar(rb[0].id)).canal_origem, nome);
      const dados = await dadosOfertas();
      const [retryA] = await a.rows(registrarSQL({ ...ea, canal_origem: "renomeado_a" }, produto(), identidadeConcorrente));
      const [retryB] = await b.rows(registrarSQL({ ...eb, canal_origem: "renomeado_b" }, produto(), identidadeConcorrente));
      assert.equal(retryA.id, ra[0].id);
      assert.equal(retryA.status, "retomado");
      assert.equal(retryB.id, rb[0].id);
      assert.equal(retryB.status, forte ? "duplicado" : "retomado");
      assert.deepEqual(await dadosOfertas(), dados);
    }
    ok("V-ET3-001 concorrente: mesmo username/mensagem em duas sessões cria provisórios separados ou duas aparições fortes; retries exatos");

    // Ordem de COMMIT oposta à ordem temporal: a observação mais nova vence.
    await disputar(registrarSQL(evento(-6004, 1, 14), produto(150), identidade("e")),
      registrarSQL(evento(-6005, 1, 13), produto(99), identidade("e")));
    assert.equal((await buscar(ca[0].id)).preco, 150);
    ok("recência determinística sob commits concorrentes em ordem temporal inversa");

    const ef1 = evento(-7001, 1, 15); const ef2 = evento(-7002, 1, 16);
    const pf1 = await registrar(ef1, produto(), identidade(null));
    const pf2 = await registrar(ef2, produto(), identidade(null));
    await db.rows(enriquecerSQL(ef1, identidade("1")));
    const [fusa, excluida] = await disputar(enriquecerSQL(ef2, identidade("1")), `select * from public.oferta_remover(${pf2.id})`);
    assert.equal(fusa[0].id, Math.min(pf1.id, pf2.id));
    assert.equal(excluida[0].id, fusa[0].id);
    assert.equal(await buscar(pf2.id), undefined);
    const er = evento(-7101, 1, 17);
    const pr = await registrar(er, produto(), identidade(null));
    const [, tardia] = await disputar(`select * from public.oferta_remover(${pr.id})`, enriquecerSQL(er, identidade("2")));
    assert.equal(tardia[0].status, "removido");
    ok("fusão→exclusão por alias e exclusão→enriquecimento concorrentes: terminal vence");

    const em = evento(-7201, 1, 18);
    const pm = await registrar(em, produto(), identidade(null));
    const [reserva, foto] = await disputar("select * from public.midia_reservar_remocao('https://midia.invalid/corrida.jpg')",
      `select * from public.oferta_foto(${pm.id},'https://midia.invalid/corrida.jpg')`);
    assert.equal(reserva[0].permitido, true);
    assert.equal(foto[0].status, "remocao_reservada");
    const [vinculo, negacao] = await disputar(`select * from public.oferta_foto(${pm.id},'https://midia.invalid/protegida.jpg')`,
      "select * from public.midia_reservar_remocao('https://midia.invalid/protegida.jpg')");
    assert.equal(vinculo[0].status, "atualizada");
    assert.equal(negacao[0].permitido, false);
    await disputar("select * from public.oferta_limpar()", enriquecerSQL(em, identidade("3")));
    assert.equal((await buscar(pm.id)).foto_url, "https://midia.invalid/protegida.jpg");
    ok("reserva↔vínculo de foto em ambas as ordens e limpeza concorrente sem apagar referência");
    // Relógio local de ingestão adiantado não invalida preço original comprovado.
    const adiantada = {...evento(-7301,1,19), recebido_em:new Date(Date.now()+60000).toISOString()};
    const relogio = await registrar(adiantada,produto(42),identidade("4"));
    assert.equal((await buscar(relogio.id)).preco,42);
    assert.equal(Date.parse((await buscar(relogio.id)).expira_em),Date.parse(adiantada.data_origem)+48*3600000);
    ok("recepção adiantada não descarta oferta nem troca tempo original por relógio de ingestão");

    await db.exec(`update public.produtos set terminal_em=now()-interval '8 days' where canonico_id=${pcadeia[0].id};`);
    await db.rows("select * from public.oferta_limpar()");
    assert.equal(await contar("produtos",`canonico_id=${pcadeia[0].id}`),2);
    await db.exec(`update public.oferta_eventos set pin=false,confirmado_em=now()-interval '8 days' where produto_id=${pcadeia[0].id};`);
    await db.rows("select * from public.oferta_limpar()");
    assert.equal(await contar("produtos",`canonico_id=${pcadeia[0].id}`),0);
    assert.equal((await buscar(pcadeia[0].id)).foto_url,"https://midia.invalid/sobrevivente.jpg");
    await db.rows("select * from public.midia_confirmar_remocao('https://midia.invalid/sobra.jpg')");
    await db.exec("update public.oferta_midias set confirmado_em=now()-interval '8 days' where url='https://midia.invalid/sobra.jpg';");
    await db.rows("select * from public.oferta_limpar()");
    assert.equal(await contar("oferta_midias","url='https://midia.invalid/sobra.jpg'"),1);
    await db.exec("update public.oferta_eventos set pin=false,confirmado_em=now()-interval '8 days';");
    await db.rows("select * from public.oferta_limpar()");
    assert.equal(await contar("oferta_midias","url='https://midia.invalid/sobra.jpg'"),0);
    ok("aliases e tombstones confirmados expiram após retenção, nunca com referência recuperável");
    console.log(`SQL etapa 3: ${aprovados} grupos aprovados em PostgreSQL real; banco sintético preservado para inspeção.`);
  } else {
    console.error(`SQL etapa 3: ${aprovados} grupos DDL/semântica aprovados em PGlite. CONCORRÊNCIA IMPEDIDA, não validada.`);
    process.exitCode = 2;
  }
} finally {
  await Promise.allSettled(sessoes.map((s) => s.close()));
  if (pglite) await pglite.close();
}
