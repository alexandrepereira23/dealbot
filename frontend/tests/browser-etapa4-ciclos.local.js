// Next DEV em loopback: confirma Strict Effects reais. Não mede latência.
// Visibilidade é evento/propriedade injetados; não equivale a aba nativa oculta.
async (page) => {
  const api = "http://127.0.0.1:54328", ui = "http://127.0.0.1:54327";
  const { sessao } = await (await page.request.get(api + "/__lab/config")).json();
  const estado = { lista: 0, stats: 0, segurar: false, limitada: false, negar: false, liberar: null, iniciou: null };
  const produto = { id: 901, titulo: "Produto de ciclo sintético", preco: 0, categoria: "outros", foto_url: null,
    criado_em: new Date().toISOString(), cupom: "LAB10", link: "https://loja.invalid/oferta" };
  await page.context().tracing.start({ screenshots: true, snapshots: true });
  await page.addInitScript(sessao => {
    localStorage.setItem("sb-127-auth-token", JSON.stringify(sessao));
    window.__ciclos = { ativos: {}, maximos: {}, inicios: [] };
    const original = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const rota = new URL(String(args[0]), location.origin).pathname;
      if (!rota.startsWith("/api/produtos")) return original(...args);
      const c = window.__ciclos; c.ativos[rota] = (c.ativos[rota] || 0) + 1;
      c.maximos[rota] = Math.max(c.maximos[rota] || 0, c.ativos[rota]); c.inicios.push({ rota, instante: Date.now() });
      try { return await original(...args); } finally { c.ativos[rota] -= 1; }
    };
    window.__ocultar = valor => {
      Object.defineProperty(document, "hidden", { configurable: true, value: valor });
      document.dispatchEvent(new Event("visibilitychange"));
    };
  }, sessao);
  await page.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/produtos" && url.origin === api) {
      estado.lista += 1; estado.iniciou?.();
      if (estado.segurar) await new Promise(resolve => { estado.liberar = resolve; });
      await route.fulfill({ status: estado.negar ? 401 : estado.limitada ? 429 : 200,
        headers: { "Cache-Control": "no-store", ...(estado.limitada ? { "Retry-After": "125", "Access-Control-Expose-Headers": "Retry-After" } : {}) },
        contentType: "application/json", body: JSON.stringify(estado.negar || estado.limitada ? { erro: "falha-sintetica" } : [produto]) }).catch(() => {});
    } else if (url.pathname === "/api/produtos/estatisticas" && url.origin === api) {
      estado.stats += 1;
      await route.fulfill({ contentType: "application/json", body: '{"total":1,"porCategoria":{"outros":1}}' });
    } else if (url.pathname.startsWith("/api/filtros")) {
      await route.fulfill({ contentType: "application/json", body: "[]" });
    } else if (url.origin === "http://127.0.0.1:54329" && url.pathname === "/auth/v1/logout") {
      await route.fulfill({ status: 204 });
    } else if (url.origin === ui) await route.continue();
    else await route.abort();
  });
  page.__estadoCiclosEtapa4 = estado;
  await page.goto(ui);
  const card = page.locator('[data-produto-id="901"]'); await card.waitFor({ state: "visible" });
  const modo = await card.evaluate(no => no[Object.keys(no).find(k => k.startsWith("__reactFiber$"))]?.mode);
  if ((modo & 24) !== 24) throw new Error(`StrictLegacy/StrictEffects não ativos: ${modo}`);
  return { strictLegacy: true, strictEffects: true, modo, lista: estado.lista, stats: estado.stats };
}
