// Aplicação Express real, sem ler .env nem chamar Auth/DB/Storage externos.
import assert from "node:assert/strict";
import { test } from "node:test";
import http from "node:http";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import dotenv from "dotenv";

test("app real isola mídia/dados, aplica no-store e expõe Retry-After por CORS", async () => {
  const diretorio = await fs.mkdtemp(path.join(os.tmpdir(), "dealbot-app-etapa4-"));
  const chave = "a".repeat(32) + ".webp";
  const webp = Buffer.from("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAUAmJaQAA3AA/v02aAA=", "base64");
  await fs.writeFile(path.join(diretorio, chave), webp);
  Object.assign(process.env, { NODE_ENV: "test", CORS_ORIGIN: "http://127.0.0.1:54327",
    SUPABASE_URL: "http://127.0.0.1:54329", SUPABASE_SERVICE_KEY: "service-ficticia", SUPABASE_ANON_KEY: "anon-ficticia",
    MIDIA_LOCAL_DIR: diretorio, MIDIA_SAIDA_MAX_BYTES: "358400", RETENCAO_HORAS: "48", RETENCAO_DIAS: "7",
    LIMPEZA_INTERVALO_MIN: "60", LIMPEZA_LOTE: "100", LIMPEZA_MAX_LOTES: "10" });
  const configurar = dotenv.config;
  dotenv.config = () => ({ parsed: {} }); // Não abrir .env implícito, mesmo que exista no host.
  let criarApp;
  try { ({ criarApp } = await import("../src/app.js")); } finally { dotenv.config = configurar; }
  const servidor = http.createServer(criarApp());
  await new Promise(resolve => servidor.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${servidor.address().port}`;
  const origem = { Origin: "http://127.0.0.1:54327" };
  try {
    const foto = await fetch(`${base}/media/${chave}`, { headers: origem });
    assert.equal(foto.status, 200);
    assert.equal(foto.headers.get("cross-origin-resource-policy"), "cross-origin");
    assert.equal(foto.headers.get("x-content-type-options"), "nosniff");
    assert.equal(foto.headers.get("cache-control"), "public, max-age=3600");
    assert.deepEqual(Buffer.from(await foto.arrayBuffer()), webp);
    for (const metodo of ["POST", "PUT", "PATCH", "DELETE"]) {
      const negada = await fetch(`${base}/media/${chave}`, { method: metodo, headers: origem });
      assert.equal(negada.status, 404);
      assert.equal(negada.headers.get("cache-control"), "no-store");
    }
    const dados = await fetch(base + "/api/produtos", { headers: origem });
    assert.equal(dados.status, 401);
    assert.equal(dados.headers.get("cache-control"), "no-store");
    let limitada;
    for (let i = 0; i < 121; i += 1) {
      limitada = await fetch(base + "/api/health", { headers: origem });
      await limitada.text();
      if (limitada.status === 429) break;
    }
    assert.equal(limitada.status, 429);
    assert.equal(limitada.headers.get("cache-control"), "no-store");
    assert.ok(Number(limitada.headers.get("retry-after")) > 0);
    assert.equal(limitada.headers.get("access-control-allow-origin"), origem.Origin);
    assert.ok(limitada.headers.get("access-control-expose-headers").toLowerCase().includes("retry-after"));
  } finally {
    servidor.closeAllConnections();
    await new Promise(resolve => servidor.close(resolve));
    await fs.rm(diretorio, { recursive: true, force: true });
  }
});
