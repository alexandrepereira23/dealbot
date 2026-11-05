// Fixtures sintéticas. Sem servidor HTTP, configuração Auth ou Supabase real.
import assert from "node:assert/strict";
import { test } from "node:test";
import { criarFiltroService } from "../src/services/filtro.service.js";
import { criarFiltroModel } from "../src/models/filtro.model.js";
import { criarFiltroController } from "../src/controllers/filtro.controller.js";
import { criarFiltroRouter } from "../src/routes/filtro.routes.js";
import { errorHandler } from "../src/middlewares/error.middleware.js";
import { readFileSync } from "node:fs";

function bancoFalso() {
  const registros = new Map();
  const consultas = [];
  let proximoId = 1;
  const banco = { registros, consultas, erro: null, gravacoes: [], from(tabela) {
    assert.equal(tabela, "filtros");
    const consulta = { operacao: "select" };
    consultas.push(consulta);
    function executar() {
      if (banco.erro) return { data: null, error: banco.erro };
      let data;
      const id = Number(consulta.id);
      if (consulta.operacao === "insert") {
        data = { id: proximoId++, criado_em: "2026-10-23T00:00:00Z", ...consulta.campos };
        registros.set(data.id, data);
        banco.gravacoes.push(structuredClone(consulta.campos));
      } else if (consulta.operacao === "update") {
        data = registros.get(id) ? { ...registros.get(id), ...consulta.campos } : null;
        if (data) registros.set(id, data);
        banco.gravacoes.push(structuredClone(consulta.campos));
      } else if (consulta.operacao === "delete") {
        registros.delete(id);
      } else {
        data = consulta.id === undefined ? [...registros.values()] : registros.get(id) ?? null;
      }
      return { data: structuredClone(data), error: null };
    }
    const query = {
      select(colunas) { consulta.colunas = colunas; return query; },
      insert(campos) { Object.assign(consulta, { operacao: "insert", campos }); return query; },
      update(campos) { Object.assign(consulta, { operacao: "update", campos }); return query; },
      delete() { consulta.operacao = "delete"; return query; },
      eq(campo, valor) { assert.equal(campo, "id"); consulta.id = valor; return query; },
      order(campo, opcoes) {
        assert.equal(campo, "criado_em"); assert.deepEqual(opcoes, { ascending: false });
        return query;
      },
      single() { consulta.single = true; return query; },
      maybeSingle() { consulta.maybeSingle = true; return query; },
      then(resolve, reject) { return Promise.resolve(executar()).then(resolve, reject); },
    };
    return query;
  } };
  const model = criarFiltroModel(async () => banco);
  const servico = criarFiltroService(model);
  return { banco, model, servico };
}

async function invalido(servico, dados) {
  await assert.rejects(servico.criar(dados), (erro) => erro.status === 400);
}

test("CRUD preserva tipo/modo, defaults e termos sem quebrar frases", async () => {
  const { servico, banco } = bancoFalso();
  const interesse = await servico.criar({ nome: "  Memórias  ", palavras_chave: [" memória RAM ", "SSD"] });
  assert.equal(interesse.nome, "Memórias");
  assert.equal(interesse.tipo_regra, "interesse");
  assert.equal(interesse.modo_palavras, "qualquer");
  assert.equal(interesse.ativo, true);
  assert.equal(interesse.categoria, null);
  assert.deepEqual(interesse.palavras_chave, ["memória RAM", "SSD"]);
  const global = await servico.criar({ nome: "Veto", tipo_regra: "bloqueio_global",
    modo_palavras: "todas", palavras_bloqueio: ["usado", "recondicionado"] });
  assert.deepEqual(global.palavras_chave, []);
  assert.equal(global.preco_max, null);
  assert.equal((await servico.listar())[1].modo_palavras, "todas");
  await servico.remover(interesse.id);
  assert.equal(banco.registros.has(interesse.id), false);
});

const entradasInvalidas = [
  { nome: " " }, { nome: "x".repeat(101) }, { tipo_regra: "global" }, { modo_palavras: "algumas" },
  { categoria: "todos" }, { categoria: "inexistente" }, { palavras_chave: [""] },
  { palavras_chave: ["\u0301"] },
  { palavras_bloqueio: ["  "] }, { palavras_chave: ["x".repeat(101)] },
  { palavras_chave: Array.from({ length: 51 }, (_, i) => `termo ${i}`) },
  { palavras_bloqueio: Array.from({ length: 51 }, (_, i) => `termo ${i}`) },
  { palavras_chave: ["MEMÓRIA  RAM", "memoria\u00a0ram"] },
  { palavras_bloqueio: ["Usádo", " usado "] },
  { preco_max: -0.01 }, { preco_max: 100000000 }, { preco_max: 1.001 }, { preco_max: 1e-7 },
  { preco_max: 0.1 + 0.2 }, { preco_max: "299,90" }, { preco_max: NaN },
  { preco_max: Infinity }, { preco_max: -Infinity }, { ativo: "false" }, { surpresa: true },
  { tipo_regra: "bloqueio_global" },
  { tipo_regra: "bloqueio_global", palavras_bloqueio: ["usado"], palavras_chave: ["SSD"] },
  { tipo_regra: "bloqueio_global", palavras_bloqueio: ["usado"], categoria: "casa" },
  { tipo_regra: "bloqueio_global", palavras_bloqueio: ["usado"], preco_max: 0 },
];
for (const [indice, entrada] of entradasInvalidas.entries()) {
  test(`validação rejeita entrada inválida #${indice + 1} sem gravar`, async () => {
    const { servico, banco } = bancoFalso();
    await invalido(servico, { nome: "Regra", ...entrada });
    assert.equal(banco.gravacoes.length, 0);
  });
}

test("limites monetários via JSON não usam resto binário, aceitam zero e centavos", async () => {
  const { servico } = bancoFalso();
  for (const preco_max of [null, 0, 0.01, 0.29, 1.1, 299.9, 299.91, 99999999.99]) {
    const entrada = JSON.parse(JSON.stringify({ nome: "Preço", preco_max }));
    assert.equal((await servico.criar(entrada)).preco_max, preco_max);
  }
});

test("nomes/termos no limite e substring distinta não são duplicatas", async () => {
  const { servico } = bancoFalso();
  const filtro = await servico.criar({ nome: "x".repeat(100),
    palavras_chave: ["RAM", "memória RAM", "x".repeat(100),
      ...Array.from({ length: 47 }, (_, i) => `termo ${i}`)] });
  assert.equal(filtro.palavras_chave.length, 50);
});

test("PUT parcial preserva pausado e todos os campos omitidos; null/[] são explícitos", async () => {
  const { servico, banco } = bancoFalso();
  const anterior = await servico.criar({ nome: "Pausado", ativo: false, palavras_chave: ["SSD"],
    palavras_bloqueio: ["usado"], categoria: "eletronicos", preco_max: 0, modo_palavras: "todas" });
  const atualizado = await servico.atualizar(anterior.id, { nome: " Novo nome " });
  assert.deepEqual(atualizado, { ...anterior, nome: "Novo nome" });
  assert.deepEqual(banco.gravacoes.at(-1), { nome: "Novo nome" });
  const ativo = await servico.atualizar(anterior.id, { ativo: true });
  assert.deepEqual(ativo, { ...atualizado, ativo: true });
  assert.deepEqual(banco.gravacoes.at(-1), { ativo: true });
  const limpo = await servico.atualizar(anterior.id, { categoria: null, preco_max: null, palavras_chave: [] });
  assert.equal(limpo.preco_max, null);
  assert.deepEqual(limpo.palavras_chave, []);
  assert.deepEqual(limpo.palavras_bloqueio, ["usado"]);
});

test("PUT combina estado para invariantes de global, sem limpeza implícita", async () => {
  const { servico, banco } = bancoFalso();
  const filtro = await servico.criar({ nome: "Regra", palavras_chave: ["SSD"],
    palavras_bloqueio: ["usado"], categoria: "eletronicos", preco_max: 0 });
  await assert.rejects(servico.atualizar(filtro.id, { tipo_regra: "bloqueio_global" }), { status: 400 });
  assert.equal(banco.gravacoes.length, 1);
  const global = await servico.atualizar(filtro.id, { tipo_regra: "bloqueio_global",
    palavras_chave: [], categoria: null, preco_max: null });
  assert.equal(global.tipo_regra, "bloqueio_global");
  await assert.rejects(servico.atualizar(filtro.id, { palavras_bloqueio: [] }), { status: 400 });
  await assert.rejects(servico.atualizar(filtro.id, { preco_max: 0 }), { status: 400 });
  assert.equal((await servico.atualizar(filtro.id, { ativo: false })).ativo, false);
});

test("PUT parcial em arrays legados nulos não apaga nem regrava campos omitidos", async () => {
  const { servico, banco } = bancoFalso();
  const filtro = await servico.criar({ nome: "Legado" });
  banco.registros.get(filtro.id).palavras_chave = null;
  banco.registros.get(filtro.id).palavras_bloqueio = null;
  const atualizado = await servico.atualizar(filtro.id, { ativo: false });
  assert.equal(atualizado.ativo, false);
  assert.equal(atualizado.palavras_chave, null);
  assert.equal(atualizado.palavras_bloqueio, null);
  assert.deepEqual(banco.gravacoes.at(-1), { ativo: false });
});

test("PUT vazio/desconhecido é 400; ausência é 404; schema/banco não são mascarados", async () => {
  const { servico, banco } = bancoFalso();
  await assert.rejects(servico.atualizar(123, {}), { status: 400 });
  await assert.rejects(servico.atualizar(123, { id: 123 }), { status: 400 });
  await assert.rejects(servico.atualizar(123, { ativo: true }), { status: 404 });
  banco.erro = { code: "42703", message: "column tipo_regra does not exist" };
  await assert.rejects(servico.atualizar(123, { ativo: true }), (e) => e === banco.erro);
});

test("falha na gravação após leitura continua erro técnico, não 404", async () => {
  const erro = new Error("Falha de schema");
  const { servico } = bancoFalso();
  const filtro = await servico.criar({ nome: "Regra" });
  const servicoFalho = criarFiltroService({ buscarPorId: async () => filtro,
    atualizar: async () => { throw erro; } });
  await assert.rejects(servicoFalho.atualizar(filtro.id, { ativo: false }), (e) => e === erro);
});

test("model exige colunas novas explicitamente em leituras e retornos de gravação", async () => {
  const { model, banco } = bancoFalso();
  await model.listar(); await model.buscarPorId(1); await model.criar({ nome: "Regra" });
  await model.atualizar(1, { ativo: false });
  for (const consulta of banco.consultas) {
    assert.match(consulta.colunas, /tipo_regra/); assert.match(consulta.colunas, /modo_palavras/);
    assert.notEqual(consulta.colunas, "*");
  }
  banco.erro = { code: "42703", message: "schema indisponível" };
  for (const operacao of [() => model.listar(), () => model.buscarPorId(1),
    () => model.criar({ nome: "Regra" }), () => model.atualizar(1, { ativo: true })]) {
    await assert.rejects(operacao(), (e) => e === banco.erro);
  }
});

function requisitar(router, method, url, body) {
  return new Promise((resolve, reject) => {
    const req = { method, url, body, headers: {} };
    const res = { statusCode: 200,
      status(status) { this.statusCode = status; return this; },
      json(corpo) { resolve({ status: this.statusCode, corpo }); },
      end() { resolve({ status: this.statusCode }); },
    };
    router.handle(req, res, (erro) => {
      if (erro) errorHandler(erro, req, res, reject);
      else reject(new Error("Rota não atendida"));
    });
  });
}

test("rotas/controllers CRUD preservam métodos, sucesso e erro HTTP com fakes", async (t) => {
  const { servico, banco } = bancoFalso();
  const router = criarFiltroRouter(criarFiltroController(servico));
  const criado = await requisitar(router, "POST", "/", { nome: "Veto", tipo_regra: "bloqueio_global",
    palavras_bloqueio: ["usado"], modo_palavras: "todas" });
  assert.equal(criado.status, 201);
  assert.equal(criado.corpo.tipo_regra, "bloqueio_global");
  assert.equal((await requisitar(router, "GET", "/")).corpo[0].modo_palavras, "todas");
  assert.equal((await requisitar(router, "PUT", "/1", { ativo: false })).corpo.ativo, false);
  assert.equal((await requisitar(router, "PUT", "/1", { preco_max: 0 })).status, 400);
  assert.equal((await requisitar(router, "PUT", "/999", { ativo: true })).status, 404);
  banco.erro = { code: "42703", message: "detalhe privado da coluna" };
  t.mock.method(console, "error", () => {});
  const falha = await requisitar(router, "PUT", "/1", { ativo: true });
  assert.deepEqual(falha, { status: 500, corpo: { erro: "Erro interno do servidor" } });
  assert.equal((await requisitar(router, "GET", "/")).status, 500);
  banco.erro = null;
  assert.equal((await requisitar(router, "DELETE", "/1")).status, 204);
});

test("registro central continua protegendo filtros com autenticar (sem carregar Auth real)", () => {
  const fonte = readFileSync(new URL("../src/routes/index.js", import.meta.url), "utf8");
  assert.ok(fonte.indexOf("router.use(autenticar)") < fonte.indexOf('router.use("/filtros"'));
});
