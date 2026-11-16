// Express e SDK Auth instalados reais; só o transporte Auth e o serviço de
// ofertas são falsos. Nunca lê .env nem usa credenciais/serviços externos.
import assert from "node:assert/strict";
import { test } from "node:test";
import http from "node:http";
import dotenv from "dotenv";
import { AuthInvalidJwtError, AuthRetryableFetchError } from "@supabase/supabase-js";

const TOKEN = "token-sintetico-mantido-entre-tentativas";
const DETALHE = "detalhe-privado-do-provedor";
const INDISPONIVEL = "Serviço de autenticação temporariamente indisponível";
const oferta = { id: 901, titulo: "Oferta sintética", preco: 10 };
const usuario = { id: "usuario-sintetico", aud: "authenticated" };
const json = (corpo, status = 200) => new Response(JSON.stringify(corpo), {
  status, headers: { "Content-Type": "application/json", "X-Supabase-Api-Version": "2024-01-01" },
});

test("Auth da API distingue indisponibilidade, credencial rejeitada e falha desconhecida", async (t) => {
  Object.assign(process.env, { NODE_ENV: "test", CORS_ORIGIN: "http://127.0.0.1:54327",
    SUPABASE_URL: "http://127.0.0.1:54329", SUPABASE_SERVICE_KEY: "service-ficticia",
    SUPABASE_ANON_KEY: "anon-ficticia", MIDIA_LOCAL_DIR: "", RETENCAO_HORAS: "48",
    RETENCAO_DIAS: "7", LIMPEZA_INTERVALO_MIN: "60", LIMPEZA_LOTE: "100", LIMPEZA_MAX_LOTES: "10" });
  const configurar = dotenv.config;
  dotenv.config = () => ({ parsed: {} });
  let criarApp, supabaseAuth, supabaseAdmin, ProdutoService, autenticar;
  try {
    ({ criarApp } = await import("../src/app.js"));
    ({ supabaseAuth, supabaseAdmin } = await import("../src/config/supabase.js"));
    ({ ProdutoService } = await import("../src/services/produto.service.js"));
    ({ autenticar } = await import("../src/middlewares/auth.middleware.js"));
  } finally { dotenv.config = configurar; }

  let responderAuth;
  const chamadasAuth = [];
  // Ponto de transporte do auth-js 2.108.2: getUser, HTTP->classes/códigos e
  // serialização de erros continuam reais, sem substituir getUser pelo resultado.
  t.mock.method(supabaseAuth.auth, "fetch", async (input, opcoes) => {
    assert.equal(String(input), "http://127.0.0.1:54329/auth/v1/user");
    assert.equal(opcoes.method, "GET");
    chamadasAuth.push(new Headers(opcoes.headers).get("Authorization"));
    return responderAuth();
  });
  // Uma fuga acidental para o banco não pode acessar sequer um transporte real.
  t.mock.method(supabaseAdmin, "from", () => assert.fail("Banco não deve ser acessado"));
  t.mock.method(supabaseAdmin, "rpc", () => assert.fail("RPC não deve ser acessada"));
  const listas = t.mock.method(ProdutoService, "listar", async () => [oferta]);
  const metricas = t.mock.method(ProdutoService, "estatisticas", async () => ({ total: 1, porCategoria: {} }));
  const consultasProtegidas = () => listas.mock.callCount() + metricas.mock.callCount();
  const servidor = http.createServer(criarApp());
  await new Promise(resolve => servidor.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    servidor.closeAllConnections();
    await new Promise(resolve => servidor.close(resolve));
  });
  const base = `http://127.0.0.1:${servidor.address().port}/api`;

  async function consultar(rota = "/produtos", authorization = `Bearer ${TOKEN}`) {
    const res = await fetch(base + rota, { headers: authorization ? { Authorization: authorization } : {} });
    assert.equal(res.headers.get("Cache-Control"), "no-store");
    return { status: res.status, corpo: await res.json() };
  }
  async function conferirFalha(responder, status, mensagem, authorization = `Bearer ${TOKEN}`) {
    responderAuth = responder;
    const antes = consultasProtegidas();
    const resposta = await consultar("/produtos", authorization);
    assert.deepEqual(resposta, { status, corpo: { erro: mensagem } });
    assert.equal(consultasProtegidas(), antes, "falha não chama serviço protegido nem devolve ofertas");
    assert.doesNotMatch(JSON.stringify(resposta.corpo), new RegExp(`${TOKEN}|${DETALHE}|Oferta|AuthApiError`));
  }

  for (const rota of ["/produtos", "/produtos/estatisticas"]) {
    await t.test(`Auth 200 → 503 → 200 na rota ${rota}, com o mesmo token`, async () => {
      const status = [];
      const antes = consultasProtegidas();
      const authAntes = chamadasAuth.length;
      for (const codigo of [200, 503, 200]) {
        responderAuth = () => codigo === 200 ? json(usuario) : json({ message: DETALHE }, codigo);
        const resposta = await consultar(rota);
        status.push(resposta.status);
        if (codigo === 503) {
          assert.deepEqual(resposta.corpo, { erro: INDISPONIVEL });
          assert.equal(consultasProtegidas(), antes + 1);
        } else {
          assert.deepEqual(resposta.corpo, rota === "/produtos" ? [oferta] : { total: 1, porCategoria: {} });
        }
      }
      assert.deepEqual(status, [200, 503, 200]);
      assert.equal(consultasProtegidas(), antes + 2);
      assert.deepEqual(chamadasAuth.slice(authAntes), Array(3).fill(`Bearer ${TOKEN}`));
    });
  }

  for (const status of [500, 502, 504, 408, 429, 507]) {
    await t.test(`HTTP ${status} do Auth não invalida sessão`, async () => {
      await conferirFalha(() => json({ message: DETALHE }, status), 503, INDISPONIVEL);
    });
  }
  for (const status of [502, 503, 504]) {
    await t.test(`gateway ${status} sem JSON também é transitório`, async () => {
      await conferirFalha(() => new Response(`<html>${DETALHE}</html>`, { status }), 503, INDISPONIVEL);
    });
  }
  for (const code of ["request_timeout", "over_request_rate_limit"]) {
    await t.test(`código transitório ${code} não depende da mensagem`, async () => {
      await conferirFalha(() => json({ code, message: "Token inválido" }, 400), 503, INDISPONIVEL);
    });
  }
  for (const erro of [new TypeError("Transporte sintético indisponível"),
    new DOMException("Timeout sintético", "TimeoutError")]) {
    await t.test(`erro de transporte ${erro.name} permite recuperação`, async (st) => {
      // O SDK registra falhas de fetch; não publicar ruído de transporte no teste.
      st.mock.method(console, "error", () => {});
      await conferirFalha(() => { throw erro; }, 503, INDISPONIVEL);
      responderAuth = () => json(usuario);
      assert.equal((await consultar()).status, 200);
    });
  }

  for (const code of ["bad_jwt", "session_expired", "session_not_found", "user_not_found", "user_banned"]) {
    await t.test(`credencial rejeitada por ${code} continua 401`, async () => {
      await conferirFalha(() => json({ code, message: DETALHE }, 401), 401, "Token inválido");
    });
  }
  await t.test("código legado error_code também identifica JWT inválido", async () => {
    await conferirFalha(() => json({ error_code: "bad_jwt", msg: DETALHE }, 403), 401, "Token inválido");
  });
  await t.test("token ausente/esquema incorreto não consulta Auth nem serviço", async () => {
    for (const header of [null, "Basic nao-bearer", "Bearer "]) {
      const antes = chamadasAuth.length;
      await conferirFalha(() => assert.fail("Não deve consultar Auth"), 401, "Token ausente", header);
      assert.equal(chamadasAuth.length, antes);
    }
  });

  for (const [nome, responder] of [
    ["401 sem código não prova token inválido", () => json({ message: "Token inválido" }, 401)],
    ["403 técnico não prova token inválido", () => json({ code: "unexpected_failure", message: DETALHE }, 403)],
    ["código desconhecido", () => json({ code: "codigo_novo", message: DETALHE }, 400)],
    ["erro com JSON inválido", () => new Response(DETALHE, { status: 400 })],
    // Nesses status o SDK tenta ler JSON e perde o status ao lançar
    // AuthUnknownError. Sem sinal estruturado restante, negar com 500, não 401.
    ...[408, 429, 507].map(status => [`HTTP ${status} sem JSON/status preservado pelo SDK`,
      () => new Response(DETALHE, { status })]),
    ["200 sem usuário", () => json({})],
    ["200 com usuário nulo", () => json({ user: null })],
  ]) {
    await t.test(`falha técnica desconhecida: ${nome}`, async () => {
      await conferirFalha(responder, 500, "Erro interno do servidor");
    });
  }
  await t.test("exceção desconhecida lançada pelo SDK falha fechada e saneada", async (st) => {
    st.mock.method(supabaseAuth.auth, "getUser", async () => { throw new Error(`${DETALHE} ${TOKEN}`); });
    const log = st.mock.method(console, "error", () => {});
    await conferirFalha(() => assert.fail("Não deve consultar transporte"), 500, "Erro interno do servidor");
    assert.equal(log.mock.callCount(), 0, "middleware não repassa erro bruto para o logger central");
  });
  await t.test("middleware anexa somente usuário validado e chama next uma única vez", async () => {
    for (const [status, corpo] of [[200, usuario], [503, { message: DETALHE }],
      [401, { code: "bad_jwt", message: DETALHE }], [500, { message: DETALHE }]]) {
      responderAuth = () => json(corpo, status);
      const req = { headers: { authorization: `Bearer ${TOKEN}` } };
      const resultados = [];
      await autenticar(req, {}, erro => resultados.push(erro));
      assert.equal(resultados.length, 1);
      if (status === 200) {
        assert.deepEqual(req.user, usuario);
        assert.equal(resultados[0], undefined);
      } else {
        assert.equal(req.user, undefined);
        assert.equal(resultados[0].status, status === 401 ? 401 : 503);
      }
    }
  });
  for (const [erro, status, mensagem] of [
    [new AuthRetryableFetchError(DETALHE, 0), 503, INDISPONIVEL],
    [new AuthInvalidJwtError(DETALHE), 401, "Token inválido"],
  ]) {
    await t.test(`erro SDK lançado ${erro.name} mantém a classificação`, async (st) => {
      st.mock.method(supabaseAuth.auth, "getUser", async () => { throw erro; });
      await conferirFalha(() => assert.fail("Não deve consultar transporte"), status, mensagem);
    });
  }
});
