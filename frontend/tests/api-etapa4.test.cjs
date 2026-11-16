// Cliente real, token/rede/relógio sintéticos; nunca importa Supabase ou env reais.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const ts = require("typescript");

function ambiente(resposta, getSession = async () => ({ data: { session: { access_token: "token-ficticio" } } })) {
  const chamadas = [];
  const modulo = { exports: {} };
  const fonte = fs.readFileSync(path.join(__dirname, "../lib/api.ts"), "utf8");
  const js = ts.transpileModule(fonte, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  class DataFalsa extends Date { static now() { return Date.parse("2026-11-10T12:00:00Z"); } }
  vm.runInNewContext(`(function(require,module,exports){${js}\n})`, {
    process: { env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:54328/api" } }, Date: DataFalsa, Error, DOMException,
    fetch: async (...args) => { chamadas.push(args); return typeof resposta === "function" ? resposta(...args) : resposta; },
  })((nome) => {
    assert.equal(nome, "./supabase");
    return { supabase: { auth: { getSession } } };
  }, modulo, modulo.exports);
  return { ...modulo.exports, chamadas };
}

test("GET autenticado envia AbortSignal/no-store e preserva resposta válida vazia", async () => {
  const a = ambiente(new Response("[]", { status: 200 }));
  const controle = new AbortController();
  assert.deepEqual(await a.api.get("/produtos", { signal: controle.signal }), []);
  const [url, opcoes] = a.chamadas[0];
  assert.equal(url, "http://127.0.0.1:54328/api/produtos");
  assert.equal(opcoes.cache, "no-store");
  assert.equal(opcoes.signal, controle.signal);
  assert.equal(opcoes.headers.Authorization, "Bearer token-ficticio");
});

test("abortar encerra espera de Auth pendente sem fetch tardio nem novas consultas SDK acumuladas", async () => {
  let resolver, consultas = 0;
  const sessao = new Promise(resolve => { resolver = resolve; });
  const a = ambiente(new Response("[]"), () => { consultas += 1; return sessao; });
  const { getEventListeners } = require("node:events");
  const drenar = async () => { for (let i = 0; i < 16; i += 1) await Promise.resolve(); };
  for (let i = 0; i < 3; i += 1) {
    const controle = new AbortController();
    let erro;
    const chamada = a.api.get("/produtos", { signal: controle.signal }).catch(e => { erro = e; });
    await drenar();
    controle.abort();
    await drenar();
    assert.equal(erro?.name, "AbortError", "timeout deve terminar mesmo com getSession sem resposta");
    await chamada;
    assert.equal(getEventListeners(controle.signal, "abort").length, 0);
  }
  assert.equal(consultas, 1, "retries não acumulam consultas de sessão pendentes");
  resolver({ data: { session: { access_token: "token-atrasado" } } });
  await drenar();
  assert.equal(a.chamadas.length, 0, "sessão tardia não dispara GET cancelado");
  await a.api.get("/produtos");
  assert.equal(consultas, 2);
  assert.equal(a.chamadas.length, 1);
});

test("consumidor da sessão B não recebe token A do SDK iniciado antes da troca", async () => {
  let concluirA, consultas = 0;
  const pendenteA = new Promise(resolve => { concluirA = resolve; });
  const a = ambiente(new Response("[]"), () => {
    consultas += 1;
    return consultas === 1 ? pendenteA : Promise.resolve({ data: { session: { access_token: "token-B" } } });
  });
  const drenar = async () => { for (let i = 0; i < 16; i += 1) await Promise.resolve(); };
  const controleA = new AbortController();
  const antiga = a.api.get("/produtos", { signal: controleA.signal });
  await drenar(); assert.equal(consultas, 1);
  controleA.abort();
  await assert.rejects(antiga, e => e.name === "AbortError");
  // Auth já anunciou B e a página abriu uma geração nova antes de A concluir.
  const controleB = new AbortController();
  const atual = a.api.get("/produtos", { signal: controleB.signal });
  await drenar(); assert.equal(consultas, 1, "não sobrepor a consulta SDK pendente");
  concluirA({ data: { session: { access_token: "token-A" } } });
  await atual;
  assert.equal(consultas, 2, "B exige consulta iniciada depois de sua entrada");
  assert.equal(a.chamadas.length, 1, "não disparar request cancelada de A");
  assert.equal(a.chamadas[0][1].headers.Authorization, "Bearer token-B");
});

test("consumidores do mesmo tick compartilham lote; consumidor posterior exige lote novo", async () => {
  let concluir, consultas = 0;
  const pendente = new Promise(resolve => { concluir = resolve; });
  const a = ambiente(() => new Response("[]"), () => {
    consultas += 1;
    return consultas === 1 ? pendente : Promise.resolve({ data: { session: { access_token: "token-novo" } } });
  });
  const lista = a.api.get("/produtos");
  const stats = a.api.get("/produtos/estatisticas");
  for (let i = 0; i < 16; i += 1) await Promise.resolve();
  assert.equal(consultas, 1);
  const posterior = a.api.get("/filtros");
  concluir({ data: { session: { access_token: "token-inicial" } } });
  await Promise.all([lista, stats, posterior]);
  assert.equal(consultas, 2);
  assert.deepEqual(a.chamadas.map(([, opcoes]) => opcoes.headers.Authorization),
    ["Bearer token-inicial", "Bearer token-inicial", "Bearer token-novo"]);
});

test("erro do SDK antigo não é distribuído ao consumidor que chegou depois", async () => {
  let rejeitar, consultas = 0;
  const pendente = new Promise((_, reject) => { rejeitar = reject; });
  const a = ambiente(new Response("[]"), () => {
    consultas += 1;
    return consultas === 1 ? pendente : Promise.resolve({ data: { session: { access_token: "token-B" } } });
  });
  const primeira = a.api.get("/produtos");
  const erroPrimeira = assert.rejects(primeira, /erro-antigo/);
  for (let i = 0; i < 16; i += 1) await Promise.resolve();
  const segunda = a.api.get("/produtos");
  rejeitar(new Error("erro-antigo"));
  await erroPrimeira;
  await segunda;
  assert.equal(consultas, 2);
  assert.equal(a.chamadas[0][1].headers.Authorization, "Bearer token-B");
});

test("cancelar consumidores de lotes seguintes não agenda SDK extra nem retém listeners", async () => {
  let concluir, consultas = 0;
  const pendente = new Promise(resolve => { concluir = resolve; });
  const a = ambiente(new Response("[]"), () => { consultas += 1; return pendente; });
  const { getEventListeners } = require("node:events");
  const controles = [new AbortController(), new AbortController(), new AbortController()];
  const promessas = [a.api.get("/produtos", { signal: controles[0].signal }).catch(e => e.name)];
  for (let i = 0; i < 16; i += 1) await Promise.resolve();
  for (const controle of controles.slice(1)) {
    promessas.push(a.api.get("/produtos", { signal: controle.signal }).catch(e => e.name));
  }
  controles.forEach(c => c.abort());
  assert.deepEqual(await Promise.all(promessas), ["AbortError", "AbortError", "AbortError"]);
  concluir({ data: { session: { access_token: "token-antigo" } } });
  for (let i = 0; i < 32; i += 1) await Promise.resolve();
  assert.equal(consultas, 1);
  assert.equal(a.chamadas.length, 0);
  controles.forEach(c => assert.equal(getEventListeners(c.signal, "abort").length, 0));
});

test("sinal já abortado não consulta Auth; rejeição de Auth permite próxima consulta", async () => {
  let consultas = 0;
  const a = ambiente(new Response("[]"), async () => {
    consultas += 1;
    if (consultas === 1) throw new Error("auth-sintetico-offline");
    return { data: { session: null } };
  });
  const controle = new AbortController(); controle.abort();
  await assert.rejects(a.api.get("/produtos", { signal: controle.signal }), e => e.name === "AbortError");
  assert.equal(consultas, 0);
  await assert.rejects(a.api.get("/produtos"), /auth-sintetico-offline/);
  await a.api.get("/produtos");
  assert.equal(a.chamadas.length, 1);
  assert.equal(a.chamadas[0][1].headers.Authorization, undefined);
});

test("controlador real libera timeout de GET parado no Auth e retenta com recuo", async () => {
  const fonte = fs.readFileSync(path.join(__dirname, "../lib/polling.ts"), "utf8");
  const js = ts.transpileModule(fonte, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const modulo = { exports: {} };
  vm.runInThisContext(`(function(module,exports){${js}\n})`)(modulo, modulo.exports);
  const { ControladorPolling, PortaoPolling } = modulo.exports;
  let consultas = 0;
  const a = ambiente(new Response("[]"), () => { consultas += 1; return new Promise(() => {}); });
  let agora = 0, sequencia = 0, disparos = 0;
  const timers = new Map(), erros = [];
  const drenar = async () => { for (let i = 0; i < 32; i += 1) await Promise.resolve(); };
  const avancar = async ms => {
    const fim = agora + ms;
    while (true) {
      const proximo = [...timers].filter(([, t]) => t.quando <= fim).sort((a, b) => a[1].quando - b[1].quando)[0];
      if (!proximo) break;
      const [id, timer] = proximo; timers.delete(id); agora = timer.quando; timer.fn(); await drenar();
    }
    agora = fim; await drenar();
  };
  const ciclo = new ControladorPolling({ intervalo: 5000, timeout: 10000, recuo: new PortaoPolling(), compartilhado: new PortaoPolling(),
    agora: () => agora, agendar: (fn, ms) => { const id = ++sequencia; timers.set(id, { fn, quando: agora + ms }); return id; },
    cancelar: id => timers.delete(id), executar: signal => { disparos += 1; return a.api.get("/produtos", { signal }); },
    sucesso: () => assert.fail("Auth continua pendente"), falha: (erro, tentativa) => { erros.push({ nome: erro.name, tentativa }); return { espera: 10000 }; } });
  ciclo.iniciar(); await drenar();
  await avancar(9999); assert.equal(disparos, 1); assert.equal(erros.length, 0);
  await avancar(1); assert.deepEqual(erros, [{ nome: "AbortError", tentativa: 1 }]);
  await avancar(9999); assert.equal(disparos, 1);
  await avancar(1); assert.equal(disparos, 2); assert.equal(consultas, 1);
  ciclo.parar(); await drenar();
  assert.equal(timers.size, 0); assert.equal(a.chamadas.length, 0);
});

test("429 preserva Retry-After em segundos e HTTP-date acima do teto de 60 s", async () => {
  for (const [header, espera] of [["125", 125000], ["Tue, 10 Nov 2026 12:03:05 GMT", 185000]]) {
    const a = ambiente(new Response('{"erro":"limite"}', { status: 429, headers: { "Retry-After": header } }));
    await assert.rejects(a.api.get("/produtos"), erro => erro instanceof a.ErroApi && erro.status === 429 && erro.retryAfterMs === espera);
  }
});

test("401 e 5xx continuam erros, mesmo com JSON inválido; Retry-After inválido não inventa prazo", async () => {
  for (const status of [401, 503]) {
    const a = ambiente(new Response("sem-json", { status, headers: { "Retry-After": "invalido" } }));
    await assert.rejects(a.api.get("/produtos"), erro => erro instanceof a.ErroApi && erro.status === status && erro.retryAfterMs === null);
  }
});
