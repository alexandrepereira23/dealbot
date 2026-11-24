// Fronteira HTTP SINTÉTICA. Não valida SQL/RLS, assinatura JWT ou Telegram reais.
// Não é copiada para imagens de produção. Sem env de credenciais e sem rede externa.
import http from "node:http";
import { readFileSync, renameSync, writeFileSync } from "node:fs";
const porta = Number(process.env.LAB_SUPABASE_PORT || 54329);
const origem = process.env.LAB_ORIGIN || "https://localhost:18443";
const usuario = { id: "00000000-0000-0000-0000-000000000905", email: "lab@example.invalid", aud: "authenticated", role: "authenticated" };
const enc = v => Buffer.from(JSON.stringify(v)).toString("base64url");
const token = `${enc({ alg: "HS256", typ: "JWT" })}.${enc({ sub: usuario.id, exp: 2100000000, role: "authenticated" })}.sintetico`;
const sessao = { access_token: token, refresh_token: "refresh-sintetico", expires_at: 2100000000, expires_in: 3600, token_type: "bearer", user: usuario };
const arquivo = process.env.LAB_DADOS;
let salvo;
if (arquivo) {
  try { salvo = JSON.parse(readFileSync(arquivo, "utf8")); }
  catch (erro) { if (erro.code !== "ENOENT") throw erro; }
}
const cards = salvo?.cards ?? [];
const eventos = salvo?.eventos ?? [];
const registrados = new Map(cards.map(p => [p.chave_lab, p]));
const reservas = new Set(salvo?.reservas);
let fotoAte = salvo?.fotoAte ?? 0;
let authFalhando = false;
const webp = Buffer.from("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAUAmJaQAA3AA/v02aAA=", "base64");

function persistir() {
  if (!arquivo) return;
  const temporario = `${arquivo}.tmp`;
  writeFileSync(temporario, JSON.stringify({ cards, eventos, reservas: [...reservas], fotoAte }), { mode: 0o600, flush: true });
  renameSync(temporario, arquivo);
}

const server = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", origem);
  res.setHeader("Access-Control-Allow-Headers", "authorization,apikey,content-type,x-client-info,x-supabase-api-version");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }
  const url = new URL(req.url, "http://laboratorio.invalid");
  const json = (status, dados) => { res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); res.end(JSON.stringify(dados)); };
  let dados = {};
  if (req.method === "POST") {
    let corpo = "";
    for await (const trecho of req) { corpo += trecho; if (corpo.length > 100_000) return json(413, {}); }
    try { dados = JSON.parse(corpo || "{}"); } catch { return json(400, {}); }
  }
  if (url.pathname === "/__lab/health") return json(200, { sintetico: true });
  if (url.pathname === "/__lab/controle" && req.method === "POST") {
    if (req.headers["x-lab-controle"] !== "sintetico") return json(403, {});
    if (dados.acao === "oferta") eventos.push({ msg: eventos.length + 1, foto: true });
    else if (dados.acao === "foto") fotoAte = eventos.length;
    else if (dados.acao === "auth") {
      authFalhando = Boolean(dados.falhar);
      return json(200, {});
    }
    else return json(400, {});
    persistir();
    return json(200, {});
  }
  if (url.pathname === "/__lab/eventos") return json(200, eventos);
  if (url.pathname === "/__lab/foto") {
    const msg = Number(url.searchParams.get("msg"));
    return json(200, { liberada: msg > 0 && msg <= fotoAte });
  }
  if (url.pathname === "/storage/v1/object/public/produtos/legada.webp") {
    res.writeHead(200, { "Content-Type": "image/webp" }); return res.end(webp);
  }
  if (url.pathname === "/auth/v1/token" && req.method === "POST") {
    if (dados.email !== usuario.email || dados.password !== "laboratorio123") return json(400, { code: "invalid_credentials", message: "Credencial sintética inválida" });
    return json(200, sessao);
  }
  if (url.pathname === "/auth/v1/user") {
    if (authFalhando) return json(503, { code: "unexpected_failure", message: "Indisponibilidade sintética" });
    return req.headers.authorization === `Bearer ${token}` ? json(200, usuario) : json(401, { code: "bad_jwt", message: "Token sintético rejeitado" });
  }
  if (url.pathname.startsWith("/rest/v1/rpc/")) {
    const nome = url.pathname.split("/").at(-1);
    if (nome === "oferta_legado_pronto" || nome === "oferta_confirmar" || nome === "midia_confirmar_remocao") return json(200, [{ status: "confirmado" }]);
    if (nome === "oferta_registrar") {
      const e = dados.p_evento;
      const chave = `${e.canal_id}:${e.msg_id}`;
      let p = registrados.get(chave);
      const repetido = Boolean(p);
      if (!p) {
        p = { ...dados.p_produto, chave_lab: chave, id: cards.length + 1, foto_url: null, estado_oferta: "ativa", canonico_id: null,
          identidade_versao: 2, criado_em: new Date().toISOString(), data_oferta: e.data_origem,
          expira_em: "2035-01-01T00:00:00Z", canal_origem: "sintetico", canais: ["sintetico"],
          produto_aparicoes: [{ canal_origem: "sintetico", visto_em: e.data_origem }] };
        registrados.set(chave, p); cards.unshift(p);
        persistir();
      }
      return json(200, [{ id: p.id, status: repetido ? "retomado" : "novo", foto_url: p.foto_url }]);
    }
    const p = cards.find(p => p.id === dados.p_id);
    if (nome === "oferta_buscar") return json(200, p ? [p] : []);
    if (nome === "oferta_foto") {
      if (reservas.has(dados.p_url)) return json(200, [{ status: "remocao_reservada" }]);
      if (!p) return json(200, [{ status: "removida" }]);
      const existente = Boolean(p.foto_url);
      if (!existente) { p.foto_url = dados.p_url; persistir(); }
      return json(200, [{ status: existente ? "existente" : "atualizada" }]);
    }
    if (nome === "midia_reservar_remocao") {
      const permitido = !cards.some(p => p.foto_url === dados.p_url);
      if (permitido && !reservas.has(dados.p_url)) { reservas.add(dados.p_url); persistir(); }
      return json(200, [{ permitido }]);
    }
    return json(500, { code: "LAB_RPC_DESCONHECIDA" });
  }
  if (url.pathname === "/rest/v1/produtos") {
    if (url.searchParams.get("limit") === "0") return json(200, []);
    const offset = Number(url.searchParams.get("offset") || 0);
    const limite = Number(url.searchParams.get("limit") || 1000);
    const resultado = cards.slice(offset, offset + limite);
    res.setHeader("Content-Range", `0-${Math.max(0, resultado.length - 1)}/${cards.length}`);
    return json(200, resultado);
  }
  if (url.pathname.startsWith("/rest/v1/")) return json(200, []);
  return json(404, { erro: "rota_sintetica_ausente" });
});
server.listen(porta, process.env.LAB_BIND || "127.0.0.1", () => console.log("laboratorio: fronteira Supabase sintética pronta"));
process.once("SIGTERM", () => server.close());
process.once("SIGINT", () => server.close());
