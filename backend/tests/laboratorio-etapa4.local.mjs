// Laboratório de integração/QA. Nunca importa env nem compõe clientes reais.
// Exige DEALBOT_LAB_PYTHON absoluto e DEALBOT_LAB_BASE temporário exclusivo.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import readline from "node:readline";
import express from "express";
import cors from "cors";
import ws from "ws";
import { createClient } from "@supabase/supabase-js";
import { criarProdutoModel } from "../src/models/produto.model.js";
import { criarProdutoService } from "../src/services/produto.service.js";
import { criarMidiaLocalModel } from "../src/models/midia-local.model.js";
import { criarMidiaService } from "../src/services/midia.service.js";
import { criarMidiaController } from "../src/controllers/midia.controller.js";
import { criarMidiaRoutes } from "../src/routes/midia.routes.js";
import { errorHandler } from "../src/middlewares/error.middleware.js";

assert.ok(path.isAbsolute(process.env.DEALBOT_LAB_PYTHON || ""));
assert.ok(path.isAbsolute(process.env.DEALBOT_LAB_BASE || ""));
const raiz = await fs.mkdtemp(path.join(process.env.DEALBOT_LAB_BASE, "flow-"));
const bot = path.resolve(import.meta.dirname, "../../bot");
const python = spawn(process.env.DEALBOT_LAB_PYTHON, ["-B", "laboratorio_etapa4.py", raiz], { cwd: bot, stdio: ["pipe", "pipe", "inherit"] });
const respostas = [];
readline.createInterface({ input: python.stdout }).on("line", linha => {
  const espera = respostas.shift();
  if (espera) {
    try { const resultado = JSON.parse(linha); resultado.erro ? espera.reject(new Error(resultado.erro)) : espera.resolve(resultado); }
    catch (erro) { espera.reject(erro); }
  }
});
python.on("exit", () => { for (const r of respostas.splice(0)) r.reject(new Error("Ponte encerrada")); });
let fila = Promise.resolve();
function ponte(pedido) {
  const proximo = fila.then(() => new Promise((resolve, reject) => {
    respostas.push({ resolve, reject }); python.stdin.write(JSON.stringify(pedido) + "\n");
  }));
  fila = proximo.catch(() => {});
  return proximo;
}
const uid = "00000000-0000-0000-0000-000000000901";
const enc = v => Buffer.from(JSON.stringify(v)).toString("base64url");
const token = `${enc({ alg: "HS256", typ: "JWT" })}.${enc({ sub: uid, exp: 2100000000, role: "authenticated" })}.assinatura-ficticia`;
const sessao = { access_token: token, refresh_token: "refresh-ficticio", expires_at: 2100000000,
  expires_in: 3600, token_type: "bearer", user: { id: uid, email: "lab@example.invalid", role: "authenticated", aud: "authenticated" } };
let registros = [];
let falha = null;
const historico = [];
const cliente = createClient("http://127.0.0.1:54329", "anon-ficticia", {
  auth: { persistSession: false, autoRefreshToken: false }, realtime: { transport: ws },
  global: { fetch: async (input) => {
    const url = new URL(input);
    let dados = registros.filter(p => !p.canonico_id && !p.removido && Date.parse(p.expira_em) > Date.now());
    const categoria = url.searchParams.get("categoria");
    if (categoria) dados = dados.filter(p => p.categoria === categoria.slice(3));
    const busca = url.searchParams.getAll("or").find(s => s.includes("titulo.ilike"));
    if (busca) { const termo = busca.match(/titulo\.ilike\.%(.*?)%/)?.[1] || ""; dados = dados.filter(p => p.titulo.toLowerCase().includes(termo.toLowerCase())); }
    dados = dados.sort((a, b) => b.id - a.id);
    const offset = Number(url.searchParams.get("offset") || 0);
    const limite = Number(url.searchParams.get("limit") || 1000);
    return new Response(JSON.stringify(dados.slice(offset, offset + limite)), { headers: { "content-type": "application/json" } });
  } },
});
const model = criarProdutoModel(async () => cliente, { obterRetencaoHoras: async () => 48 });
const produtos = criarProdutoService(model);
const midia = criarMidiaLocalModel(async () => ({ diretorio: path.join(raiz, "media"), limiteBytes: 358400 }));
const app = express();
app.use(cors({ origin: ["http://127.0.0.1:54327", "http://127.0.0.1:54326"], exposedHeaders: ["Retry-After"] }));
app.use(express.json());
app.get("/__lab/config", (req, res) => res.json({ sessao, raiz }));
app.get("/__lab/historico", (req, res) => res.json(historico));
app.post("/__lab/encerrar", (req, res) => {
  if (req.headers["x-lab-controle"] !== "sintetico") return res.sendStatus(403);
  res.json({ encerrando: true });
  void fechar();
});
app.post("/__lab/controle", async (req, res, next) => {
  if (req.headers["x-lab-controle"] !== "sintetico") return res.sendStatus(403);
  try {
    if (req.body.acao === "falha_api") { falha = req.body.status ? req.body : null; return res.json({}); }
    const resposta = await ponte(req.body);
    registros = resposta.produtos;
    res.json(resposta);
  } catch (erro) { next(erro); }
});
app.use("/media", criarMidiaRoutes(criarMidiaController(criarMidiaService(midia))));
app.use("/api", (req, res, next) => {
  res.set("Cache-Control", "no-store");
  if (req.headers.authorization !== `Bearer ${token}`) return res.sendStatus(401);
  if (falha) { if (falha.retry) res.set("Retry-After", falha.retry); return res.status(falha.status).json({ erro: "falha-sintetica" }); }
  next();
});
app.get("/api/produtos", async (req, res, next) => {
  try {
    registros = (await ponte({ acao: "snapshot" })).produtos;
    const dados = await produtos.listar(req.query);
    historico.push({ inicio: Date.now(), ids: dados.map(p => p.id), rota: req.originalUrl });
    res.json(dados);
  } catch (erro) { next(erro); }
});
app.get("/api/produtos/estatisticas", async (req, res, next) => {
  try { res.json(await produtos.estatisticas()); } catch (erro) { next(erro); }
});
app.use(errorHandler);
const server = app.listen(54328, "127.0.0.1", () => console.log(JSON.stringify({ laboratorio: raiz, porta: 54328 })));
async function fechar() {
  python.stdin.write(JSON.stringify({ acao: "encerrar" }) + "\n");
  python.stdin.end();
  await new Promise(resolve => python.once("exit", resolve));
  server.closeAllConnections();
  server.close();
}
process.once("SIGINT", fechar);
process.once("SIGTERM", fechar);
