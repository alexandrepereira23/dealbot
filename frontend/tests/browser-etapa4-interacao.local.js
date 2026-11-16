// Após a preparação sintética: React/DOM reais, evento antigo injetado explícito.
async (page) => {
  const dados = await page.evaluate(() => window.__LAB);
  const controle = async body => {
    const res = await page.request.post("http://127.0.0.1:54328/__lab/controle", { headers: { "x-lab-controle": "sintetico" }, data: body });
    const dados = await res.json(); if (!res.ok() || dados.erro) throw new Error(JSON.stringify(dados)); return dados;
  };
  const card = page.locator(`[data-produto-id="${dados.inicial}"]`);
  await card.locator("img").scrollIntoViewIfNeeded();
  await card.locator("img").evaluate(no => {
    const props = no[Object.keys(no).find(k => k.startsWith("__reactProps$"))];
    if (!props?.onError) throw new Error("handler React não encontrado");
    window.__erroImagemAntiga = props.onError;
  });
  await card.evaluate(no => { no.__instancia = "preservada"; });
  await controle({ acao: "mudar", id: dados.inicial, campos: { foto_url: dados.quadros[2].url } });
  await page.waitForFunction(({ id, url }) => {
    const img = document.querySelector(`[data-produto-id="${id}"] img`);
    return img?.src.endsWith(url) && img.complete && img.naturalWidth > 0;
  }, { id: dados.inicial, url: dados.quadros[2].url }, { timeout: 10000 });
  // Chamada do callback de A capturado ANTES do unmount, depois de B carregar.
  // Não se apresenta esta injeção como erro de rede natural da URL anterior.
  await page.evaluate(() => window.__erroImagemAntiga());
  await page.evaluate(() => new Promise(requestAnimationFrame));
  if (!await card.locator("img").isVisible() || await card.evaluate(no => no.__instancia) !== "preservada") throw new Error("erro de A afetou B");
  const busca = page.getByRole("searchbox");
  await Promise.all([
    page.waitForResponse(r => new URL(r.url()).searchParams.get("q") === "Produto" && r.status() === 200),
    busca.fill("Produto"),
  ]);
  await page.waitForFunction(() => document.querySelectorAll("[data-produto-id]").length >= 6);
  await page.setViewportSize({ width: 375, height: 900 });
  await card.scrollIntoViewIfNeeded();
  const ancora = await card.evaluate(no => ({ topo: no.getBoundingClientRect().top, scroll: scrollY }));
  const novo = await controle({ acao: "oferta", foto: false });
  await page.locator(`[data-produto-id="${novo.id}"]`).waitFor({ state: "attached", timeout: 10000 });
  const depois = await card.evaluate(no => ({ topo: no.getBoundingClientRect().top, scroll: scrollY }));
  if (Math.abs(depois.topo - ancora.topo) > 1 || await busca.inputValue() !== "Produto") throw new Error(JSON.stringify({ ancora, depois }));
  const categoria = page.getByRole("button", { name: "Outros", exact: false });
  await Promise.all([
    page.waitForResponse(r => new URL(r.url()).searchParams.get("categoria") === "outros" && r.status() === 200),
    categoria.click(),
  ]);
  if (await busca.inputValue() !== "Produto") throw new Error("filtro apagou busca");
  return { erroTardioInjetadoNaoAfetouB: true, cardFisicoPreservado: true, buscaPreservada: true, ancora, depois, categoria: "outros" };
}
