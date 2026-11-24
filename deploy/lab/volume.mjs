// Leitura e reserva com o model de produção no MESMO container/permissões da API.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { chaveLocalDaUrl, MidiaLocalModel } from "/app/src/models/midia-local.model.js";
import { LimpezaModel } from "/app/src/models/limpeza.model.js";

assert.deepEqual([process.geteuid(), process.getegid()], [10002, 10000]);
await assert.rejects(fs.open("/data/state/inbox.sqlite3", "r"), { code: "ENOENT" });

const raiz = "/data/media";
const dir = await fs.lstat(raiz);
assert.equal(dir.isDirectory(), true);
assert.deepEqual([dir.uid, dir.gid, dir.mode & 0o7777], [10001, 10000, 0o2770]);

async function lerComoApi(chave) {
  const info = await fs.lstat(`${raiz}/${chave}`);
  assert.equal(info.isFile(), true);
  assert.deepEqual([info.uid, info.gid, info.mode & 0o7777], [10001, 10000, 0o640]);
  const midia = await MidiaLocalModel.ler(chave);
  assert.ok(midia?.tamanho > 0);
  return midia.dados;
}

const [, , referenciada, modo] = process.argv;
const chaveReferenciada = chaveLocalDaUrl(referenciada);
const chaveOrfa = "f".repeat(32) + ".webp";
assert.ok(chaveReferenciada && chaveReferenciada !== chaveOrfa, "esperado WebP do card da fixture");
assert.ok(modo === undefined || modo === "--somente-referenciada");
const antes = await lerComoApi(chaveReferenciada);
assert.equal(await LimpezaModel.reservarRemocao(referenciada), false, "reserva de mídia referenciada deve ser recusada");
// Não se chama apagarFoto/confirmarRemocao se a reserva foi negada.
assert.deepEqual(await lerComoApi(chaveReferenciada), antes);

if (modo === undefined) {
  await lerComoApi(chaveOrfa);
  const orfa = "/media/" + chaveOrfa;
  assert.equal(await LimpezaModel.reservarRemocao(orfa), true);
  await LimpezaModel.apagarFoto(orfa);
  await LimpezaModel.confirmarRemocao(orfa);
  assert.equal(await MidiaLocalModel.ler(chaveOrfa), null);
}
console.log("volume: propriedade/modo exatos, leitura /proc/self/fd, estado não montado e proteção da mídia referenciada (RPC sintética)");
