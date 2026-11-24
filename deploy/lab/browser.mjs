import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import https from "node:https";
import path from "node:path";
import { pathToFileURL } from "node:url";

assert.ok(path.isAbsolute(process.env.DEALBOT_PLAYWRIGHT_MODULE || ""));
const { chromium } = await import(pathToFileURL(process.env.DEALBOT_PLAYWRIGHT_MODULE));
const origem = process.env.LAB_ORIGIN || "https://localhost:18443";
assert.match(origem, /^https:\/\/localhost:\d+$/);
const mock = "http://127.0.0.1:54329";
const ca = process.env.LAB_CADDY_CA ? await readFile(process.env.LAB_CADDY_CA) : undefined;
const ofertaPendente = process.argv.includes("--oferta-pendente");
assert.ok(!ofertaPendente || ca, "O ensaio Compose exige a CA extraída do próprio Caddy");
const celular = { width: 390, height: 844 };
const desktop = { width: 1440, height: 900 };

const controle = async dados => {
  const r = await fetch(mock + "/__lab/controle", { method: "POST",
    headers: { "Content-Type": "application/json", "x-lab-controle": "sintetico" },
    body: JSON.stringify(dados), signal: AbortSignal.timeout(5000) });
  assert.equal(r.status, 200);
};

function solicitar(url, opcoes = {}) {
  assert.equal(new URL(url).origin, origem);
  return new Promise((resolve, reject) => {
    const req = https.request(url, { ca, rejectUnauthorized: Boolean(ca), family: 4, timeout: 5000, ...opcoes }, res => {
      const certificado = res.socket.getPeerX509Certificate();
      res.resume();
      resolve({ status: res.statusCode, headers: res.headers, certificado });
    });
    req.once("timeout", () => req.destroy(new Error("HTTPS do laboratório indisponível")));
    req.once("error", reject);
    req.end();
  });
}

const args = [];
if (ca) {
  // Valida cadeia e hostname com a CA do projeto antes de extrair a chave TLS.
  // Chromium não precisa alterar a confiança do host: a exceção é só para esta chave.
  const resposta = await solicitar(origem + "/login");
  assert.equal(resposta.status, 200);
  const chave = resposta.certificado.publicKey.export({ type: "spki", format: "der" });
  const spki = createHash("sha256").update(chave).digest("base64");
  args.push(`--ignore-certificate-errors-spki-list=${spki}`);
}

const browser = await chromium.launch({ headless: true, args });
const erros = [];

async function logar(movel) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: !ca, // Apenas o smoke histórico de host sem CA; não realiza o ensaio Clipboard.
    viewport: movel || !ca ? celular : desktop,
    isMobile: movel, hasTouch: movel, serviceWorkers: "block",
  });
  const page = await context.newPage();
  page.on("pageerror", erro => erros.push(erro.message));
  // Não permitir acesso a qualquer origem real, inclusive compra da fixture.
  await context.route("**/*", route => {
    const u = new URL(route.request().url());
    return [origem, mock].includes(u.origin) ? route.continue() : route.abort();
  });
  await page.goto(origem + "/login");
  await page.getByLabel("E-mail").fill("lab@example.invalid");
  await page.getByLabel("Senha").fill("laboratorio123");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(origem + "/");
  return { context, page };
}

async function testarClipboard({ context, page }, card, movel) {
  const modo = movel ? "móvel" : "desktop";
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: origem });
  await page.bringToFront();
  assert.equal(await page.evaluate(() => isSecureContext && location.protocol === "https:" &&
    typeof navigator.clipboard?.writeText === "function" && typeof navigator.clipboard?.readText === "function"),
    true, `Clipboard API deve estar disponível num contexto HTTPS seguro (${modo})`);
  if (movel) assert.ok(await page.evaluate(() => navigator.maxTouchPoints > 0));
  await card.getByText("LAB10", { exact: true }).waitFor({ state: "visible" });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  const sentinela = `limpar-clipboard-${modo}`;
  assert.equal(await page.evaluate(async texto => {
    await navigator.clipboard.writeText(texto);
    return navigator.clipboard.readText();
  }, sentinela), sentinela);
  const copiar = card.getByRole("button", { name: "Copiar cupom", exact: true });
  if (movel) await copiar.tap();
  else await copiar.click();
  await page.waitForFunction(() => navigator.clipboard.readText().then(texto => texto === "LAB10"),
    null, { timeout: 5000 });
  console.log(`Clipboard API em contexto HTTPS seguro: ${modo} copiou LAB10`);
}

try {
  const sessao = await logar(Boolean(ca));
  const { context, page } = sessao;
  if (!ofertaPendente) await controle({ acao: "oferta" });
  const cards = page.locator("[data-produto-id]");
  const card = ofertaPendente ? cards : cards.first();
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
  const resposta = await solicitar(foto);
  assert.equal(resposta.status, 200);
  assert.match(resposta.headers["content-type"], /image\/webp/);
  assert.equal((await solicitar(foto, { method: "HEAD" })).status, 200);
  assert.equal((await solicitar(origem + "/api/produtos")).status, 401);
  const cors = await solicitar(origem + "/api/health", { headers: { Origin: origem } });
  assert.equal(cors.headers["access-control-allow-origin"], origem);
  const corsNegado = await solicitar(origem + "/api/health", { headers: { Origin: "https://fora.invalid" } });
  assert.equal(corsNegado.headers["access-control-allow-origin"], undefined);
  const html = await solicitar(origem + "/");
  const csp = html.headers["content-security-policy"];
  assert.match(csp, /img-src[^;]*'self'[^;]*http:\/\/127.0.0.1:54329/);
  const legado = await page.evaluate(async () => {
    const img = new Image();
    img.src = "http://127.0.0.1:54329/storage/v1/object/public/produtos/legada.webp";
    try { await img.decode(); return img.naturalWidth > 0; } catch { return false; }
  });
  assert.equal(legado, true, "CSP deve permitir a origem legada Supabase");
  await Promise.all([
    page.waitForResponse(r => r.url().includes("/api/produtos") && r.status() === 503, { timeout: 15_000 }),
    controle({ acao: "auth", falhar: true }),
  ]);
  assert.equal(await card.getAttribute("data-produto-id"), id);
  assert.equal(new URL(page.url()).pathname, "/");
  await Promise.all([
    page.waitForResponse(r => r.url().includes("/api/produtos") && r.status() === 200, { timeout: 20_000 }),
    controle({ acao: "auth", falhar: false }),
  ]);
  assert.equal(await card.evaluate(no => no.__instanciaLab), true);
  if (ca) {
    await testarClipboard(sessao, card, true);
    await context.close();
    const sessaoDesktop = await logar(false);
    const cardDesktop = sessaoDesktop.page.locator("[data-produto-id]");
    await cardDesktop.getByRole("link", { name: "Ver oferta", exact: true }).waitFor();
    assert.equal(await cardDesktop.getAttribute("data-produto-id"), id);
    await testarClipboard(sessaoDesktop, cardDesktop, false);
    await sessaoDesktop.context.close();
  } else {
    for (const viewport of [celular, desktop]) {
      await page.setViewportSize(viewport);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await card.getByRole("link", { name: "Ver oferta", exact: true }).isVisible(), true);
    }
    await context.close();
  }
  assert.deepEqual(erros, []);
  console.log("Browser: login sintético, polling sem F5, mesmo card/WebP, legado/CSP, 401, 503→200 e celular/desktop aprovados");
} finally {
  await controle({ acao: "auth", falhar: false }).catch(() => {});
  await browser.close();
}
