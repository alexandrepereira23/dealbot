// Executado por browser_run_code_unsafe(filename), com laboratório explícito.
// API/Auth/Telegram/SQL da fixture são falsos; pipeline/Pillow/disco/HTTP/UI reais.
async (page) => {
  const api = "http://127.0.0.1:54328", ui = "http://127.0.0.1:54327";
  const controle = async body => {
    const resposta = await page.request.post(api + "/__lab/controle", { headers: { "x-lab-controle": "sintetico" }, data: body });
    const dados = await resposta.json();
    if (!resposta.ok() || dados.erro) throw new Error(JSON.stringify(dados));
    return dados;
  };
  const config = await (await page.request.get(api + "/__lab/config")).json();
  await page.context().tracing.start({ screenshots: true, snapshots: true });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], { origin: ui });
  await page.route("**/*", route => {
    const origem = new URL(route.request().url()).origin;
    return [api, ui].includes(origem) ? route.continue() : route.abort();
  });
  await page.addInitScript(sessao => {
    localStorage.setItem("sb-127-auth-token", JSON.stringify(sessao));
    window.__renderizados = {};
    window.__gets = [];
    const fetchOriginal = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const inicio = Date.now(), resposta = await fetchOriginal(...args);
      const url = String(args[0]);
      if (url.includes("/api/produtos")) {
        window.__gets.push({ inicio, fim: Date.now(), url, status: resposta.status });
      }
      return resposta;
    };
    const observar = () => {
      new MutationObserver(() => {
        for (const card of document.querySelectorAll("[data-produto-id]")) {
          const id = card.getAttribute("data-produto-id");
          if (!window.__renderizados[id]) window.__renderizados[id] = Date.now();
        }
      }).observe(document.documentElement, { childList: true, subtree: true });
    };
    if (document.documentElement) observar(); else document.addEventListener("DOMContentLoaded", observar, { once: true });
  }, config.sessao);
  const inicial = await controle({ acao: "oferta", foto: true, tamanho: [300, 600] });
  await page.goto(ui);
  const cartao = page.locator(`[data-produto-id="${inicial.id}"]`);
  await cartao.getByRole("link", { name: "Ver oferta", exact: true }).waitFor({ state: "visible" });
  if (await cartao.locator("img").count()) throw new Error("foto apareceu antes da barreira");
  await cartao.getByRole("button", { name: "Copiar cupom" }).click();
  const copiado = await page.evaluate(() => navigator.clipboard.readText());
  if (copiado !== "LAB10") throw new Error("copia antes da foto falhou");
  await cartao.evaluate(no => { no.__mesmaInstancia = "preservada"; });
  const liberada = await controle({ acao: "liberar", msg: inicial.msg });
  if (liberada.estado !== "pronta") throw new Error("midia nao foi concluida");
  await page.waitForFunction(id => {
    const foto = document.querySelector(`[data-produto-id="${id}"] img`);
    return foto?.complete && foto.naturalWidth > 0;
  }, inicial.id);
  if (await cartao.evaluate(no => no.__mesmaInstancia) !== "preservada") throw new Error("card foi remontado");
  const imagem = await cartao.locator("img").getAttribute("src");
  const respostaFoto = await page.request.get(imagem);
  if (respostaFoto.headers()["content-type"] !== "image/webp") throw new Error("formato incorreto");
  const semToken = await page.request.get(api + "/api/produtos");
  if (semToken.status() !== 401) throw new Error("fixture de dados ficou publica");
  const quadros = [{ id: inicial.id, msg: inicial.msg, url: imagem }];
  for (const tamanho of [[700, 250], [300, 300]]) {
    const oferta = await controle({ acao: "oferta", foto: true, tamanho });
    const final = await controle({ acao: "liberar", msg: oferta.msg });
    quadros.push({ id: oferta.id, msg: oferta.msg, url: final.produtos.find(p => p.id === oferta.id).foto_url });
  }
  for (let i = 0; i < 3; i += 1) {
    const oferta = await controle({ acao: "oferta", foto: false });
    quadros.push({ id: oferta.id, msg: oferta.msg, url: null });
  }
  const canais = "canal_" + "X".repeat(160), titulo = "Produto" + "X".repeat(200), cupom = "LAB" + "Y".repeat(120);
  for (const quadro of quadros) {
    await controle({ acao: "mudar", id: quadro.id, campos: { titulo, cupom, canal_origem: canais, produto_aparicoes: [{ canal_origem: canais, visto_em: "2026-11-10T00:00:00Z" }] } });
  }
  const infos = { inicial: inicial.id, quadros, root: config.raiz, copia: copiado, imagem, cacheFoto: respostaFoto.headers()["cache-control"] };
  await page.evaluate(infos => { window.__LAB = infos; }, infos);
  return infos;
}
