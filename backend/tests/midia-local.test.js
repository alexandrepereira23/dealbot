// Arquivos e servidor Express locais, sem env/credencial/Auth/Supabase reais.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { constants } from "node:fs";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import express from "express";
import { criarMidiaLocalModel, chaveLocalDaUrl } from "../src/models/midia-local.model.js";
import { criarMidiaService } from "../src/services/midia.service.js";
import { criarMidiaController } from "../src/controllers/midia.controller.js";
import { criarMidiaRoutes } from "../src/routes/midia.routes.js";
import { criarLimpezaModel } from "../src/models/limpeza.model.js";

const CHAVE = "0123456789abcdef0123456789abcdef.webp";
const WEBP = Buffer.from("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAUAmJaQAA3AA/v02aAA=", "base64");

async function diretorioTemporario() {
  return fs.mkdtemp(path.join(os.tmpdir(), "dealbot-midia-"));
}

async function iniciar(app) {
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  return {
    base: `http://127.0.0.1:${port}`,
    async fechar() {
      server.closeAllConnections?.();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

test("model local lê somente final canônico e remoção não toca URL externa", async () => {
  const diretorio = await diretorioTemporario();
  try {
    await fs.writeFile(path.join(diretorio, CHAVE), WEBP);
    const model = criarMidiaLocalModel(async () => ({ diretorio, limiteBytes: 358400 }));
    assert.deepEqual(await model.ler(CHAVE), { dados: WEBP, tamanho: WEBP.length });
    assert.equal(chaveLocalDaUrl(`/media/${CHAVE}`), CHAVE);
    for (const url of ["media/" + CHAVE, `/media/${CHAVE}?x=1`, `/media/%2e%2e/${CHAVE}`, "/media/.tmp"]) {
      assert.equal(chaveLocalDaUrl(url), null);
    }
    await assert.rejects(model.ler("../segredo.webp"), /Chave/);
    await model.apagarChave(CHAVE);
    assert.equal(await model.ler(CHAVE), null);
  } finally {
    await fs.rm(diretorio, { recursive: true, force: true });
  }
});

test("GET/HEAD público só serve WebP final; método e chave inválidos não escrevem", async () => {
  const diretorio = await diretorioTemporario();
  const arquivo = path.join(diretorio, CHAVE);
  await fs.writeFile(arquivo, WEBP);
  const model = criarMidiaLocalModel(async () => ({ diretorio, limiteBytes: 358400 }));
  const app = express();
  app.use("/media", criarMidiaRoutes(criarMidiaController(criarMidiaService(model))));
  // Equivale ao notFound global da aplicação: URL percent-encoded com .. pode
  // ser normalizada pelo cliente antes de alcançar o subrouter /media.
  app.use((req, res) => res.set("Cache-Control", "no-store").status(404).end());
  const servidor = await iniciar(app);
  try {
    const get = await fetch(`${servidor.base}/media/${CHAVE}`);
    assert.equal(get.status, 200);
    assert.equal(get.headers.get("content-type"), "image/webp");
    assert.equal(get.headers.get("cache-control"), "public, max-age=3600");
    assert.equal(get.headers.get("x-content-type-options"), "nosniff");
    assert.deepEqual(Buffer.from(await get.arrayBuffer()), WEBP);
    const head = await fetch(`${servidor.base}/media/${CHAVE}`, { method: "HEAD" });
    assert.equal(head.status, 200);
    assert.equal(head.headers.get("content-length"), String(WEBP.length));
    assert.equal((await head.arrayBuffer()).byteLength, 0);
    const comQuery = await fetch(`${servidor.base}/media/${CHAVE}?nao=aceitar`);
    assert.equal(comQuery.status, 404);
    assert.equal(comQuery.headers.get("cache-control"), "no-store");
    for (const alvo of [`/media/%2e%2e/${CHAVE}`, `/media/${CHAVE}.jpg`, "/media/.dealbot-media-x.tmp"]) {
      const resposta = await fetch(servidor.base + alvo);
      assert.equal(resposta.status, 404);
      assert.equal(resposta.headers.get("cache-control"), "no-store");
    }
    assert.equal((await fetch(`${servidor.base}/media/${CHAVE}`, { method: "DELETE" })).status, 404);
    assert.deepEqual(await fs.readFile(arquivo), WEBP);
  } finally {
    await servidor.fechar();
    await fs.rm(diretorio, { recursive: true, force: true });
  }
});

test("diretório local ausente mantém rota compatível como 404 sem cache", async () => {
  const model = criarMidiaLocalModel(async () => ({ diretorio: null, limiteBytes: 358400 }));
  const app = express();
  app.use("/media", criarMidiaRoutes(criarMidiaController(criarMidiaService(model))));
  const servidor = await iniciar(app);
  try {
    const resposta = await fetch(`${servidor.base}/media/${CHAVE}`);
    assert.equal(resposta.status, 404);
    assert.equal(resposta.headers.get("cache-control"), "no-store");
  } finally {
    await servidor.fechar();
  }
});

test("WebP com magic header mas RIFF truncado não é servido", async () => {
  const diretorio = await diretorioTemporario();
  try {
    await fs.writeFile(path.join(diretorio, CHAVE), Buffer.from("RIFF\x04\x00\x00\x00WEBP", "binary"));
    const model = criarMidiaLocalModel(async () => ({ diretorio, limiteBytes: 358400 }));
    await assert.rejects(model.ler(CHAVE), /incompatível/);
  } finally {
    await fs.rm(diretorio, { recursive: true, force: true });
  }
});

test("limpeza local usa só URL relativa canônica; legado continua no Storage", async () => {
  const chamadas = [];
  const local = { apagadas: [], async apagarChave(chave) { this.apagadas.push(chave); } };
  const cliente = {
    storage: { from() { return { async remove(chaves) { chamadas.push(chaves); return { error: null }; } }; } },
  };
  const model = criarLimpezaModel(async () => cliente, async () => "https://projeto.invalid", local);
  await model.apagarFoto(`/media/${CHAVE}`);
  assert.deepEqual(local.apagadas, [CHAVE]);
  assert.deepEqual(chamadas, []);
  await assert.rejects(model.apagarFoto(`/media/${CHAVE}?forjada=1`));
  await model.apagarFoto("https://projeto.invalid/storage/v1/object/public/produtos/legada.jpg");
  assert.deepEqual(chamadas, [["legada.jpg"]]);
});

test("troca da raiz durante remoção fica presa ao handle Linux", { skip: process.platform !== "linux" }, async () => {
  const base = await diretorioTemporario();
  const diretorio = path.join(base, "midia");
  const fora = path.join(base, "fora");
  await fs.mkdir(diretorio);
  await fs.mkdir(fora);
  await fs.writeFile(path.join(diretorio, CHAVE), WEBP);
  await fs.writeFile(path.join(fora, CHAVE), WEBP);
  const original = fs.lstat;
  let trocou = false;
  try {
    fs.lstat = async (alvo, ...opcoes) => {
      const info = await original(alvo, ...opcoes);
      if (String(alvo).endsWith(`/${CHAVE}`) && !trocou) {
        await fs.rename(diretorio, path.join(base, "midia-antiga"));
        await fs.symlink(fora, diretorio, "dir");
        trocou = true;
      }
      return info;
    };
    const model = criarMidiaLocalModel(async () => ({ diretorio }));
    await model.apagarChave(CHAVE);
    assert.equal(trocou, true);
    assert.deepEqual(await fs.readFile(path.join(fora, CHAVE)), WEBP);
  } finally {
    fs.lstat = original;
    await fs.rm(base, { recursive: true, force: true });
  }
});

test("ancestral trocado antes de abrir a raiz não redireciona a API Linux", { skip: process.platform !== "linux" }, async () => {
  const base = await diretorioTemporario();
  const pai = path.join(base, "pai");
  const diretorio = path.join(pai, "midia");
  const fora = path.join(base, "fora");
  await fs.mkdir(diretorio, { recursive: true });
  await fs.mkdir(path.join(fora, "midia"), { recursive: true });
  await fs.writeFile(path.join(diretorio, CHAVE), WEBP);
  await fs.writeFile(path.join(fora, "midia", CHAVE), WEBP);
  const original = fs.open;
  let trocou = false;
  try {
    fs.open = async (alvo, ...opcoes) => {
      if (String(alvo).startsWith("/proc/self/fd/") && String(alvo).endsWith("/midia") && !trocou) {
        await fs.rename(pai, path.join(base, "pai-antigo"));
        await fs.symlink(fora, pai, "dir");
        trocou = true;
      }
      return original(alvo, ...opcoes);
    };
    const model = criarMidiaLocalModel(async () => ({ diretorio }));
    await model.apagarChave(CHAVE);
    assert.equal(trocou, true);
    assert.deepEqual(await fs.readFile(path.join(fora, "midia", CHAVE)), WEBP);
  } finally {
    fs.open = original;
    await fs.rm(base, { recursive: true, force: true });
  }
});

test("FIFO com chave canônica é recusado sem bloquear open Linux", { skip: process.platform !== "linux" }, async () => {
  const diretorio = await diretorioTemporario();
  const caminho = path.join(diretorio, CHAVE);
  execFileSync("mkfifo", [caminho]);
  let timer;
  try {
    const model = criarMidiaLocalModel(async () => ({ diretorio }));
    await assert.rejects(Promise.race([
      model.ler(CHAVE),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("FIFO bloqueou open")), 2000); }),
    ]), /Arquivo local de mídia inseguro/);
  } finally {
    clearTimeout(timer);
    // Se houver regressão, destravar o leitor antes de remover o FIFO evita
    // deixar um worker de open pendente mantendo o processo de teste vivo.
    const liberar = await fs.open(caminho, constants.O_RDWR | constants.O_NONBLOCK);
    await liberar.close();
    await fs.rm(diretorio, { recursive: true, force: true });
  }
});
