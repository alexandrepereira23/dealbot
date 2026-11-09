// Fixtures sintéticas; sem env, servidor, Auth ou acesso a Supabase real.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createClient } from "@supabase/supabase-js";
import { criarProdutoModel } from "../src/models/produto.model.js";
import { criarProdutoService, ProdutoService } from "../src/services/produto.service.js";
import router from "../src/routes/produto.routes.js";
import { errorHandler } from "../src/middlewares/error.middleware.js";

const AGORA = Date.parse("2026-11-05T12:00:00Z");
const APOS = "2026-11-06T12:00:00Z";
const CORTE = "2026-11-03T12:00:00.000Z";
const publico = { id: 1, titulo: "Oferta sintética", preco: 250, preco_original: 400,
  cupom: "AbC10", link: "https://loja.example.invalid/item", foto_url: null,
  categoria: "games", canal_origem: "canal_a", criado_em: "2026-10-01T00:00:00Z",
  data_oferta: "2026-11-05T10:00:00Z", preco_anterior_atualizacao: 300,
  preco_observado_em: "2026-11-05T10:00:00Z", expira_em: APOS };

function ambiente(registros = [], retencaoHoras = 48, instante = AGORA) {
  const consultas = [];
  let erro = null;
  const cliente = createClient("https://projeto.example.invalid", "chave-sintetica", {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: { fetch: async (input, opcoes) => {
      const url = new URL(input);
      const consulta = { url, metodo: opcoes.method, corpo: opcoes.body && JSON.parse(opcoes.body) };
      consultas.push(consulta);
      if (erro) return new Response(JSON.stringify(erro), { status: 500 });
      let dados = registros;
      if (url.pathname.endsWith("/oferta_remover")) {
        dados = [{ id: 1, status: consulta.corpo.p_id === 999 ? "ausente" : "removido", foto_url: null }];
      } else if (url.pathname.endsWith("/oferta_buscar")) {
        dados = consulta.corpo.p_id === 999 ? [] : registros;
      } else {
        const inicio = Number(url.searchParams.get("offset") || 0);
        const limite = Number(url.searchParams.get("limit") || 1000);
        dados = registros.slice(inicio, inicio + limite);
      }
      return new Response(JSON.stringify(dados), { status: 200, headers: { "Content-Type": "application/json" } });
    } },
  });
  const model = criarProdutoModel(async () => cliente, {
    obterRetencaoHoras: async () => retencaoHoras, agora: () => instante,
  });
  return { consultas, model, servico: criarProdutoService(model), falhar(e) { erro = e; } };
}

function conferirElegibilidade(url) {
  assert.equal(url.searchParams.get("estado_oferta"), "eq.ativa");
  assert.equal(url.searchParams.get("canonico_id"), "is.null");
  assert.ok(url.searchParams.getAll("or").includes(
    `(and(identidade_versao.is.null,criado_em.gt.${CORTE}),and(identidade_versao.not.is.null,expira_em.gt.2026-11-05T12:00:00.000Z))`));
}

test("lista/contagem/detalhe enviam elegibilidade canônica idêntica ao PostgREST real", async () => {
  const a = ambiente([publico]);
  await a.model.listar({ categoria: "games", q: "SSD", limite: 12, offset: 24 });
  await a.model.contarPorCategoria();
  await a.model.buscarPorId(2);
  assert.equal(a.consultas.length, 3);
  for (const { url } of a.consultas) conferirElegibilidade(url);
  const lista = a.consultas[0].url;
  assert.equal(lista.searchParams.get("categoria"), "eq.games");
  assert.equal(lista.searchParams.get("limit"), "12");
  assert.equal(lista.searchParams.get("offset"), "24");
  // A busca textual acrescenta outro OR sem substituir a condição temporal.
  assert.deepEqual(lista.searchParams.getAll("or").slice(1), ["(titulo.ilike.%SSD%,raw_text.ilike.%SSD%)"]);
  assert.match(lista.searchParams.get("order"), /data_oferta.desc.nullslast,criado_em.desc,id.desc/);
  for (const { url } of a.consultas) {
    const colunas = url.searchParams.get("select");
    assert.doesNotMatch(colunas, /\*|identidade|raw_text|dedup_hash|telegram_msg_id|diagnostico/);
    if (colunas !== "categoria") {
      assert.match(colunas, /produto_aparicoes\(canal_origem,visto_em\)/);
      assert.match(colunas, /preco_anterior_atualizacao/);
    }
  }
});

test("busca literal escapa wildcards e filtros omitidos mantêm comportamento", async () => {
  const a = ambiente();
  await a.model.listar({ categoria: "todos", q: "x%_,\\" });
  const { searchParams } = a.consultas[0].url;
  assert.equal(searchParams.has("categoria"), false);
  assert.equal(searchParams.getAll("or")[1], "(titulo.ilike.%x\\%\\_\\,\\\\%,raw_text.ilike.%x\\%\\_\\,\\\\%)");
  await a.model.listar({ q: "x" });
  assert.equal(a.consultas[1].url.searchParams.getAll("or").length, 1);
});

test("janela configurável só altera corte legado; instâncias novas usam expiração congelada", async () => {
  const a = ambiente([], 24);
  await a.model.listar();
  await a.model.contarPorCategoria();
  await a.model.buscarPorId(1);
  for (const { url } of a.consultas) {
    assert.equal(url.searchParams.get("or"), "(and(identidade_versao.is.null,criado_em.gt.2026-11-04T12:00:00.000Z),and(identidade_versao.not.is.null,expira_em.gt.2026-11-05T12:00:00.000Z))");
  }
});

test("contagem pagina além de 1000 linhas com corte temporal fixo", async () => {
  const a = ambiente(Array.from({ length: 1001 }, (_, id) => ({ ...publico, id })));
  assert.deepEqual(await a.servico.estatisticas(), { total: 1001, porCategoria: { games: 1001 } });
  assert.equal(a.consultas.length, 2);
  assert.equal(a.consultas[1].url.searchParams.get("offset"), "1000");
  a.consultas.forEach(({ url }) => conferirElegibilidade(url));
});

test("GET alias usa canônico/aparições e whitelist mesmo com payload privado inesperado", async () => {
  const a = ambiente([{ ...publico, canal_id: -100123, identidade: { segredo: true }, raw_text: "texto privado",
    dedup_hash: "hash", produto_aparicoes: [
      { canal_origem: "canal_b", visto_em: "2026-11-05T11:00:00Z", segredo: true },
      { canal_origem: "canal_a", visto_em: "2026-11-05T09:00:00Z" },
      { canal_origem: "canal_b", visto_em: "2026-11-05T12:00:00Z" },
    ] }]);
  assert.deepEqual(await a.servico.detalhar("2"), { ...publico, canais: ["canal_a", "canal_b"] });
  assert.deepEqual(a.consultas[0].corpo, { p_id: 2 });
  assert.match(a.consultas[0].url.pathname, /rpc\/oferta_buscar$/);
  const lista = await a.servico.listar();
  assert.deepEqual(lista[0], { ...publico, canais: ["canal_a", "canal_b"] });
});

test("legado e preço zero/nulo preservam campos sem inventar atualização/canais", async () => {
  for (const preco of [0, null]) {
    const produto = { ...publico, preco, preco_anterior_atualizacao: null, preco_observado_em: null };
    const a = ambiente([produto]);
    assert.deepEqual(await a.servico.detalhar(1), { ...produto, canais: ["canal_a"] });
  }
});

test("ausência é 404, schema/RPC/banco falho propaga erro técnico sem fallback", async () => {
  const a = ambiente();
  await assert.rejects(a.servico.detalhar(999), { status: 404 });
  for (const code of ["42703", "PGRST202", "08006"]) {
    a.falhar({ code, message: "Falha técnica sintética" });
    for (const op of [() => a.servico.detalhar(1), () => a.servico.listar(),
      () => a.servico.estatisticas(), () => a.servico.remover(1)]) {
      await assert.rejects(op(), (e) => e.code === code && e.status !== 404);
    }
  }
});

test("DELETE alias envia só RPC transacional, ausência 404 e repetição é idempotente", async () => {
  const a = ambiente([publico]);
  await a.servico.remover("2");
  await a.servico.remover("2");
  assert.equal(a.consultas.length, 2);
  for (const c of a.consultas) {
    assert.match(c.url.pathname, /rpc\/oferta_remover$/);
    assert.deepEqual(c.corpo, { p_id: 2 });
    assert.equal(c.metodo, "POST");
  }
  await assert.rejects(a.servico.remover(999), { status: 404 });
});

test("validação de paginação/IDs ocorre antes de tocar banco", async () => {
  const a = ambiente();
  for (const filtros of [{ limite: 0 }, { limite: 101 }, { offset: -1 }, { q: "x".repeat(201) }]) {
    await assert.rejects(a.servico.listar(filtros), { status: 400 });
  }
  for (const id of [0, -1, "abc", 1.5, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    await assert.rejects(a.servico.detalhar(id), { status: 400 });
    await assert.rejects(a.servico.remover(id), { status: 400 });
  }
  assert.equal(a.consultas.length, 0);
});

function requisitar(method, url, query = {}) {
  return new Promise((resolve, reject) => {
    const req = { method, url, query, headers: {} };
    const res = { statusCode: 200,
      status(status) { this.statusCode = status; return this; },
      json(corpo) { resolve({ status: this.statusCode, corpo }); },
      end() { resolve({ status: this.statusCode }); },
    };
    router.handle(req, res, (e) => e ? errorHandler(e, req, res, reject) : reject(new Error("Rota não atendida")));
  });
}

test("rotas reais preservam métodos/status e erro técnico não vaza detalhes privados", async (t) => {
  const a = ambiente([publico]);
  for (const nome of ["listar", "detalhar", "remover", "estatisticas"]) {
    t.mock.method(ProdutoService, nome, (...args) => a.servico[nome](...args));
  }
  t.mock.method(console, "error", () => {});
  assert.equal((await requisitar("GET", "/")).corpo[0].id, 1);
  assert.equal((await requisitar("GET", "/2")).corpo.id, 1);
  assert.equal((await requisitar("GET", "/estatisticas")).corpo.total, 1);
  assert.equal((await requisitar("DELETE", "/2")).status, 204);
  assert.equal((await requisitar("GET", "/999")).status, 404);
  a.falhar({ code: "42703", message: "Segredo do banco" });
  assert.deepEqual(await requisitar("GET", "/2"), {
    status: 500, corpo: { erro: "Erro interno do servidor" },
  });
});
