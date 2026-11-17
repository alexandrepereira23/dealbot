import assert from "node:assert/strict";
import { test } from "node:test";
import { agendarLimpeza } from "../src/services/agendamento-limpeza.service.js";

const log = { log() {}, error() {} };
test("limpeza suspensa não dispara nem no boot nem após intervalo", async t => {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  let chamadas = 0;
  const agenda = agendarLimpeza({ ativa: false, intervaloMin: 1 }, () => chamadas++, log);
  t.mock.timers.tick(180_000);
  await agenda.encerrar();
  assert.equal(chamadas, 0);
});
test("encerramento drena ciclo em andamento, sem sobrepor ou reagendar", async t => {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  let liberar;
  let chamadas = 0;
  const pendente = new Promise(resolve => { liberar = resolve; });
  const agenda = agendarLimpeza({ ativa: true, intervaloMin: 1 }, () => { chamadas++; return pendente; }, log);
  t.mock.timers.tick(10_000);
  await Promise.resolve();
  assert.equal(chamadas, 1);
  t.mock.timers.tick(180_000);
  assert.equal(chamadas, 1);
  let encerrou = false;
  const fim = agenda.encerrar().then(() => { encerrou = true; });
  await Promise.resolve();
  assert.equal(encerrou, false);
  liberar();
  await fim;
  t.mock.timers.tick(180_000);
  assert.equal(chamadas, 1);
});
