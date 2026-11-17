import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

assert.ok(path.isAbsolute(process.env.DEALBOT_PLAYWRIGHT_MODULE || ""));
const { chromium } = await import(pathToFileURL(process.env.DEALBOT_PLAYWRIGHT_MODULE));
const origem = process.env.LAB_ORIGIN || "https://localhost:18443";
assert.match(origem, /^https:\/\/localhost:\d+$/);
const controle = async dados => {
  const r = await fetch("http://127.0.0.1:54329/__lab/controle", { method: "POST",
    headers: { "Content-Type": "application/json", "x-lab-controle": "sintetico" }, body: JSON.stringify(dados) });
  assert.equal(r.status, 200);
};
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const erros = [];
  page.on("pageerror", erro => erros.push(erro.message));
  // Não permitir acesso a qualquer origem real, inclusive compra da fixture.
  await context.route("**/*", route => {
    const u = new URL(route.request().url());
    return [origem, "http://127.0.0.1:54329"].includes(u.origin) ? route.continue() : route.abort();
  });
  await page.goto(origem + "/login");
  await page.getByLabel("E-mail").fill("lab@example.invalid");
  await page.getByLabel("Senha").fill("laboratorio123");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(origem + "/");
  await controle({ acao: "oferta" });
  const card = page.locator("[data-produto-id]").first();
  await card.getByRole("link", { name: "Ver oferta", exact: true }).waitFor({ timeout: 25_000 });
  assert.equal(await card.locator("img").count(), 0, "Compra deve aparecer antes da foto");
  const id = await card.getAttribute("data-produto-id");
  await card.evaluate(no => { no.__instanciaLab = true; });
  await controle({ acao: "foto" });
  await page.waitForFunction(() => {
    const img = document.querySelector("[data-produto-id] img");
    return img?.complete && img.naturalWidth > 0;
  }, null, { timeout: 25_000 });
  assert.equal(await card.evaluate(no => no.__instanciaLab), true);
  const foto = await card.locator("img").getAttribute("src");
  assert.ok(foto.startsWith(origem + "/media/"));
  const resposta = await context.request.get(foto);
  assert.equal(resposta.status(), 200);
  assert.match(resposta.headers()["content-type"], /image\/webp/);
  assert.equal((await context.request.head(foto)).status(), 200);
  assert.equal((await context.request.get(origem + "/api/produtos")).status(), 401);
  const cors = await context.request.get(origem + "/api/health", { headers: { Origin: origem } });
  assert.equal(cors.headers()["access-control-allow-origin"], origem);
  const corsNegado = await context.request.get(origem + "/api/health", { headers: { Origin: "https://fora.invalid" } });
  assert.equal(corsNegado.headers()["access-control-allow-origin"], undefined);
  const html = await context.request.get(origem + "/");
  const csp = html.headers()["content-security-policy"];
  assert.match(csp, /img-src[^;]*'self'[^;]*http:\/\/127.0.0.1:54329/);
  const legado = await page.evaluate(async () => {
    const img = new Image();
    img.src = "http://127.0.0.1:54329/storage/v1/object/public/produtos/legada.webp";
    try { await img.decode(); return img.naturalWidth > 0; } catch { return false; }
  });
  assert.equal(legado, true, "CSP deve permitir a origem legada Supabase");
  await controle({ acao: "auth", falhar: true });
  await page.waitForResponse(r => r.url().includes("/api/produtos") && r.status() === 503, { timeout: 15_000 });
  assert.equal(await card.getAttribute("data-produto-id"), id);
  assert.equal(new URL(page.url()).pathname, "/");
  await controle({ acao: "auth", falhar: false });
  await page.waitForResponse(r => r.url().includes("/api/produtos") && r.status() === 200, { timeout: 20_000 });
  assert.equal(await card.evaluate(no => no.__instanciaLab), true);
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await card.getByRole("link", { name: "Ver oferta", exact: true }).isVisible(), true);
  }
  assert.deepEqual(erros, []);
  console.log("Browser: login sintético, polling sem F5, mesmo card/WebP, legado/CSP, 401, 503→200 e celular/desktop aprovados");
  await context.close();
} finally {
  await controle({ acao: "auth", falhar: false }).catch(() => {});
  await browser.close();
}
