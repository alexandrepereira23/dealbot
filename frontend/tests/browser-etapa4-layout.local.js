// Executar após browser-etapa4.local.js no mesmo contexto sintético.
async (page) => {
  const api = "http://127.0.0.1:54328";
  const dados = await page.evaluate(() => window.__LAB);
  const controle = async body => {
    const res = await page.request.post(api + "/__lab/controle", { headers: { "x-lab-controle": "sintetico" }, data: body });
    const dados = await res.json(); if (!res.ok() || dados.erro) throw new Error(JSON.stringify(dados)); return dados;
  };
  if (!dados.lentaPreparada) {
    const extra = await controle({ acao: "oferta", foto: true, tamanho: [400, 300] });
    const final = await controle({ acao: "liberar", msg: extra.msg });
    const lenta = final.produtos.find(p => p.id === extra.id).foto_url;
    await controle({ acao: "mudar", id: extra.id, campos: { removido: true } });
    let liberar;
    const barreira = new Promise(resolve => { liberar = resolve; });
    page.__liberarFotoLentaEtapa4 = liberar;
    await page.route("**" + lenta, async route => { await barreira; await route.continue().catch(() => {}); });
    dados.quadros[4].url = lenta;
    dados.quadros[5].url = "/media/" + "b".repeat(32) + ".webp";
    dados.lentaPreparada = true;
    await page.evaluate(dados => { window.__LAB = dados; }, dados);
  }
  const ids = dados.quadros.map(p => String(p.id));
  const geometria = () => page.evaluate(ids => ids.map(id => {
    const card = document.querySelector(`[data-produto-id="${id}"]`);
    const media = card.querySelector(".produto__media"), r = media.getBoundingClientRect();
    return { id, largura: r.width, altura: r.height, overflow: card.scrollWidth > card.clientWidth,
      fit: card.querySelector("img") ? getComputedStyle(card.querySelector("img")).objectFit : null };
  }), ids);
  const resultados = [];
  const larguras = await page.evaluate(() => window.__largurasQA ?? [320]);
  for (const largura of larguras) {
    await page.setViewportSize({ width: largura, height: 900 });
    for (const quadro of dados.quadros) await controle({ acao: "mudar", id: quadro.id, campos: { foto_url: null } });
    await page.waitForFunction(ids => ids.every(id => {
      const card = document.querySelector(`[data-produto-id="${id}"]`); return card && !card.querySelector("img");
    }), ids, { timeout: 10000 });
    const antes = await geometria();
    for (const quadro of dados.quadros) await controle({ acao: "mudar", id: quadro.id, campos: { foto_url: quadro.url } });
    await page.waitForFunction(ids => ids.slice(0, 3).every(id => document.querySelector(`[data-produto-id="${id}"] img`)), ids, { timeout: 10000 });
    // Aguardar o snapshot antes do scroll: rolar quando ainda não existe img não
    // aciona lazy loading. Isso é instrumentação, não mudança do componente.
    for (const quadro of dados.quadros) await page.locator(`[data-produto-id="${quadro.id}"]`).scrollIntoViewIfNeeded();
    for (const id of ids.slice(0, 3)) {
      await page.locator(`[data-produto-id="${id}"]`).scrollIntoViewIfNeeded();
      await page.waitForFunction(id => {
        const img = document.querySelector(`[data-produto-id="${id}"] img`); return img?.complete && img.naturalWidth > 0;
      }, id, { timeout: 10000 });
    }
    await page.waitForFunction(id => {
      const card = document.querySelector(`[data-produto-id="${id}"]`); return !card.querySelector("img") && card.querySelector(".produto__no-photo");
    }, ids[5], { timeout: 10000 });
    const depois = await geometria();
    const pagina = await page.evaluate(() => ({ largura: window.innerWidth, client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    const diferenca = Math.max(...antes.map((a, i) => Math.max(Math.abs(a.largura - depois[i].largura), Math.abs(a.altura - depois[i].altura))));
    if (pagina.scroll > pagina.client || diferenca > 1 || depois.some(r => r.overflow || Math.abs(r.altura - r.largura * .75) > 1 || (r.fit && r.fit !== "contain"))) {
      throw new Error(JSON.stringify({ largura, antes, depois, pagina, diferenca }));
    }
    for (const id of [ids[3], ids[4], ids[5]]) {
      const card = page.locator(`[data-produto-id="${id}"]`);
      const cta = card.getByRole("link", { name: "Ver oferta", exact: true });
      await cta.scrollIntoViewIfNeeded();
      if (!await cta.isVisible() || !await cta.getAttribute("href")) throw new Error("CTA bloqueado");
      // Click real com hit-testing; impedir navegação no próprio elemento garante
      // que o teste jamais abre a loja, mas detecta mídia sobrepondo o CTA.
      await cta.evaluate(no => { no.__clicado = false; no.addEventListener("click", evento => { evento.preventDefault(); no.__clicado = true; }, { once: true }); });
      await cta.click({ timeout: 3000 });
      if (!await cta.evaluate(no => no.__clicado)) throw new Error("CTA não recebeu click");
      await card.getByRole("button", { name: "Copiar cupom" }).click({ timeout: 3000 });
      const cupom = await card.locator(".produto__coupon strong").innerText();
      if (await page.evaluate(() => navigator.clipboard.readText()) !== cupom) throw new Error("cópia bloqueada");
    }
    await page.screenshot({ path: `C:/Users/Alexandre_HP/AppData/Local/Temp/opencode/dealbot-etapa4-layout-final-${largura}.png`, fullPage: true });
    resultados.push({ largura: pagina.largura, areas: depois, diferenca, overflow: pagina.scroll > pagina.client });
  }
  await page.evaluate(resultados => { window.__layoutEtapa4 = [...(window.__layoutEtapa4 || []), ...resultados]; }, resultados);
  if (!larguras.includes(1440)) return { resultados, restante: true };
  // Mesmo card falhou em A; trocar para B deve carregar sem herdar erro.
  await controle({ acao: "mudar", id: dados.quadros[5].id, campos: { foto_url: dados.quadros[2].url } });
  await page.waitForFunction(id => {
    const img = document.querySelector(`[data-produto-id="${id}"] img`); return img?.complete && img.naturalWidth > 0;
  }, ids[5]);
  page.__liberarFotoLentaEtapa4();
  await page.waitForFunction(id => {
    const img = document.querySelector(`[data-produto-id="${id}"] img`); return img?.complete && img.naturalWidth > 0;
  }, ids[4]);
  return { resultados, fotoAparaB: true, lentaLiberada: true };
}
