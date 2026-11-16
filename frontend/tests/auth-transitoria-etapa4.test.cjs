// Página, useAuth, cliente HTTP, polling e ProdutoCard reais. Relógio/rede e
// fronteira Supabase falsos; sem browser, .env ou serviços externos.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ambiente, sessao } = require("./helpers/lifecycle.cjs");

const AVISO = "Serviço de autenticação temporariamente indisponível";
const oferta = (preco = 10) => ({ id: 901, titulo: "Oferta sintética", preco,
  preco_original: null, foto_url: null, cupom: null, link: "https://loja.example.invalid/oferta" });
const lista = ui => ui.chamadas.filter(c => c.rota === "/produtos");
const stats = ui => ui.chamadas.filter(c => c.rota === "/produtos/estatisticas");
const json = (corpo, status = 200) => new Response(JSON.stringify(corpo), {
  status, headers: { "Content-Type": "application/json" },
});

async function liberarToken(ui) {
  // Cada lote de consultas usa a mesma sessão válida, nunca uma credencial real.
  for (const consulta of ui.consultasToken) consulta.resolver({ data: { session: sessao() } });
  await ui.estabilizar();
}
async function preparar(t) {
  const ui = ambiente({ apiReal: true, cardReal: true });
  t.after(() => ui.desmontar());
  await ui.estabilizar(); await liberarToken(ui);
  return ui;
}
function conferirSessao(ui) {
  assert.equal(ui.pendencias().saidas, 0, "503 não chama signOut");
  assert.deepEqual(ui.redirecionamentos, [], "503 não redireciona");
  assert.ok(ui.chamadas.every(c => c.headers.Authorization === "Bearer token-falso-a"));
}
function conferirCard(ui, preco) {
  assert.equal(ui.cards().length, 1);
  assert.equal(ui.cards()[0].key, "901");
  assert.equal(ui.cards()[0].props.produto.preco, preco);
  assert.match(ui.html(), /href="https:\/\/loja.example.invalid\/oferta"[^>]*class="produto__cta">Ver oferta<\/a>/);
}

test("HTTP 200 → 503 → 200 no polling preserva sessão/card/CTA e recupera sem F5", async t => {
  const ui = await preparar(t);
  lista(ui)[0].resolver(json([oferta()]));
  stats(ui)[0].resolver(json({ total: 37, porCategoria: { eletronicos: 9 } }));
  await ui.estabilizar(); conferirCard(ui, 10);
  await ui.avancar(5000); await liberarToken(ui);
  lista(ui)[1].resolver(json({ erro: AVISO }, 503)); await ui.estabilizar();
  conferirCard(ui, 10); conferirSessao(ui);
  assert.match(ui.html(), new RegExp(`Ofertas podem estar desatualizadas: ${AVISO}`));
  assert.match(ui.html(), />37<\/div>/);
  assert.doesNotMatch(ui.html(), /Carregando ofertas|Nenhuma oferta ainda/);
  await ui.avancar(9999); assert.equal(lista(ui).length, 2);
  await ui.avancar(1); await liberarToken(ui); assert.equal(lista(ui).length, 3);
  lista(ui)[2].resolver(json([oferta(25)])); await ui.estabilizar();
  conferirCard(ui, 25); conferirSessao(ui);
  assert.doesNotMatch(ui.html(), /desatualizadas|Não foi possível consultar/);
  assert.match(ui.html(), /Atualizado automaticamente/);
  // Após sucesso o intervalo volta aos 5 s normais, em vez do recuo de 10 s.
  await ui.avancar(4999); assert.equal(lista(ui).length, 3);
  await ui.avancar(1); await liberarToken(ui); assert.equal(lista(ui).length, 4);
});

test("503 na primeira carga indica falha de consulta, não lista vazia, e retry recupera", async t => {
  const ui = await preparar(t);
  lista(ui)[0].resolver(json({ erro: AVISO }, 503));
  stats(ui)[0].resolver(json({ total: 0, porCategoria: {} }));
  await ui.estabilizar(); conferirSessao(ui);
  assert.match(ui.html(), /Não foi possível consultar ofertas agora. A atualização será tentada novamente/);
  assert.match(ui.html(), new RegExp(AVISO));
  assert.doesNotMatch(ui.html(), /Carregando ofertas|Nenhuma oferta ainda/);
  assert.equal(ui.cards().length, 0);
  await ui.avancar(9999); assert.equal(lista(ui).length, 1);
  await ui.avancar(1); await liberarToken(ui);
  lista(ui)[1].resolver(json([oferta()])); await ui.estabilizar();
  conferirCard(ui, 10); conferirSessao(ui);
  assert.doesNotMatch(ui.html(), /desatualizadas|Não foi possível consultar/);
});

test("503 nas estatísticas mantém métricas anteriores e lista ativa até recuperação automática", async t => {
  const ui = await preparar(t);
  lista(ui)[0].resolver(json([oferta()]));
  stats(ui)[0].resolver(json({ total: 37, porCategoria: { eletronicos: 9 } }));
  await ui.estabilizar();
  async function avancarComLista(ms) {
    while (ms > 0) {
      const passo = Math.min(ms, 5000);
      await ui.avancar(passo); await liberarToken(ui);
      lista(ui).at(-1).resolver(json([oferta()])); await ui.estabilizar();
      ms -= passo;
    }
  }
  await avancarComLista(30000); assert.equal(stats(ui).length, 2);
  stats(ui)[1].resolver(json({ erro: AVISO }, 503)); await ui.estabilizar();
  conferirCard(ui, 10); conferirSessao(ui);
  assert.match(ui.html(), new RegExp(`Métricas globais podem estar desatualizadas: ${AVISO}`));
  assert.match(ui.html(), />37<\/div>/); assert.match(ui.html(), />9<\/div>/);
  assert.doesNotMatch(ui.html(), /Ofertas podem estar desatualizadas/);
  const listasAntes = lista(ui).length;
  await avancarComLista(59999); assert.equal(stats(ui).length, 2);
  assert.ok(lista(ui).length > listasAntes, "503 de stats não bloqueia endpoint de lista");
  await avancarComLista(1); assert.equal(stats(ui).length, 3);
  stats(ui)[2].resolver(json({ total: 42, porCategoria: { eletronicos: 12 } }));
  await ui.estabilizar(); conferirCard(ui, 10); conferirSessao(ui);
  assert.match(ui.html(), />42<\/div>/); assert.match(ui.html(), />12<\/div>/);
  assert.doesNotMatch(ui.html(), /desatualizadas/);
});

test("503 inicial de estatísticas não inventa métricas zero nem encerra sessão", async t => {
  const ui = await preparar(t);
  lista(ui)[0].resolver(json([oferta()]));
  stats(ui)[0].resolver(json({ erro: AVISO }, 503)); await ui.estabilizar();
  conferirCard(ui, 10); conferirSessao(ui);
  assert.match(ui.html(), /Total<\/div><div class="metric__value">—<\/div>/);
  assert.match(ui.html(), /Métricas globais podem estar desatualizadas/);
});

for (const endpoint of ["lista", "estatísticas"]) {
  test(`401 HTTP legítimo em ${endpoint} limpa cards e interrompe polling até login`, async t => {
    const ui = await preparar(t);
    lista(ui)[0].resolver(json([oferta()])); await ui.estabilizar();
    conferirCard(ui, 10);
    if (endpoint === "lista") {
      stats(ui)[0].resolver(json({ total: 1, porCategoria: {} })); await ui.estabilizar();
      await ui.avancar(5000); await liberarToken(ui);
    }
    const chamada = endpoint === "lista" ? lista(ui).at(-1) : stats(ui)[0];
    chamada.resolver(json({ erro: "Token inválido" }, 401)); await ui.estabilizar();
    assert.equal(ui.pendencias().saidas, 1);
    assert.equal(ui.cards().length, 0);
    assert.match(ui.html(), /Redirecionando para entrar/);
    const chamadasAntes = ui.chamadas.length;
    await ui.avancar(60000); assert.equal(ui.chamadas.length, chamadasAntes);
    ui.logout.resolver({ error: null }); await ui.estabilizar();
    assert.deepEqual(ui.redirecionamentos, ["/login"]);
    assert.equal(ui.pendencias().timers, 0);
  });
}
