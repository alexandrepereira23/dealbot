// Duas amostras por chamada para respeitar o orçamento do transporte MCP.
async (page) => {
  const fases = [100, 700, 1400, 2200, 2900, 3500, 4100, 4700, 200, 2600];
  const anteriores = await page.evaluate(() => window.__amostrasEtapa4 || []);
  if (!anteriores.length) await page.evaluate(() => { window.__inicioMedicoes = Date.now(); });
  const amostras = [];
  for (let i = anteriores.length; i < Math.min(anteriores.length + 2, fases.length); i += 1) {
    const resposta = await page.waitForResponse(r => new URL(r.url()).pathname === "/api/produtos" && r.request().method() === "GET" && r.status() === 200, { timeout: 10000 });
    await resposta.finished();
    const inicioCiclo = await page.evaluate(() => window.__gets.filter(r => new URL(r.url).pathname === "/api/produtos").at(-1).fim);
    // Espera intencional define a fase da inserção; não é auto-wait de UI.
    await page.evaluate(ms => new Promise(resolve => setTimeout(resolve, ms)), fases[i]);
    const res = await page.request.post("http://127.0.0.1:54328/__lab/controle", {
      headers: { "x-lab-controle": "sintetico" }, data: { acao: "oferta", foto: false },
    });
    const oferta = await res.json();
    if (!res.ok() || oferta.erro) throw new Error(JSON.stringify(oferta));
    await page.waitForFunction(id => window.__renderizados[id], oferta.id, { timeout: 10000 });
    const render = await page.evaluate(id => ({ render: window.__renderizados[id], oculta: document.hidden,
      ultimoPoll: window.__gets.filter(r => new URL(r.url).pathname === "/api/produtos").at(-1) }), oferta.id);
    const amostra = { id: oferta.id, fasePlanejada: fases[i], faseObservada: Math.round(oferta.disponivel_em - inicioCiclo),
      api: oferta.disponivel_em, render: render.render, latencia: Math.round(render.render - oferta.disponivel_em), foto: null, oculta: render.oculta };
    if (render.oculta || amostra.latencia < 0 || amostra.latencia > 5500) throw new Error(JSON.stringify(amostra));
    amostras.push(amostra);
  }
  const todas = [...anteriores, ...amostras];
  await page.evaluate(todas => { window.__amostrasEtapa4 = todas; }, todas);
  const volume = await page.evaluate(() => {
    const fim = Date.now(), gets = window.__gets.filter(r => r.inicio >= window.__inicioMedicoes);
    return { duracaoMs: fim - window.__inicioMedicoes, lista: gets.filter(r => new URL(r.url).pathname === "/api/produtos").length,
      stats: gets.filter(r => new URL(r.url).pathname.endsWith("/estatisticas")).length, total: gets.length };
  });
  return { amostras, realizadas: todas.length, volume };
}
