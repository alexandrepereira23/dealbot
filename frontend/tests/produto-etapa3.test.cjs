// Renderização do componente real, offline, sem Next startup nem leitura de env.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const arquivo = path.resolve(__dirname, "../components/ProdutoCard.tsx");
const compilado = ts.transpileModule(fs.readFileSync(arquivo, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
    target: ts.ScriptTarget.ES2020, esModuleInterop: true },
}).outputText;
const modulo = { exports: {} };
const importar = (nome) => {
  assert.ok(["react", "react/jsx-runtime"].includes(nome), `Importação offline inesperada: ${nome}`);
  return require(nome);
};
vm.runInThisContext(`(function(require,module,exports){${compilado}\n})`, { filename: arquivo })(importar, modulo, modulo.exports);
const Card = modulo.exports.ProdutoCard;
const produto = { id: 1, titulo: "Produto sintético", preco: 250, preco_original: null,
  cupom: null, link: null, foto_url: null, categoria: "games", canal_origem: "canal_a",
  criado_em: "2026-10-01T10:00:00Z", data_oferta: "2026-11-05T10:00:00Z",
  preco_anterior_atualizacao: 300, preco_observado_em: "2026-11-05T10:00:00Z" };
const renderizar = (extras = {}) => renderToStaticMarkup(React.createElement(Card, { produto: { ...produto, ...extras } }));

test("queda verdadeira usa preço anterior da atualização e não fabrica desconto anunciado", () => {
  const html = renderizar();
  assert.match(html, /Preço caiu de R\$ 300.00/);
  assert.match(html, /2026/);
  assert.doesNotMatch(html, /produto__badge|produto__price-old/);
  assert.match(html, /R\$ 250.00/);
});

test("desconto anunciado continua separado da queda histórica", () => {
  const html = renderizar({ preco_original: 500, preco_anterior_atualizacao: 275 });
  assert.match(html, /-50%/);
  assert.match(html, /Preço caiu de R\$ 275.00/);
  assert.doesNotMatch(html, /-9%|-10%/);
});

test("subida atualiza preço sem anunciar queda, igualdade não inventa mudança", () => {
  const subida = renderizar({ preco: 350 });
  assert.match(subida, /R\$ 350.00/);
  assert.match(subida, /Preço atualizado/);
  assert.doesNotMatch(subida, /Preço caiu|produto__badge/);
  assert.doesNotMatch(renderizar({ preco: 300 }), /Preço atualizado|Preço caiu/);
});

test("nulo, ausência ou data inválida não viram zero nem queda fictícia", () => {
  for (const extras of [{ preco: null }, { preco_anterior_atualizacao: null },
    { preco_anterior_atualizacao: undefined }, { preco_observado_em: null },
    { preco_observado_em: undefined }, { preco_observado_em: "inválida" }]) {
    assert.doesNotMatch(renderizar(extras), /Preço atualizado|Preço caiu/);
  }
  assert.match(renderizar({ preco: null }), /R\$ —/);
  assert.doesNotMatch(renderizar({ preco: null }), /produto__badge/);
});

test("zero é preço conhecido tanto na queda quanto na subida", () => {
  const gratuito = renderizar({ preco: 0 });
  assert.match(gratuito, /R\$ 0.00/);
  assert.match(gratuito, /Preço caiu de R\$ 300.00/);
  const deixouGratuito = renderizar({ preco_anterior_atualizacao: 0, preco: 10 });
  assert.match(deixouGratuito, /Preço atualizado/);
  assert.doesNotMatch(deixouGratuito, /Preço caiu/);
});

test("legado preserva foto nula, canais, cupom e link sem metadados novos", () => {
  const html = renderizar({ preco_anterior_atualizacao: undefined, preco_observado_em: undefined,
    canais: ["canal_a", "canal_b"], cupom: "AbC10", link: "https://loja.example.invalid/oferta" });
  assert.match(html, /Sem foto/);
  assert.match(html, /@canal_a/);
  assert.match(html, /\+1/);
  assert.match(html, /AbC10/);
  assert.match(html, /Ver oferta/);
  assert.doesNotMatch(html, /Preço atualizado|Preço caiu/);
});
