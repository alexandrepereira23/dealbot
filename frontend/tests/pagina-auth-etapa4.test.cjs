const assert = require("node:assert/strict");
const { test } = require("node:test");
const { ambiente, sessao } = require("./helpers/lifecycle.cjs");

const oferta = (id = 901) => ({ id, titulo: `Oferta sintética ${id}`, preco: 0,
  foto_url: null, cupom: "CupomOffline", link: "https://loja.example.invalid/oferta" });
const lista = (ui) => ui.chamadas.filter((c) => c.rota !== "/produtos/estatisticas");
const stats = (ui) => ui.chamadas.filter((c) => c.rota === "/produtos/estatisticas");

test("página real encerra primeira carga com card/CTA sem esperar stats ou mídia", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar());
  await ui.estabilizar();
  assert.match(ui.html(), /Carregando ofertas/);
  assert.doesNotMatch(ui.html(), /Nenhuma oferta ainda/);
  assert.equal(lista(ui).length, 1); assert.equal(stats(ui).length, 1);
  lista(ui)[0].resolver([oferta()]); await ui.estabilizar();
  assert.doesNotMatch(ui.html(), /Carregando ofertas/);
  assert.equal(ui.cards().length, 1);
  assert.equal(ui.cards()[0].key, "901");
  assert.equal(ui.cards()[0].props.produto.foto_url, null);
  assert.match(ui.html(), /Ver oferta/);
  assert.match(ui.html(), /R\$ 0,00/);
  stats(ui)[0].rejeitar(new Error("Stats offline")); await ui.estabilizar();
  assert.match(ui.html(), /Métricas globais podem estar desatualizadas/);
  assert.equal(ui.cards().length, 1);
});

test("primeira resposta válida vazia encerra spinner e confirma vazio", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  lista(ui)[0].resolver([]); await ui.estabilizar();
  assert.match(ui.html(), /Nenhuma oferta ainda/);
  assert.doesNotMatch(ui.html(), /Carregando ofertas|Não foi possível consultar/);
});

test("categoria ausente em stats válidas é zero; stats ainda desconhecidas são indisponíveis", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  const metrica = () => ui.html().match(/Eletrônicos<\/div><div class="metric__value">([^<]+)</)?.[1];
  assert.equal(metrica(), "—");
  stats(ui)[0].resolver({ total: 3, porCategoria: { outros: 3 } });
  await ui.estabilizar();
  assert.equal(metrica(), "0");
});

test("intervalos públicos configurados são aplicados sem reduzir mínimos", async (t) => {
  const ui = ambiente({ env: { NEXT_PUBLIC_POLLING_LISTA_MS: "6000", NEXT_PUBLIC_POLLING_STATS_MS: "45000" } });
  t.after(() => ui.desmontar()); await ui.estabilizar();
  lista(ui)[0].resolver([]); stats(ui)[0].resolver({ total: 0, porCategoria: {} });
  await ui.estabilizar();
  await ui.avancar(5999); assert.equal(lista(ui).length, 1);
  await ui.avancar(1); assert.equal(lista(ui).length, 2);
  await ui.avancar(38999); assert.equal(stats(ui).length, 1);
  await ui.avancar(1); assert.equal(stats(ui).length, 2);
});

test("falha inicial encerra spinner sem vazio falso; retry recupera sem mudar aba/filtro", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  lista(ui)[0].rejeitar(new Error("Rede indisponível")); await ui.estabilizar();
  assert.match(ui.html(), /Ofertas podem estar desatualizadas: Rede indisponível/);
  assert.match(ui.html(), /Não foi possível consultar ofertas agora/);
  assert.doesNotMatch(ui.html(), /Carregando ofertas|Nenhuma oferta ainda/);
  await ui.avancar(9999); assert.equal(lista(ui).length, 1);
  await ui.avancar(1); assert.equal(lista(ui).length, 2);
  lista(ui)[1].resolver([oferta()]); await ui.estabilizar();
  assert.equal(ui.cards().length, 1);
  assert.doesNotMatch(ui.html(), /Carregando ofertas|desatualizadas|Não foi possível consultar/);
});

test("refresh pendente/falho mantém cards/CTA, digitação e key; recuperação substitui snapshot", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  lista(ui)[0].resolver([oferta()]); await ui.estabilizar();
  ui.busca().props.onChange("S"); await ui.estabilizar();
  await ui.avancar(5000);
  assert.equal(lista(ui).length, 2);
  assert.equal(ui.cards()[0].key, "901");
  assert.equal(ui.busca().props.valor, "S");
  assert.match(ui.html(), /Ver oferta/); assert.doesNotMatch(ui.html(), /Carregando ofertas/);
  lista(ui)[1].rejeitar(new Error("Falha temporária")); await ui.estabilizar();
  assert.match(ui.html(), /desatualizadas/); assert.equal(ui.cards().length, 1);
  await ui.avancar(10000);
  lista(ui)[2].resolver([{ ...oferta(), preco: 10, foto_url: "/media/foto.webp" }]);
  await ui.estabilizar();
  assert.equal(ui.cards()[0].key, "901"); assert.equal(ui.cards()[0].props.produto.preco, 10);
  assert.equal(ui.busca().props.valor, "S"); assert.doesNotMatch(ui.html(), /desatualizadas|Carregando ofertas/);
  await ui.avancar(5000); lista(ui)[3].resolver([]); await ui.estabilizar();
  assert.equal(ui.cards().length, 0); assert.match(ui.html(), /Nenhuma oferta ainda/);
});

test("troca de filtro cancela geração antiga e resposta tardia não encerra carga atual", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  ui.categoria().props.onChange("games"); await ui.estabilizar();
  assert.equal(lista(ui)[0].signal.aborted, true);
  assert.equal(lista(ui)[1].rota, "/produtos?categoria=games");
  lista(ui)[0].resolver([oferta(1)]); await ui.estabilizar();
  assert.match(ui.html(), /Carregando ofertas/); assert.equal(ui.cards().length, 0);
  lista(ui)[1].resolver([oferta(2)]); await ui.estabilizar();
  assert.doesNotMatch(ui.html(), /Carregando ofertas/); assert.equal(ui.cards()[0].key, "2");
});

test("refresh de token preserva interação/cards; troca de usuário descarta dados e respostas antigas", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  lista(ui)[0].resolver([oferta()]); stats(ui)[0].resolver({ total: 37, porCategoria: {} });
  await ui.estabilizar();
  ui.busca().props.onChange("SSD"); await ui.estabilizar(); await ui.avancar(300);
  const buscaAntiga = lista(ui).at(-1);
  await ui.emitir(sessao("usuario-a", "token-falso-novo"), "TOKEN_REFRESHED");
  assert.equal(buscaAntiga.signal.aborted, true);
  assert.equal(ui.busca().props.valor, "SSD"); assert.equal(ui.cards()[0].key, "901");
  assert.doesNotMatch(ui.html(), /Carregando ofertas/);
  const tokenAntigo = lista(ui).at(-1);
  await ui.emitir(sessao("usuario-b", "token-falso-b"));
  assert.equal(tokenAntigo.signal.aborted, true);
  assert.equal(ui.cards().length, 0); assert.match(ui.html(), /Carregando ofertas/);
  assert.doesNotMatch(ui.html(), />37</);
  tokenAntigo.resolver([oferta(3)]); buscaAntiga.resolver([oferta(4)]);
  await ui.estabilizar(); assert.equal(ui.cards().length, 0);
  lista(ui).at(-1).resolver([oferta(5)]); await ui.estabilizar();
  assert.equal(ui.cards()[0].key, "5");
});

test("página/Auth/API reais não reutilizam SDK de A nos polls da geração B", async (t) => {
  const ui = ambiente({ apiReal: true }); t.after(() => ui.desmontar());
  await ui.estabilizar();
  assert.equal(ui.consultasToken.length, 1, "lista/stats iniciais compartilham consulta");
  assert.equal(ui.chamadas.length, 0, "SDK de A ainda não respondeu");
  const b = sessao("usuario-b", "token-B");
  await ui.emitir(b);
  assert.equal(ui.cards().length, 0);
  assert.equal(ui.consultasToken.length, 1, "consulta SDK antiga permanece única");
  ui.consultasToken[0].resolver({ data: { session: sessao("usuario-a", "token-A") } });
  await ui.estabilizar();
  assert.equal(ui.chamadas.length, 0, "A não atende nem dispara os polls atuais de B");
  assert.equal(ui.consultasToken.length, 2, "geração B obtém credencial em consulta nova");
  ui.consultasToken[1].resolver({ data: { session: b } });
  await ui.estabilizar();
  assert.equal(ui.chamadas.length, 2);
  assert.ok(ui.chamadas.every(c => c.headers.Authorization === "Bearer token-B" && !c.signal.aborted));
  lista(ui)[0].resolver(new Response(JSON.stringify([oferta(902)]), { status: 200 }));
  stats(ui)[0].resolver(new Response(JSON.stringify({ total: 1, porCategoria: {} }), { status: 200 }));
  await ui.estabilizar();
  assert.equal(ui.cards()[0].key, "902");
  assert.doesNotMatch(ui.html(), /Carregando ofertas|desatualizadas/);
});

test("expiração limpa dados, cancela requests/timers e redireciona sem vazio falso", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  lista(ui)[0].resolver([oferta()]); await ui.estabilizar(); await ui.avancar(5000);
  const antiga = lista(ui).at(-1);
  await ui.emitir(null, "SIGNED_OUT");
  assert.equal(antiga.signal.aborted, true); assert.equal(stats(ui)[0].signal.aborted, true);
  assert.match(ui.html(), /Redirecionando para entrar/);
  assert.doesNotMatch(ui.html(), /Oferta sintética|Nenhuma oferta ainda/);
  assert.deepEqual(ui.redirecionamentos, ["/login"]);
  const chamadas = ui.chamadas.length;
  antiga.resolver([oferta(99)]); await ui.avancar(60000);
  assert.equal(ui.chamadas.length, chamadas);
  assert.equal(ui.pendencias().timers, 0);
});

test("página sem sessão inicial redireciona sem iniciar consultas", async (t) => {
  const ui = ambiente({ inicial: null }); t.after(() => ui.desmontar());
  await ui.estabilizar();
  assert.match(ui.html(), /Redirecionando para entrar/);
  assert.deepEqual(ui.redirecionamentos, ["/login"]);
  assert.equal(ui.chamadas.length, 0);
});

test("401 na primeira consulta encerra carga e polling enquanto logout está pendente", async (t) => {
  const ui = ambiente(); t.after(() => ui.desmontar()); await ui.estabilizar();
  lista(ui)[0].rejeitar(new ui.ErroApi("Sessão encerrada", 401)); await ui.estabilizar();
  assert.match(ui.html(), /Redirecionando para entrar/);
  assert.doesNotMatch(ui.html(), /Carregando ofertas|Nenhuma oferta ainda/);
  assert.equal(stats(ui)[0].signal.aborted, true);
  assert.equal(ui.pendencias().saidas, 1);
  await ui.avancar(60000); assert.equal(lista(ui).length, 1);
  ui.logout.resolver({ error: null }); await ui.estabilizar();
  assert.deepEqual(ui.redirecionamentos, ["/login"]);
  assert.equal(ui.pendencias().timers, 0);
});

test("ocultar/unmount cancela gerações e remove listeners sem aceitar respostas tardias", async () => {
  const ui = ambiente(); await ui.estabilizar();
  const primeira = lista(ui)[0];
  await ui.visibilidade(true); assert.equal(primeira.signal.aborted, true);
  await ui.avancar(30000); assert.equal(lista(ui).length, 1);
  await ui.visibilidade(false); assert.equal(lista(ui).length, 2);
  primeira.resolver([oferta(1)]); await ui.estabilizar();
  assert.equal(ui.cards().length, 0); assert.match(ui.html(), /Carregando ofertas/);
  ui.desmontar();
  assert.equal(lista(ui)[1].signal.aborted, true);
  assert.deepEqual(ui.pendencias(), { timers: 0, listeners: 0, assinaturas: 0, saidas: 0 });
  lista(ui)[1].resolver([oferta(2)]); await ui.avancar(60000);
  assert.equal(lista(ui).length, 2);
});

for (const origem of ["getSession", "evento", "rejeição"]) {
  test(`hook real aplica primeira sessão nula por ${origem} e redireciona`, async (t) => {
    const ui = ambiente({ pagina: false, inicial: null, adiarSessao: origem !== "getSession" });
    t.after(() => ui.desmontar()); await ui.estabilizar();
    if (origem === "evento") await ui.emitir(null, "INITIAL_SESSION");
    if (origem === "rejeição") { ui.sessaoInicial.rejeitar(new Error("Auth offline")); await ui.estabilizar(); }
    assert.equal(ui.estado().carregando, false); assert.equal(ui.estado().autenticado, false);
    assert.equal(ui.estado().usuarioId, null); assert.equal(ui.estado().email, null);
    assert.equal(ui.estado().sessaoVersao, 1); assert.deepEqual(ui.redirecionamentos, ["/login"]);
    await ui.emitir(null, "SIGNED_OUT");
    assert.equal(ui.estado().sessaoVersao, 1); assert.deepEqual(ui.redirecionamentos, ["/login"]);
  });
}

test("hook ignora sessão inicial velha após evento, deduplica e aplica refresh/troca/expiração", async (t) => {
  const ui = ambiente({ pagina: false, adiarSessao: true }); t.after(() => ui.desmontar());
  await ui.estabilizar(); assert.equal(ui.estado().carregando, true);
  await ui.emitir(sessao("usuario-b", "token-b"));
  ui.sessaoInicial.resolver({ data: { session: sessao() } }); await ui.estabilizar();
  assert.equal(ui.estado().usuarioId, "usuario-b"); assert.equal(ui.estado().sessaoVersao, 1);
  await ui.emitir(sessao("usuario-b", "token-b")); assert.equal(ui.estado().sessaoVersao, 1);
  await ui.emitir(sessao("usuario-b", "token-b2"), "TOKEN_REFRESHED");
  assert.equal(ui.estado().sessaoVersao, 2); assert.equal(ui.estado().usuarioId, "usuario-b");
  await ui.emitir(sessao("usuario-c", "token-c"));
  assert.equal(ui.estado().usuarioId, "usuario-c"); assert.equal(ui.estado().email, "usuario-c@example.invalid");
  await ui.emitir(null, "SIGNED_OUT");
  assert.equal(ui.estado().autenticado, false); assert.equal(ui.estado().email, null);
  assert.equal(ui.estado().sessaoVersao, 4); assert.deepEqual(ui.redirecionamentos, ["/login"]);
});

test("hook logout retira identidade antes de aguardar signOut e libera assinatura no unmount", async () => {
  const ui = ambiente({ pagina: false }); await ui.estabilizar();
  const saindo = ui.estado().sair(); await ui.estabilizar();
  assert.equal(ui.estado().autenticado, false); assert.equal(ui.estado().usuarioId, null);
  assert.equal(ui.estado().email, null); assert.equal(ui.pendencias().saidas, 1);
  ui.logout.resolver({ error: null }); await saindo; await ui.estabilizar();
  assert.deepEqual(ui.redirecionamentos, ["/login"]);
  ui.desmontar(); assert.equal(ui.pendencias().assinaturas, 0);
  await ui.emitir(sessao("ignorado"));
});
