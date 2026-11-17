// Leitura e remoção com o model de produção no MESMO container/permissões da API.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { MidiaLocalModel } from "/app/src/models/midia-local.model.js";
import { LimpezaModel } from "/app/src/models/limpeza.model.js";
assert.equal(process.getuid(), 10002);
assert.equal(process.getgid(), 10000);
await assert.rejects(fs.access("/data/state/inbox.sqlite3"));
const chave = "f".repeat(32) + ".webp";
assert.ok((await MidiaLocalModel.ler(chave)).tamanho > 0);
const url = "/media/" + chave;
assert.equal(await LimpezaModel.reservarRemocao(url), true);
await LimpezaModel.apagarFoto(url);
await LimpezaModel.confirmarRemocao(url);
assert.equal(await MidiaLocalModel.ler(chave), null);
console.log("volume: /proc/self/fd, isolamento do estado e reserva→unlink→ack como API aprovados (RPC sintética)");
