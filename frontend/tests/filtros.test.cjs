// UI real transpilada com TypeScript instalado; hooks, API e Auth locais/falsos.
// Não abre servidor, não carrega .env e não duplica a avaliação de ofertas Python.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function ambiente(registros = []) {
  const linhas = structuredClone(registros);
  const chamadas = [];
  let erroServidor = "";
  const api = {
    async get(url) {
      chamadas.push({ metodo: "GET", url });
      if (erroServidor) throw new Error(erroServidor);
      return structuredClone(linhas);
    },
    async post(url, corpo) {
      chamadas.push({ metodo: "POST", url, corpo: structuredClone(corpo) });
      if (erroServidor) throw new Error(erroServidor);
      const linha = { id: linhas.length + 1, ativo: true, ...corpo };
      linhas.push(linha); return structuredClone(linha);
    },
    async put(url, corpo) {
      chamadas.push({ metodo: "PUT", url, corpo: structuredClone(corpo) });
      if (erroServidor) throw new Error(erroServidor);
      const linha = linhas.find((item) => item.id === Number(url.split("/").at(-1)));
      assert.ok(linha); Object.assign(linha, corpo); return structuredClone(linha);
    },
    async del(url) {
      chamadas.push({ metodo: "DELETE", url });
      if (erroServidor) throw new Error(erroServidor);
      linhas.splice(linhas.findIndex((item) => item.id === Number(url.split("/").at(-1))), 1);
    },
  };
  let cursor = 0;
  const slots = [];
  const efeitos = [];
  const iguais = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const reactFalso = { ...React,
    useState(inicial) {
      const indice = cursor++;
      if (!(indice in slots)) slots[indice] = typeof inicial === "function" ? inicial() : inicial;
      return [slots[indice], (valor) => {
        slots[indice] = typeof valor === "function" ? valor(slots[indice]) : valor;
      }];
    },
    useCallback(fn, deps) {
      const indice = cursor++;
      if (!iguais(slots[indice]?.deps, deps)) slots[indice] = { deps, fn };
      return slots[indice].fn;
    },
    useEffect(fn, deps) {
      const indice = cursor++;
      if (!iguais(slots[indice], deps)) { slots[indice] = deps; efeitos.push(fn); }
    },
  };
  const cache = new Map();
  function carregar(arquivo) {
    const absoluto = path.resolve(__dirname, "..", arquivo);
    if (cache.has(absoluto)) return cache.get(absoluto);
    const compilado = ts.transpileModule(fs.readFileSync(absoluto, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
        target: ts.ScriptTarget.ES2020, esModuleInterop: true },
    }).outputText;
    const modulo = { exports: {} };
    cache.set(absoluto, modulo.exports);
    const importar = (nome) => {
      if (nome === "react") return reactFalso;
      if (nome === "@/hooks/useAuth") return { useAuth: () => ({ carregando: false, email: "teste@example.invalid", sair() {} }) };
      if (nome === "@/lib/api") return { api };
      if (nome === "@/components/Header") return { Header: () => React.createElement("header", null, "Sessão falsa") };
      if (nome.startsWith("@/")) return carregar(`${nome.slice(2)}.ts`);
      if (nome.startsWith(".")) return carregar(path.relative(path.resolve(__dirname, ".."), path.resolve(path.dirname(absoluto), `${nome}.ts`)));
      if (nome === "react/jsx-runtime") return require(nome);
      throw new Error(`Importação inesperada no teste offline: ${nome}`);
    };
    vm.runInThisContext(`(function(require,module,exports){${compilado}\n})`, { filename: absoluto })(importar, modulo, modulo.exports);
    return modulo.exports;
  }
  const Pagina = carregar("app/filtros/page.tsx").default;
  let arvore;
  function renderizar() { cursor = 0; arvore = Pagina(); }
  async function estabilizar() {
    renderizar();
    while (efeitos.length) {
      for (const efeito of efeitos.splice(0)) efeito();
      await new Promise(setImmediate);
      renderizar();
    }
  }
  function elementos(no, resultado = []) {
    if (!no || typeof no !== "object") return resultado;
    if (Array.isArray(no)) { no.forEach((filho) => elementos(filho, resultado)); return resultado; }
    if (typeof no.type === "function") return elementos(no.type(no.props), resultado);
    resultado.push(no);
    elementos(no.props?.children, resultado);
    return resultado;
  }
  const texto = (no) => renderToStaticMarkup(no).replace(/<[^>]*>/g, "");
  const campo = (id) => {
    const encontrado = elementos(arvore).find((no) => no.props?.id === id);
    assert.ok(encontrado, `Campo ${id}`); return encontrado;
  };
  async function alterar(id, value) { campo(id).props.onChange({ target: { value } }); await estabilizar(); }
  async function clicar(rotulo, escopo) {
    const botao = elementos(escopo ?? arvore).find((no) => no.type === "button" && texto(no) === rotulo);
    assert.ok(botao, `Botão ${rotulo}`); await botao.props.onClick(); await estabilizar();
  }
  const artigo = (nome) => elementos(arvore).find((no) => no.type === "article" && texto(no).includes(nome));
  return { api, linhas, chamadas, carregar, estabilizar, alterar, clicar, campo, artigo,
    html: () => renderToStaticMarkup(arvore), texto: () => texto(arvore),
    falhar(mensagem) { erroServidor = mensagem; } };
}

const regra = (extras = {}) => ({ id: 1, nome: "Interesse pausado", palavras_chave: ["SSD"],
  palavras_bloqueio: ["usado"], categoria: "eletronicos", preco_max: 0, ativo: false,
  tipo_regra: "interesse", modo_palavras: "todas", ...extras });

test("criar/listar interesses e globais, todos/qualquer, limpar inclusões e pausar", async () => {
  const ui = ambiente(); await ui.estabilizar();
  assert.match(ui.texto(), /descrição completa/);
  assert.match(ui.texto(), /\(OU\)/); assert.match(ui.texto(), /\(E\)/);
  assert.match(ui.texto(), /Preço desconhecido/);
  assert.match(ui.texto(), /Outro interesse ainda pode aceitar/);
  await ui.alterar("nome", "SSD gratuito");
  await ui.alterar("palavras_chave", "SSD, Kingston, ,");
  await ui.alterar("modo_palavras", "todas");
  await ui.alterar("categoria", "eletronicos");
  await ui.alterar("preco_max", "0");
  await ui.clicar("Criar filtro");
  assert.equal(ui.linhas[0].ativo, true);
  assert.equal(ui.linhas[0].preco_max, 0);
  assert.deepEqual(ui.linhas[0].palavras_chave, ["SSD", "Kingston"]);
  assert.match(ui.texto(), /Máx. R\$ 0.00/);
  assert.match(ui.texto(), /Todos os termos de inclusão/);
  await ui.clicar("Pausar", ui.artigo("SSD gratuito"));
  assert.deepEqual(ui.chamadas.filter((c) => c.metodo === "PUT").at(-1).corpo, { ativo: false });

  await ui.alterar("nome", "Veto sintético");
  await ui.alterar("palavras_chave", "Inclusão a limpar");
  await ui.alterar("categoria", "casa");
  await ui.alterar("preco_max", "10");
  await ui.alterar("tipo_regra", "bloqueio_global");
  for (const id of ["palavras_chave", "categoria", "preco_max"]) {
    assert.equal(ui.campo(id).props.value, ""); assert.equal(ui.campo(id).props.disabled, true);
  }
  assert.match(ui.texto(), /são limpos explicitamente/);
  assert.match(ui.texto(), /Nenhum interesse pode sobrepor um veto global/);
  await ui.alterar("palavras_bloqueio", "usado, recondicionado");
  await ui.clicar("Criar filtro");
  assert.equal(ui.linhas[1].modo_palavras, "qualquer");
  assert.equal(ui.linhas[1].tipo_regra, "bloqueio_global");
  assert.deepEqual(ui.linhas[1].palavras_chave, []);
  assert.equal(ui.linhas[1].categoria, null); assert.equal(ui.linhas[1].preco_max, null);
  assert.match(ui.texto(), /Veto global: usado, recondicionado/);
  await ui.clicar("Pausar", ui.artigo("Veto sintético"));
  assert.equal(ui.linhas[1].ativo, false);
  await ui.clicar("Editar", ui.artigo("Veto sintético"));
  await ui.alterar("modo_palavras", "todas");
  await ui.clicar("Atualizar");
  assert.equal(ui.linhas[1].ativo, false); assert.equal(ui.linhas[1].modo_palavras, "todas");
  assert.match(ui.texto(), /Todos os termos de bloqueio/);
  await ui.clicar("Ativar", ui.artigo("Veto sintético"));
  assert.deepEqual(ui.chamadas.filter((c) => c.metodo === "PUT").at(-1).corpo, { ativo: true });
});

test("editar interesse pausado mantém zero e não envia ativo; toggle só envia ativo", async () => {
  const ui = ambiente([regra()]); await ui.estabilizar();
  await ui.clicar("Editar", ui.artigo("Interesse pausado"));
  assert.equal(ui.campo("preco_max").props.value, "0");
  assert.equal(ui.campo("modo_palavras").props.value, "todas");
  await ui.alterar("nome", "Editado pausado"); await ui.alterar("modo_palavras", "qualquer");
  await ui.clicar("Atualizar");
  const payload = ui.chamadas.find((c) => c.metodo === "PUT").corpo;
  assert.equal(Object.hasOwn(payload, "ativo"), false);
  assert.equal(payload.preco_max, 0); assert.equal(payload.tipo_regra, "interesse");
  assert.equal(ui.linhas[0].ativo, false); assert.match(ui.texto(), /Pausado/);
  assert.match(ui.texto(), /Veto local \(qualquer\): usado/);
  await ui.clicar("Ativar", ui.artigo("Editado pausado"));
  assert.deepEqual(ui.chamadas.filter((c) => c.metodo === "PUT").at(-1).corpo, { ativo: true });
  await ui.clicar("Excluir", ui.artigo("Editado pausado"));
  assert.equal(ui.linhas.length, 0);
});

test("erro de servidor não limpa edição nem finge sucesso; schema não vira lista vazia válida", async () => {
  const ui = ambiente([regra()]); await ui.estabilizar();
  await ui.clicar("Editar", ui.artigo("Interesse pausado"));
  await ui.alterar("nome", "Não salvo"); ui.falhar("Serviço indisponível");
  await ui.clicar("Atualizar");
  assert.match(ui.html(), /role="alert"/); assert.match(ui.texto(), /Serviço indisponível/);
  assert.equal(ui.campo("nome").props.value, "Não salvo");
  assert.equal(ui.linhas[0].nome, "Interesse pausado");
  assert.match(ui.texto(), /Editar filtro/);
  const vazio = ambiente(); vazio.falhar("Erro interno do servidor"); await vazio.estabilizar();
  assert.match(vazio.texto(), /Erro interno do servidor/);
  assert.doesNotMatch(vazio.texto(), /Nenhum filtro criado/);
});

test("edição de arrays legados nulos mantém o formulário utilizável e o estado pausado", async () => {
  const ui = ambiente([regra({ palavras_chave: null, palavras_bloqueio: null })]);
  await ui.estabilizar();
  await ui.clicar("Editar", ui.artigo("Interesse pausado"));
  assert.equal(ui.campo("palavras_chave").props.value, "");
  assert.equal(ui.campo("palavras_bloqueio").props.value, "");
  await ui.clicar("Atualizar");
  assert.equal(ui.linhas[0].ativo, false);
});

test("validação local impede global vazio, duplicatas e moeda inválida sem chamada de gravação", async () => {
  const ui = ambiente(); await ui.estabilizar();
  await ui.alterar("nome", "Regra"); await ui.alterar("tipo_regra", "bloqueio_global");
  await ui.clicar("Criar filtro"); assert.match(ui.texto(), /exige termos de bloqueio/);
  await ui.alterar("palavras_bloqueio", "Usádo, usado");
  await ui.clicar("Criar filtro"); assert.match(ui.texto(), /duplicados/);
  await ui.alterar("tipo_regra", "interesse"); await ui.alterar("palavras_bloqueio", "");
  for (const preco of ["1.001", "-1", "100000000", "Infinity"]) {
    await ui.alterar("preco_max", preco); await ui.clicar("Criar filtro");
    assert.match(ui.texto(), /Preço deve estar/);
  }
  assert.equal(ui.chamadas.some((c) => c.metodo !== "GET"), false);
});

test("card mostra gratuidade e não inventa desconto com anterior menor/igual", () => {
  const ui = ambiente();
  const Card = ui.carregar("components/ProdutoCard.tsx").ProdutoCard;
  const produto = { id: 1, titulo: "SSD sintético", preco: 0, preco_original: 99,
    categoria: "eletronicos", canais: [], criado_em: "2026-10-23T00:00:00Z" };
  const gratuito = renderToStaticMarkup(Card({ produto }));
  assert.match(gratuito, /R\$ 0.00/); assert.match(gratuito, /-100%/);
  for (const preco_original of [0, 9, 10, null]) {
    assert.doesNotMatch(renderToStaticMarkup(Card({ produto: { ...produto, preco: 10, preco_original } })), /produto__badge/);
  }
});

test("nomes e termos recebidos da API são texto escapado, nunca HTML executável", async () => {
  const ui = ambiente([regra({ nome: '<script>alert("sintético")</script>',
    palavras_bloqueio: ['<img src=x onerror="alert(1)">'] })]);
  await ui.estabilizar();
  assert.match(ui.html(), /&lt;script&gt;/);
  assert.match(ui.html(), /&lt;img/);
  assert.doesNotMatch(ui.html(), /<script>|<img src="?x/);
});
