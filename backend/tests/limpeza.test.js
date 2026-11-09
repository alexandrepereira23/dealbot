// Protocolo remoto/Storage falsos e duráveis entre ciclos; nenhuma configuração real.
import assert from "node:assert/strict";
import { test } from "node:test";
import { criarLimpezaModel } from "../src/models/limpeza.model.js";
import { criarExecutarLimpeza } from "../src/services/limpeza.service.js";

const BASE = "https://projeto.example.invalid";
const FOTO = `${BASE}/storage/v1/object/public/produtos/pasta/123.jpg`;
const CONFIG = { retencaoHoras: 48, retencaoDias: 7, limpezaLote: 100, limpezaMaxLotes: 3 };

function ambiente(urls = [FOTO]) {
  const chamadas = [];
  const pendentes = new Set(urls);
  const referencias = new Set();
  const reservadas = new Set();
  const logs = [];
  const cliente = {
    erroStorage: null, erroConfirmacao: null, erroRpc: null, antesStorage: null,
    async rpc(nome, args) {
      chamadas.push({ nome, args });
      if (cliente.erroRpc) return { error: cliente.erroRpc, data: null };
      if (nome === "oferta_limpar") {
        return { data: [...pendentes].slice(0, args.p_lote).map((url) => ({ id: null, status: "midia_pendente", url })) };
      }
      if (nome === "midia_reservar_remocao") {
        if (referencias.has(args.p_url)) return { data: [{ permitido: false }] };
        reservadas.add(args.p_url);
        return { data: [{ permitido: true }] };
      }
      assert.equal(nome, "midia_confirmar_remocao");
      if (cliente.erroConfirmacao) return { error: cliente.erroConfirmacao };
      pendentes.delete(args.p_url);
      return { data: [{ status: "confirmado" }] };
    },
    storage: { from(bucket) {
      assert.equal(bucket, "produtos");
      return { async remove(chaves) {
        chamadas.push({ nome: "storage.remove", chaves });
        if (cliente.antesStorage) await cliente.antesStorage();
        return { error: cliente.erroStorage };
      } };
    } },
  };
  const model = criarLimpezaModel(async () => cliente, async () => BASE);
  const log = Object.fromEntries(["log", "warn", "error"].map((nome) => [nome, (...args) => logs.push(args.join(" "))]));
  const executar = criarExecutarLimpeza(model, async () => CONFIG, log);
  return { cliente, chamadas, pendentes, referencias, reservadas, logs, model, executar, log };
}

test("limpeza reserva atomicamente antes do Storage e só confirma após sucesso", async () => {
  const a = ambiente();
  assert.deepEqual(await a.executar(), { lotes: 1, fotos: 1, falhas: 0 });
  assert.deepEqual(a.chamadas.map((c) => c.nome), ["oferta_limpar", "midia_reservar_remocao", "storage.remove", "midia_confirmar_remocao"]);
  assert.deepEqual(a.chamadas[0].args, { p_retencao_horas: 48, p_retencao_dias: 7, p_lote: 100 });
  assert.deepEqual(a.chamadas[2].chaves, ["pasta/123.jpg"]);
  assert.equal(a.pendentes.size, 0);
});

test("foto compartilhada/adotada referenciada não recebe DELETE nem ack", async () => {
  const a = ambiente();
  a.referencias.add(FOTO);
  assert.equal((await a.executar()).fotos, 0);
  assert.deepEqual(a.chamadas.map((c) => c.nome), ["oferta_limpar", "midia_reservar_remocao"]);
  assert.equal(a.pendentes.size, 1);
});

test("reserva no fake impede referência tardia durante remoção (não substitui prova SQL)", async () => {
  const a = ambiente();
  a.cliente.antesStorage = async () => {
    assert.equal(a.reservadas.has(FOTO), true);
    // O contrato remoto rejeita anexação depois desta fronteira durável.
    const anexar = () => {
      if (a.reservadas.has(FOTO)) throw new Error("remocao_reservada");
      a.referencias.add(FOTO);
    };
    assert.throws(anexar, /remocao_reservada/);
  };
  assert.equal((await a.executar()).fotos, 1);
});

test("falha Storage mantém tarefa remota e próximo ciclo retoma sem URL em log", async () => {
  const a = ambiente();
  a.cliente.erroStorage = new Error(`segredo ${FOTO}?token=privado`);
  assert.equal((await a.executar()).falhas, 1);
  assert.equal(a.pendentes.has(FOTO), true);
  assert.equal(a.chamadas.some((c) => c.nome === "midia_confirmar_remocao"), false);
  assert.doesNotMatch(a.logs.join("\n"), /segredo|token|https:\/\//);
  a.cliente.erroStorage = null;
  const aposReinicio = criarExecutarLimpeza(a.model, async () => CONFIG, a.log);
  assert.equal((await aposReinicio()).fotos, 1);
  assert.equal(a.pendentes.size, 0);
});

test("resposta de ack perdida repete DELETE idempotente e conserva pendência", async () => {
  const a = ambiente();
  a.cliente.erroConfirmacao = new Error("resposta perdida");
  assert.equal((await a.executar()).falhas, 1);
  assert.equal(a.pendentes.has(FOTO), true);
  a.cliente.erroConfirmacao = null;
  assert.equal((await a.executar()).fotos, 1);
  assert.equal(a.chamadas.filter((c) => c.nome === "storage.remove").length, 2);
});

test("boot/intervalos compartilham um ciclo sem overlap nem fila adicional", async () => {
  const a = ambiente();
  let liberar;
  const barreira = new Promise((resolve) => { liberar = resolve; });
  let entrou;
  const iniciou = new Promise((resolve) => { entrou = resolve; });
  a.cliente.antesStorage = async () => { entrou(); await barreira; };
  const primeiro = a.executar();
  await iniciou;
  const segundo = a.executar();
  assert.equal(primeiro, segundo);
  assert.equal(a.chamadas.filter((c) => c.nome === "oferta_limpar").length, 1);
  liberar();
  await Promise.all([primeiro, segundo]);
  assert.equal(a.chamadas.filter((c) => c.nome === "storage.remove").length, 1);
  await a.executar();
  assert.equal(a.chamadas.filter((c) => c.nome === "oferta_limpar").length, 2);
});

test("orçamento de lotes é finito mesmo se todo lote vier cheio", async () => {
  const a = ambiente();
  let lotes = 0;
  const model = { async prepararLote() {
    lotes++;
    return { urls: [], processadas: 100, continuar: true };
  } };
  const executar = criarExecutarLimpeza(model, async () => CONFIG, a.log);
  assert.equal((await executar()).lotes, CONFIG.limpezaMaxLotes);
  assert.equal(lotes, CONFIG.limpezaMaxLotes);
});

test("mesma candidata falhando não é tentada sem limite num único ciclo", async () => {
  const a = ambiente();
  a.cliente.erroStorage = new Error("indisponível");
  const executar = criarExecutarLimpeza(a.model, async () => ({ ...CONFIG, limpezaLote: 1 }), a.log);
  assert.deepEqual(await executar(), { lotes: 2, fotos: 0, falhas: 1 });
  assert.equal(a.chamadas.filter((c) => c.nome === "storage.remove").length, 1);
});

test("schema/RPC ausente falha fechado sem consulta legada nem varredura Storage", async () => {
  const a = ambiente();
  a.cliente.erroRpc = { code: "PGRST202", message: "segredo" };
  assert.equal((await a.executar()).falhas, 1);
  assert.deepEqual(a.chamadas.map((c) => c.nome), ["oferta_limpar"]);
  assert.equal(a.pendentes.size, 1);
  assert.doesNotMatch(a.logs.join("\n"), /segredo/);
});

test("linhas de expiração/purga com URL nula são trabalho, não remoções Storage", async () => {
  const a = ambiente([]);
  a.cliente.rpc = async () => ({ data: [
    { id: 1, status: "expirado", url: null }, { id: 2, status: "purgado", url: null },
    { id: null, status: "midia_pendente", url: FOTO },
  ] });
  assert.deepEqual(await a.model.prepararLote({ retencaoHoras: 48, retencaoDias: 7, lote: 1 }),
    { urls: [FOTO], processadas: 2, continuar: true });
});

test("contratos RPC incompatíveis não simulam sucesso nem ack", async () => {
  const a = ambiente();
  for (const data of [null, {}, [{ status: "expirado", url: FOTO }], [{ status: "desconhecido", url: null }]]) {
    a.cliente.rpc = async () => ({ data });
    await assert.rejects(a.model.prepararLote({}), /Contrato/);
  }
  for (const data of [null, [], [{ permitido: "true" }], [{ permitido: true }, { permitido: true }]]) {
    a.cliente.rpc = async () => ({ data });
    await assert.rejects(a.model.reservarRemocao(FOTO), /Contrato/);
  }
  a.cliente.rpc = async () => ({ data: [{ status: "ausente" }] });
  await assert.rejects(a.model.confirmarRemocao(FOTO), /não persistida/);
});

test("Storage só recebe caminho conhecido do projeto/bucket, nunca basename de URL alheia", async () => {
  const a = ambiente();
  for (const url of ["inválida", "https://outro.example.invalid/123.jpg", `${BASE}/outro/123.jpg`,
    `${BASE}/storage/v1/object/public/outro/123.jpg`, `${FOTO}?token=privado`,
    `${BASE}/storage/v1/object/public/produtos/%2e%2e%2f123.jpg`,
    `${BASE}/storage/v1/object/public/produtos/pasta/../123.jpg`,
    `${BASE}/storage/v1/object/public/produtos/%31%32%33.jpg`]) {
    await assert.rejects(a.model.apagarFoto(url));
  }
  assert.equal(a.chamadas.length, 0);
  await a.model.apagarFoto(`${BASE}/storage/v1/object/public/produtos/pasta/minha%20foto.jpg`);
  assert.deepEqual(a.chamadas[0].chaves, ["pasta/minha foto.jpg"]);
});

test("limites inválidos são recusados antes de chamar RPC", async () => {
  const a = ambiente();
  for (const config of [{ ...CONFIG, retencaoHoras: NaN }, { ...CONFIG, retencaoDias: 6 },
    { ...CONFIG, limpezaLote: 0 }, { ...CONFIG, limpezaMaxLotes: Infinity },
    { ...CONFIG, limpezaMaxLotes: 1.5 }, { ...CONFIG, limpezaLote: 501 }]) {
    const executar = criarExecutarLimpeza(a.model, async () => config, a.log);
    assert.equal((await executar()).falhas, 1);
  }
  assert.equal(a.chamadas.length, 0);
});
